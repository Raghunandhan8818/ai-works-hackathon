"""
Temporal activities for AutoFixConsumerWorkflow.

Queue routing:
  rib-io  — clone_and_branch_activity, commit_push_fix_activity,
             create_fix_pr_activity, comment_fix_prs_on_producer_activity
  rib-cpu — run_claude_code_fix_activity
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
from pathlib import Path
from uuid import uuid4

import anthropic
import httpx
from temporalio import activity

logger = logging.getLogger(__name__)

_WORKSPACE_ROOT = Path(os.environ.get("RIB_WORKSPACE_ROOT", "/tmp/ripple-workspaces"))


def _inject_token(repo_url: str, github_token: str) -> str:
    """Embed GitHub token into an HTTPS clone URL so git push works without interactive auth."""
    if not github_token:
        return repo_url
    # ssh → https conversion
    url = re.sub(r"^git@github\.com:", "https://github.com/", repo_url)
    # inject token
    return re.sub(r"^https://", f"https://{github_token}@", url, count=1)


def _parse_owner_repo(repo_url: str) -> str | None:
    url = repo_url.rstrip("/").removesuffix(".git")
    m = re.search(r"github\.com[/:]([^/]+/[^/]+)$", url)
    if m:
        return m.group(1)
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", url):
        return url
    return None


# ── Activity 1: Clone consumer repo + create fix branch ───────────────────────

@activity.defn(name="clone_and_branch_activity")
async def clone_and_branch_activity(payload: dict) -> dict:
    """Clone the consumer repo and check out a new ripple/fix-* branch."""
    consumer_repo_url: str = payload["consumer_repo_url"]
    branch_name: str = payload["branch_name"]
    github_token: str = payload.get("github_token", "")
    workflow_run_id: str = payload["workflow_run_id"]

    workspace = _WORKSPACE_ROOT / workflow_run_id / "fix" / uuid4().hex[:8]
    workspace.mkdir(parents=True, exist_ok=True)

    clone_url = _inject_token(consumer_repo_url, github_token)

    result = subprocess.run(
        ["git", "clone", clone_url, str(workspace)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to clone {consumer_repo_url}: {result.stderr.strip()}")

    # Set git identity so the commit isn't rejected
    subprocess.run(["git", "-C", str(workspace), "config", "user.email", "ripple-bot@ripple.ai"], check=False)
    subprocess.run(["git", "-C", str(workspace), "config", "user.name", "Ripple Bot"], check=False)

    result = subprocess.run(
        ["git", "-C", str(workspace), "checkout", "-b", branch_name],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to create branch {branch_name}: {result.stderr.strip()}")

    logger.info("clone_and_branch_activity workspace=%s branch=%s", workspace, branch_name)
    return {"workspace": str(workspace)}


_FIX_MODEL = os.environ.get("RIPPLE_FIX_MODEL", "claude-sonnet-4-6")
_SOURCE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".py", ".java", ".kt", ".go", ".rb", ".cs"}
_SKIP_DIRS = {"node_modules", ".git", "target", "build", "dist", "__pycache__", ".gradle", "vendor"}


# ── Activity 2: Apply fixes via per-file Claude API calls ─────────────────────

@activity.defn(name="run_claude_code_fix_activity")
async def run_claude_code_fix_activity(payload: dict) -> dict:
    """
    Fix consumer files one at a time — one focused Claude API call per file.
    Eliminates the non-determinism of asking Claude to fix 10+ files in one shot.
    """
    workspace: str = payload["workspace"]
    producer_service: str = payload["producer_service"]
    field_changes: list[dict] = payload["field_changes"]
    breaking_impacts: list[dict] = payload["breaking_impacts"]

    # Extract chosen_strategy from the first breaking impact that has one
    chosen_strategy = ""
    for impact in breaking_impacts:
        if impact.get("chosen_strategy"):
            chosen_strategy = impact["chosen_strategy"]
            break

    # Build search terms: field names + endpoint path segments (skip bare HTTP status codes)
    _STATUS_CODE_RE = re.compile(r"^\d{3}$")
    search_terms = list({
        t for t in (
            c.get("old_field_name") or c.get("field_name")
            for c in field_changes
            if c.get("old_field_name") or c.get("field_name")
        )
        if t and not _STATUS_CODE_RE.match(t)
    })
    # Also add endpoint path segments so behavioral-change interrupts find the right files
    for c in field_changes:
        ep = c.get("endpoint_path", "")
        for segment in re.split(r"[/\-_]", ep):
            if len(segment) > 3 and not _STATUS_CODE_RE.match(segment):
                search_terms.append(segment)

    # Collect affected files via grep + explicit impact locations
    affected_files = _find_affected_files(workspace, search_terms)
    for impact in breaking_impacts:
        fp = impact.get("file_path", "")
        if fp:
            abs_path = Path(workspace) / fp
            if abs_path.exists():
                affected_files.setdefault(str(abs_path), fp)

    if not affected_files:
        logger.warning("run_claude_code_fix_activity no affected files workspace=%s", workspace)
        return {"success": False, "output": "No files found referencing changed fields"}

    # Build producer change summary once — shared across all per-file calls
    producer_summary = _build_producer_summary(producer_service, field_changes)

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    total_files_fixed = 0
    file_results: list[str] = []

    for abs_path, rel_path in list(affected_files.items())[:20]:
        try:
            content = Path(abs_path).read_text(errors="replace")
        except Exception:
            continue

        # Find which breaking impacts reference this file
        file_impacts = [
            i for i in breaking_impacts
            if i.get("file_path", "").endswith(rel_path.split("/")[-1])
        ]

        user_prompt = _build_per_file_prompt(
            rel_path, content, producer_summary, field_changes, file_impacts, chosen_strategy
        )

        try:
            response = client.messages.create(
                model=_FIX_MODEL,
                max_tokens=4096,
                system=_PER_FILE_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
            raw = response.content[0].text
        except Exception as exc:
            logger.error("run_claude_code_fix_activity API error file=%s: %s", rel_path, exc)
            continue

        applied = _apply_single_file_edits(workspace, rel_path, raw)
        if applied > 0:
            total_files_fixed += 1
            file_results.append(f"{rel_path}: {applied} replacement(s)")
            logger.info("fixed %s (%d replacements)", rel_path, applied)
        else:
            logger.info("no changes needed in %s", rel_path)

    logger.info(
        "run_claude_code_fix_activity done files_fixed=%d/%d",
        total_files_fixed, len(affected_files),
    )
    summary = f"Fixed {total_files_fixed}/{len(affected_files)} files: " + ", ".join(file_results)
    return {"success": total_files_fixed > 0, "output": summary}


_PER_FILE_SYSTEM_PROMPT = """\
You are fixing a single source file to align it with a breaking API contract change in its producer service.

OUTPUT FORMAT — CRITICAL:
Return ONLY a raw JSON array of search/replace pairs. No prose, no markdown, no explanation.

[
  {"from": "exact verbatim string from the file", "to": "replacement string"},
  {"from": "second occurrence needing a different replacement", "to": "replacement string"}
]

RULES:
- Each "from" must be an EXACT substring present in the file — copy character-for-character
- Add one entry per distinct occurrence that needs changing (duplicates need duplicate entries)
- For FIELD_REMOVED / FIELD_RENAMED changes: rename/update identifiers that reference the old field
- For BEHAVIORAL_CHANGE / SEMANTIC_UNIT_CHANGE: update API call parameters, response handling, or
  display logic that is directly affected by the described behavior change. Apply the CHOSEN STRATEGY
  if one is provided — that is the human-approved migration path.
- Do NOT change UI display labels (e.g. keep the label text "Full Name:", change only the JS key)
- Do NOT add new business logic beyond what the chosen strategy explicitly describes
- If this file needs NO changes (it does not reference the changed endpoint or field), return: []"""


def _build_producer_summary(producer_service: str, field_changes: list[dict]) -> str:
    """One compact block describing what changed in the producer — shared across all file prompts."""
    lines = [f"Producer service `{producer_service}` made these breaking API changes:"]
    for c in field_changes:
        old = c.get("old_field_name") or c["field_name"]
        new = c["field_name"]
        rename = f"`{old}` → `{new}`" if old != new else f"`{old}` (unchanged name)"
        ep = c.get("endpoint_path", "")
        endpoint_note = f"  Endpoint: {ep}\n" if ep else ""
        lines.append(
            f"  • {rename}  [{c['change_type']}]\n"
            f"{endpoint_note}"
            f"    Before: {c.get('old_description', '—')}\n"
            f"    After:  {c.get('new_description', '—')}\n"
            f"    Intent: {c.get('semantic_intent', '—')}"
        )
    return "\n".join(lines)


def _build_per_file_prompt(
    rel_path: str,
    content: str,
    producer_summary: str,
    field_changes: list[dict],
    file_impacts: list[dict],
    chosen_strategy: str = "",
) -> str:
    impact_block = ""
    if file_impacts:
        impact_lines = "\n".join(
            f"  • line {i.get('line', '?')}: {i.get('explanation', '')} — suggested fix: {i.get('suggested_fix', '')}"
            for i in file_impacts
        )
        impact_block = f"\nKnown breaking locations in this file:\n{impact_lines}\n"

    prompt = f"""{producer_summary}
{impact_block}
Fix this file — `{rel_path}`:
```
{content}
```

Return a JSON array of search/replace pairs for every change needed in this file.
If no changes are needed, return []."""

    if chosen_strategy:
        prompt += f"\n\nCHOSEN MIGRATION STRATEGY (the human selected this — apply it exactly):\n{chosen_strategy}\n"

    return prompt


def _find_affected_files(workspace: str, search_terms: list[str]) -> dict[str, str]:
    """Return {{abs_path: rel_path}} for source files containing any search term."""
    if not search_terms:
        return {}
    pattern = "|".join(re.escape(t) for t in search_terms if t)
    if not pattern:
        return {}

    include_args = [arg for ext in _SOURCE_EXTENSIONS for arg in ("--include", f"*{ext}")]
    exclude_args = [arg for d in _SKIP_DIRS for arg in ("--exclude-dir", d)]

    try:
        result = subprocess.run(
            ["grep", "-rl", "-E", pattern, *include_args, *exclude_args, workspace],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {}

    files: dict[str, str] = {}
    for line in result.stdout.splitlines():
        abs_path = line.strip()
        if not abs_path:
            continue
        try:
            rel = str(Path(abs_path).relative_to(workspace))
            files[abs_path] = rel
        except ValueError:
            continue
    return files


def _apply_single_file_edits(workspace: str, rel_path: str, raw: str) -> int:
    """Apply per-file Claude response to one file on disk.

    Claude returns a flat array of {"from": ..., "to": ...} pairs (no "file" wrapper).
    Also accepts {"content": ...} for full file overwrite as fallback.
    """
    target = Path(workspace) / rel_path

    # Handle full-file overwrite format
    start_brace = raw.find("{")
    start_bracket = raw.find("[")
    if start_brace >= 0 and (start_bracket < 0 or start_brace < start_bracket):
        # Might be a single object — check for "content" key
        try:
            obj = json.loads(raw[start_brace: raw.rfind("}") + 1])
            if "content" in obj:
                target.write_text(obj["content"])
                return 1
        except (json.JSONDecodeError, ValueError):
            pass

    start = raw.find("[")
    end = raw.rfind("]") + 1
    if start < 0 or end <= start:
        logger.warning("_apply_single_file_edits: no JSON array in response for %s", rel_path)
        return 0

    try:
        pairs = json.loads(raw[start:end])
    except json.JSONDecodeError as exc:
        logger.warning("_apply_single_file_edits parse failed %s: %s", rel_path, exc)
        return 0

    if not pairs:
        return 0  # Claude returned [] — file needs no changes

    try:
        content = target.read_text(errors="replace")
    except Exception as exc:
        logger.error("_apply_single_file_edits read failed %s: %s", rel_path, exc)
        return 0

    changed = False
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        from_str = pair.get("from", "")
        to_str = pair.get("to", "")
        if not from_str:
            continue
        if from_str in content:
            content = content.replace(from_str, to_str, 1)
            changed = True
        else:
            logger.warning("_apply_single_file_edits 'from' not found in %s: %r", rel_path, from_str[:80])

    if changed:
        target.write_text(content)
        return 1
    return 0


def _infer_extensions(workspace: str) -> list[str]:
    markers = {
        "package.json":     ["*.js", "*.jsx", "*.ts", "*.tsx"],
        "pom.xml":          ["*.java"],
        "build.gradle":     ["*.java", "*.kt"],
        "build.gradle.kts": ["*.java", "*.kt"],
        "go.mod":           ["*.go"],
        "pyproject.toml":   ["*.py"],
        "requirements.txt": ["*.py"],
        "Cargo.toml":       ["*.rs"],
    }
    for marker, exts in markers.items():
        if Path(workspace, marker).exists():
            return exts
    return ["*.js", "*.jsx", "*.ts", "*.tsx", "*.py", "*.java", "*.go"]


def _build_fix_prompt(
    workspace: str,
    producer_service: str,
    field_changes: list[dict],
    breaking_impacts: list[dict],
) -> str:
    # Build rename map: old_name → new_name for searchable substitutions
    renames = []
    enum_changes = []
    for c in field_changes:
        old = c.get("old_field_name", "") or c.get("field_name", "")
        new = c.get("field_name", "")
        change_type = c.get("change_type", "")
        if old and old != new:
            renames.append((old, new, c.get("old_description", ""), c.get("new_description", "")))
        if change_type == "ENUM_CHANGE":
            enum_changes.append((old or new, c.get("old_description", ""), c.get("new_description", "")))

    rename_lines = "\n".join(
        f"  - `{old}` → `{new}`  (was: {old_desc[:80]}, now: {new_desc[:80]})"
        for old, new, old_desc, new_desc in renames
    ) or "  (no simple renames — see semantic changes below)"

    semantic_lines = "\n".join(
        f"  - `{c['field_name']}` ({c['change_type']}): {c.get('old_description','?')[:100]} → {c.get('new_description','?')[:100]}"
        for c in field_changes
        if not c.get("old_field_name") or c.get("old_field_name") == c.get("field_name")
    )

    search_terms = " ".join(f'"{old}"' for old, _, _, _ in renames) if renames else ""
    include_flags = " ".join(f"--include='{e}'" for e in _infer_extensions(workspace))

    impact_parts: list[str] = []
    for idx, impact in enumerate(breaking_impacts, 1):
        evidence_lines = "\n    ".join(str(e) for e in impact.get("evidence", [])[:3])
        impact_parts.append(
            f"  {idx}. `{impact.get('file_path', '?')}` line {impact.get('line', '?')}\n"
            f"     Why it breaks: {impact.get('explanation', '')}\n"
            f"     Suggested fix: {impact.get('suggested_fix', '')}\n"
            + (f"     Evidence: {evidence_lines}\n" if evidence_lines else "")
        )
    impacts_text = "".join(impact_parts) or "  (use the rename map above to find affected usages)"

    return f"""You are fixing breaking API contract changes in this consumer service codebase.
The producer service `{producer_service}` changed its API and this consumer needs to be updated.

## Step 1 — Field renames to apply everywhere

These API field names changed. Find and fix ALL occurrences in the codebase,
both in production source files AND test files:

{rename_lines}

{"## Enum/value changes" + chr(10) + "  " + chr(10).join(f"- {f}: {o[:80]} → {n[:80]}" for f,o,n in enum_changes) if enum_changes else ""}

{"## Other semantic changes" + chr(10) + semantic_lines if semantic_lines.strip() else ""}

## Step 2 — Search strategy

Run these searches to find every file that needs updating:
{"1. Bash: grep -rn " + search_terms + " src/ " + include_flags if search_terms else "1. Search source files for changed field names"}
2. Pay special attention to:
   - API/service files (*Service.js, api/*.js, *Api.js) — these send/receive the field names
   - Component files (*.jsx, *.tsx) — these read API responses and build request payloads
   - Test files — update mocks/assertions to match new field names

## Step 3 — Known breaking locations (from static analysis)

{impacts_text}

## Rules
- Fix EVERY occurrence you find — not just the listed locations above
- Do NOT change UI display labels (e.g. keep "Full Name:" as a label, only change the API field key)
- Do NOT change internal variable names unless they shadow the API field name in a confusing way
- After all edits, briefly summarize what you changed

Make all fixes now.
"""


# ── Activity 3: Commit and push the fix branch ────────────────────────────────

@activity.defn(name="commit_push_fix_activity")
async def commit_push_fix_activity(payload: dict) -> dict:
    """Stage all changes, commit, and push the fix branch to origin."""
    workspace: str = payload["workspace"]
    branch_name: str = payload["branch_name"]
    producer_service: str = payload["producer_service"]
    field_name: str = payload["field_name"]
    consumer_repo_url: str = payload.get("consumer_repo_url", "")
    # RIPPLE_GITHUB_TOKEN is a bot token with write access to consumer repos.
    # Falls back to the per-request github_token (producer token, may lack write access).
    github_token: str = (
        os.environ.get("RIPPLE_GITHUB_TOKEN", "")
        or payload.get("github_token", "")
    )

    # Stage any new changes
    subprocess.run(["git", "-C", workspace, "add", "-A"], check=False)

    status = subprocess.run(
        ["git", "-C", workspace, "status", "--porcelain"],
        capture_output=True, text=True, check=False,
    )

    if status.stdout.strip():
        # There are uncommitted changes — commit them now
        commit_msg = (
            f"fix: update consumer for {producer_service} `{field_name}` contract change\n\n"
            "Automated fix applied by Ripple autonomous fix agent.\n"
            "Review the changes before merging."
        )
        result = subprocess.run(
            ["git", "-C", workspace, "commit", "-m", commit_msg],
            capture_output=True, text=True, check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git commit failed: {result.stderr.strip()}")
    else:
        # No uncommitted changes — check if there are commits not yet pushed
        # (happens on retry after a push failure)
        if not _has_unpushed_commits(workspace, branch_name):
            logger.warning("commit_push_fix_activity nothing to push workspace=%s", workspace)
            return {"pushed": False, "reason": "no_changes"}
        logger.info("commit_push_fix_activity retrying push of existing commits branch=%s", branch_name)

    # Inject token into remote URL so push is authenticated
    if github_token and consumer_repo_url:
        auth_url = _inject_token(consumer_repo_url, github_token)
        subprocess.run(
            ["git", "-C", workspace, "remote", "set-url", "origin", auth_url],
            check=False,
        )

    result = subprocess.run(
        ["git", "-C", workspace, "push", "origin", branch_name],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"git push failed: {result.stderr.strip()}")

    logger.info("commit_push_fix_activity pushed branch=%s", branch_name)
    return {"pushed": True}


def _has_unpushed_commits(workspace: str, branch_name: str) -> bool:
    """Return True if there are local commits on branch_name not yet on the remote."""
    # Try to compare against the remote tracking branch
    fetch = subprocess.run(
        ["git", "-C", workspace, "fetch", "origin", branch_name],
        capture_output=True, text=True, check=False,
    )
    if fetch.returncode != 0:
        # Remote branch doesn't exist yet — we definitely have commits to push
        # Verify there's at least one local commit on this branch
        log = subprocess.run(
            ["git", "-C", workspace, "log", branch_name, "--oneline", "-1"],
            capture_output=True, text=True, check=False,
        )
        return bool(log.stdout.strip())

    ahead = subprocess.run(
        ["git", "-C", workspace, "log", f"origin/{branch_name}..HEAD", "--oneline"],
        capture_output=True, text=True, check=False,
    )
    return bool(ahead.stdout.strip())


# ── Activity 4: Create PR on the consumer repo ────────────────────────────────

@activity.defn(name="create_fix_pr_activity")
async def create_fix_pr_activity(payload: dict) -> dict:
    """Open a GitHub PR from the fix branch against the consumer repo's default branch."""
    consumer_repo_url: str = payload["consumer_repo_url"]
    branch_name: str = payload["branch_name"]
    producer_service: str = payload["producer_service"]
    producer_pr_url: str = payload.get("producer_pr_url", "")
    field_changes: list[dict] = payload["field_changes"]
    breaking_impacts: list[dict] = payload["breaking_impacts"]
    github_token: str = (
        payload.get("github_token", "")
        or os.environ.get("RIPPLE_GITHUB_TOKEN")
        or os.environ.get("GITHUB_TOKEN", "")
    )

    owner_repo = _parse_owner_repo(consumer_repo_url)
    if not owner_repo:
        return {"pr_url": "", "success": False, "error": f"Cannot parse repo URL: {consumer_repo_url}"}

    base_branch = await _get_default_branch(owner_repo, github_token) or "main"

    field_names = ", ".join(c["field_name"] for c in field_changes[:3])
    title = f"fix: update consumer for {producer_service} contract change ({field_names})"
    body = _build_pr_body(producer_service, producer_pr_url, field_changes, breaking_impacts)

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{owner_repo}/pulls",
            headers=headers,
            json={"title": title, "body": body, "head": branch_name, "base": base_branch},
        )

    if resp.status_code not in (200, 201):
        logger.error(
            "create_fix_pr_activity HTTP %d repo=%s body=%s",
            resp.status_code, owner_repo, resp.text[:200],
        )
        return {
            "pr_url": "",
            "success": False,
            "error": f"GitHub API {resp.status_code}: {resp.text[:200]}",
        }

    pr_url = resp.json().get("html_url", "")
    logger.info("create_fix_pr_activity created pr_url=%s", pr_url)
    return {"pr_url": pr_url, "success": True}


def _build_pr_body(
    producer_service: str,
    producer_pr_url: str,
    field_changes: list[dict],
    breaking_impacts: list[dict],
) -> str:
    producer_link = f"[producer PR]({producer_pr_url})" if producer_pr_url else "the producer service"
    changes_md = "\n".join(
        f"- `{c['field_name']}` ({c['change_type']}): "
        f"_{c.get('old_description', '?')}_ → _{c.get('new_description', '?')}_"
        for c in field_changes
    )
    impacts_md = "\n".join(
        f"- `{i.get('file_path', '?')}:{i.get('line', '?')}` — {i.get('explanation', '')}"
        for i in breaking_impacts
    )
    return f"""## Ripple Auto-Fix

This PR was automatically generated by **Ripple** in response to a breaking contract change in `{producer_service}`.

### What changed upstream
{changes_md}

See {producer_link} for full context.

### What was fixed in this PR
{impacts_md}

### Review checklist
- [ ] Verify the fix is semantically correct for your use case
- [ ] Run the test suite to confirm no regressions
- [ ] Merge only after the upstream `{producer_service}` change is merged

---
*Generated by [Ripple](https://github.com/) — semantic contract firewall*
"""


async def _get_default_branch(owner_repo: str, github_token: str) -> str | None:
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"https://api.github.com/repos/{owner_repo}", headers=headers)
        if resp.status_code == 200:
            return resp.json().get("default_branch")
    except Exception:
        pass
    return None


# ── Activity 5: Post fix PR links back on producer PR ─────────────────────────

@activity.defn(name="comment_fix_prs_on_producer_activity")
async def comment_fix_prs_on_producer_activity(payload: dict) -> dict:
    """
    After all consumer fix PRs are created, post a follow-up comment on the
    producer PR so the author can see what was auto-fixed downstream.
    """
    repo_url: str = payload["repo_url"]
    pr_number: int = payload["pr_number"]
    fix_results: list[dict] = payload["fix_results"]
    github_token: str = payload["github_token"]

    owner_repo = _parse_owner_repo(repo_url)
    if not owner_repo:
        return {"success": False, "error": "Cannot parse repo URL"}

    successful = [r for r in fix_results if r.get("pr_url")]
    if not successful:
        logger.info("comment_fix_prs_on_producer_activity no successful fixes to report")
        return {"success": True, "skipped": True}

    lines = [
        "## Ripple: Auto-Fix PRs Raised\n",
        "Ripple detected breaking consumer impacts and automatically raised fix PRs:\n",
    ]
    for r in successful:
        consumer = r.get("consumer_service", "?")
        pr_url = r.get("pr_url", "")
        lines.append(f"- **`{consumer}`** → {pr_url}")

    failed = [r for r in fix_results if not r.get("pr_url")]
    if failed:
        lines.append("")
        lines.append("Could not auto-fix (manual review needed):")
        for r in failed:
            lines.append(f"- `{r.get('consumer_service', '?')}`: {r.get('error', 'unknown error')}")

    lines.append("\n---\n*[Ripple — semantic contract firewall]*")

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"https://api.github.com/repos/{owner_repo}/issues/{pr_number}/comments",
            headers=headers,
            json={"body": "\n".join(lines)},
        )

    success = resp.status_code in (200, 201)
    logger.info(
        "comment_fix_prs_on_producer_activity success=%s status=%d",
        success, resp.status_code,
    )
    return {"success": success}
