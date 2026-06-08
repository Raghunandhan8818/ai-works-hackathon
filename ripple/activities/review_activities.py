"""
Activities for the ConsolidatedPRReviewWorkflow and LearnFromFeedbackWorkflow.

Queue assignments:
  rib-llm  — run_architectural_review_activity, process_learn_command_activity
  rib-io   — post_consolidated_review_activity, read_arch_md_activity
"""
from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path

import httpx
from temporalio import activity

from ripple.rib.graph.factory import get_store
from ripple.rib.graph.schema import ArchitecturalIntent

logger = logging.getLogger(__name__)


async def _async_sonnet(system: str, user: str, max_tokens: int = 2048) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


# ── Activity 0: Read ARCHITECTURE.md (rib-io, co-located with workspace) ─────

@activity.defn(name="read_arch_md_activity")
async def read_arch_md_activity(workspace: str) -> str:
    """Reads ARCHITECTURE.md from a cloned workspace. Runs on rib-io where the workspace exists."""
    arch_md_path = Path(workspace) / "ARCHITECTURE.md"
    if arch_md_path.exists():
        return arch_md_path.read_text(encoding="utf-8", errors="ignore")[:8000]
    return ""


# ── Activity 1: Run architectural review ─────────────────────────────────────

_ARCH_REVIEW_SYSTEM = """\
You are a senior software architect performing a code review. You will be given:
1. A git diff from a pull request
2. Architectural constraints for this codebase (from ARCHITECTURE.md and learned rules)

Review the diff against the constraints and also check for general best practices, security concerns, and performance issues.

Return a JSON object with this structure:
{
  "architectural_violations": [
    {"severity": "HIGH|MEDIUM|LOW", "description": "...", "file": "...", "suggestion": "..."}
  ],
  "security_concerns": [
    {"severity": "HIGH|MEDIUM|LOW", "description": "...", "file": "...", "suggestion": "..."}
  ],
  "performance_suggestions": [
    {"severity": "MEDIUM|LOW", "description": "...", "file": "...", "suggestion": "..."}
  ],
  "best_practices": [
    {"severity": "MEDIUM|LOW", "description": "...", "file": "...", "suggestion": "..."}
  ]
}

Return only the JSON object. If a category has no findings, use an empty array.
Do not invent violations — only flag real issues visible in the diff.
"""


@activity.defn(name="run_architectural_review_activity")
async def run_architectural_review_activity(payload: dict) -> dict:
    """
    payload keys:
      arch_md_content: str — content of ARCHITECTURE.md (pre-read on rib-io via read_arch_md_activity)
      diff_content: str — the PR diff text
      repo_full: str — "owner/repo" used as lookup key for learned intents
    """
    arch_md_content: str = payload.get("arch_md_content", "")
    diff_content: str = payload["diff_content"]
    repo_full: str = payload.get("repo_full", "")

    # Load learned intents from DB
    learned_intents: list[str] = []
    try:
        store = get_store()
        intents = store.get_architecture_intents(repo_full)
        learned_intents = [i.natural_language for i in intents]
    except Exception:
        logger.warning("Could not load architecture intents from DB", exc_info=True)

    # Build constraints block
    constraints_parts: list[str] = []
    if arch_md_content:
        constraints_parts.append(f"## From ARCHITECTURE.md\n{arch_md_content}")
    if learned_intents:
        rules = "\n".join(f"- {r}" for r in learned_intents)
        constraints_parts.append(f"## Learned Rules (from /learn corrections)\n{rules}")

    if not constraints_parts and not diff_content.strip():
        return {"architectural_violations": [], "security_concerns": [], "performance_suggestions": [], "best_practices": []}

    constraints_block = "\n\n".join(constraints_parts) if constraints_parts else "(No architectural constraints defined for this repo)"
    user_prompt = f"## Architectural Constraints\n\n{constraints_block}\n\n## PR Diff\n\n```diff\n{diff_content[:12000]}\n```"

    try:
        raw = await _async_sonnet(_ARCH_REVIEW_SYSTEM, user_prompt, max_tokens=2048)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)
    except Exception:
        logger.warning("Architectural review Claude call failed", exc_info=True)
        return {"architectural_violations": [], "security_concerns": [], "performance_suggestions": [], "best_practices": []}


# ── Activity 2: Process /learn command ────────────────────────────────────────

_LEARN_SYSTEM = """\
You are extracting an architectural constraint from a developer's correction on a code review.

Given:
- The developer's correction text (from /learn command)
- The PR diff context

Extract a structured architectural constraint. Return a JSON object:
{
  "constraint_type": "DEPENDENCY|BOUNDED_CONTEXT|SECURITY|PERFORMANCE|NAMING|CUSTOM",
  "natural_language": "Clear, reusable rule statement that can guide future reviews",
  "encoded_rule": {
    "pattern": "what triggers this rule",
    "allowed": "what IS allowed",
    "forbidden": "what is NOT allowed"
  }
}

The natural_language field should be a complete, self-contained rule that makes sense without the PR context.
Return only the JSON object.
"""


@activity.defn(name="process_learn_command_activity")
async def process_learn_command_activity(payload: dict) -> dict:
    """
    payload keys:
      correction_text: str — text after /learn command
      diff_content: str — PR diff for context
      repo_full: str — "owner/repo"
      pr_number: int
      comment_id: str
      github_token: str
    """
    correction_text: str = payload["correction_text"]
    diff_context: str = payload.get("diff_content", "")[:4000]
    repo_full: str = payload["repo_full"]
    pr_number: int = payload["pr_number"]
    comment_id: str = payload.get("comment_id", "")
    github_token: str = payload.get("github_token", "") or os.environ.get("RIPPLE_GITHUB_TOKEN", "")

    user_prompt = f"Developer correction: {correction_text}\n\nPR diff context:\n```diff\n{diff_context}\n```"

    try:
        raw = await _async_sonnet(_LEARN_SYSTEM, user_prompt, max_tokens=512)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        extracted = json.loads(raw)
    except Exception:
        logger.warning("Learn command extraction failed", exc_info=True)
        extracted = {
            "constraint_type": "CUSTOM",
            "natural_language": correction_text,
            "encoded_rule": {},
        }

    pr_url = f"https://github.com/{repo_full}/pull/{pr_number}"
    intent = ArchitecturalIntent(
        repo=repo_full,
        constraint_type=extracted.get("constraint_type", "CUSTOM"),
        natural_language=extracted.get("natural_language", correction_text),
        encoded_rule=extracted.get("encoded_rule", {}),
        source="learned",
        pr_url=pr_url,
        pr_comment_id=str(comment_id),
    )

    stored = False
    try:
        get_store().upsert_architecture_intent(intent)
        stored = True
        logger.info("Stored architectural intent from /learn: repo=%s type=%s", repo_full, intent.constraint_type)
    except Exception:
        logger.error(
            "Failed to store architectural intent — DB write failed repo=%s rule=%s",
            repo_full, intent.natural_language, exc_info=True,
        )

    # Only post acknowledgement if the rule was actually persisted
    if stored and github_token and repo_full:
        ack_body = (
            f"**Ripple learned:** {intent.natural_language}\n\n"
            f"*This rule will be applied to future PR reviews for `{repo_full}`.*"
        )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"https://api.github.com/repos/{repo_full}/issues/{pr_number}/comments",
                    headers={
                        "Authorization": f"Bearer {github_token}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={"body": ack_body},
                )
                if resp.status_code not in (200, 201):
                    logger.warning(
                        "Failed to post /learn acknowledgement: HTTP %d %s",
                        resp.status_code, resp.text[:200],
                    )
        except Exception:
            logger.warning("Failed to post /learn acknowledgement", exc_info=True)

    return {"stored": stored, "constraint_type": intent.constraint_type, "natural_language": intent.natural_language}


# ── Activity 3: Post consolidated GitHub review ───────────────────────────────

def _format_consolidated_review(
    producer_service: str,
    contract_findings: dict,
    arch_findings: dict,
) -> str:
    field_changes: list[dict] = contract_findings.get("field_changes", [])
    impacts: list[dict] = contract_findings.get("impacts", [])
    fix_results: list[dict] = contract_findings.get("fix_results", [])

    arch_violations = arch_findings.get("architectural_violations", [])
    security = arch_findings.get("security_concerns", [])
    perf = arch_findings.get("performance_suggestions", [])
    best = arch_findings.get("best_practices", [])
    breaking = [i for i in impacts if i.get("breaks")]

    # ── Badge line ────────────────────────────────────────────────────────────
    def _contract_badge() -> str:
        if not field_changes:
            return "`CONTRACT: OK`"
        return f"`CONTRACT: {len(breaking)} breaking`" if breaking else f"`CONTRACT: {len(field_changes)} changed`"

    def _arch_badge() -> str:
        if not arch_violations:
            return "`ARCH: OK`"
        highs = sum(1 for v in arch_violations if v.get("severity") == "HIGH")
        meds = sum(1 for v in arch_violations if v.get("severity") == "MEDIUM")
        parts = []
        if highs:
            parts.append(f"{highs} HIGH")
        if meds:
            parts.append(f"{meds} MEDIUM")
        lows = len(arch_violations) - highs - meds
        if lows:
            parts.append(f"{lows} LOW")
        return f"`ARCH: {', '.join(parts)}`"

    def _security_badge() -> str:
        if not security:
            return "`SECURITY: OK`"
        highs = sum(1 for s in security if s.get("severity") == "HIGH")
        return f"`SECURITY: {highs} HIGH`" if highs else f"`SECURITY: {len(security)} issues`"

    lines: list[str] = [
        "## Ripple Review",
        "",
        f"{_contract_badge()} {_arch_badge()} {_security_badge()}",
        "",
    ]

    # ── Contract Changes ──────────────────────────────────────────────────────
    if field_changes:
        lines.append("**Contract Changes**")
        for fc in field_changes:
            fname = fc.get("field_name", fc.get("field_fqn", "?"))
            change = fc.get("change_summary", fc.get("change_type", "changed"))
            lines.append(f"- `{fname}` — {change}")
        successful_fixes = [r for r in fix_results if r.get("pr_url")]
        if successful_fixes:
            for r in successful_fixes:
                svc = r.get("consumer_service", "?")
                url = r.get("pr_url", "")
                lines.append(f"  - `{svc}` auto-fix → {url}")
        failed_fixes = [r for r in fix_results if not r.get("pr_url")]
        if failed_fixes:
            for r in failed_fixes:
                svc = r.get("consumer_service", "?")
                err = r.get("error", "needs manual review")
                lines.append(f"  - `{svc}` needs manual review — {err}")
        lines.append("")

    # ── Violations (arch + security combined) ─────────────────────────────────
    all_violations = (
        [("ARCH", v) for v in arch_violations]
        + [("SEC", s) for s in security]
    )
    if all_violations:
        lines.append("**Violations**")
        sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        all_violations.sort(key=lambda x: sev_order.get(x[1].get("severity", "LOW"), 2))
        for tag, v in all_violations:
            sev = v.get("severity", "MEDIUM")
            fname = v.get("file", "")
            desc = v.get("description", "")
            suggestion = v.get("suggestion", "")
            file_part = f" `{fname}`" if fname else ""
            fix_part = f" ({suggestion})" if suggestion else ""
            lines.append(f"- {sev} ·{file_part} — {desc}{fix_part}")
        lines.append("")

    # ── Suggestions (perf + best practices combined) ──────────────────────────
    suggestions = perf + best
    if suggestions:
        lines.append("**Suggestions**")
        for s in suggestions:
            desc = s.get("description", "")
            suggestion = s.get("suggestion", "")
            fix_part = f" ({suggestion})" if suggestion else ""
            lines.append(f"- {desc}{fix_part}")
        lines.append("")

    lines.append("---")
    lines.append("*Ripple · `/learn <rule>` to add architecture rules*")
    return "\n".join(lines)


@activity.defn(name="post_consolidated_review_activity")
async def post_consolidated_review_activity(payload: dict) -> dict:
    """
    payload keys:
      repo_url: str
      pr_number: int
      head_sha: str
      github_token: str
      producer_service: str
      contract_findings: dict  — {field_changes, impacts, fix_results}
      arch_findings: dict      — {architectural_violations, security_concerns, performance_suggestions, best_practices}
    """
    repo_url: str = payload["repo_url"]
    pr_number: int = payload["pr_number"]
    head_sha: str = payload.get("head_sha", "")
    github_token: str = payload.get("github_token", "") or os.environ.get("RIPPLE_GITHUB_TOKEN", "")
    producer_service: str = payload.get("producer_service", "")
    contract_findings: dict = payload.get("contract_findings", {})
    arch_findings: dict = payload.get("arch_findings", {})

    m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", repo_url)
    if not m:
        return {"success": False, "error": "Cannot parse repo_url"}
    repo_full = m.group(1)

    body = _format_consolidated_review(producer_service, contract_findings, arch_findings)

    if not github_token or not head_sha:
        logger.warning("post_consolidated_review: missing token or head_sha, skipping post")
        return {"success": False, "error": "missing token or head_sha", "preview": body[:200]}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.github.com/repos/{repo_full}/pulls/{pr_number}/reviews",
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                json={
                    "commit_id": head_sha,
                    "body": body,
                    "event": "COMMENT",
                    "comments": [],
                },
            )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {"success": True, "url": data.get("html_url", ""), "preview": body[:200]}
        else:
            logger.warning("GitHub review post failed: %s %s", resp.status_code, resp.text[:200])
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        logger.warning("post_consolidated_review_activity error: %s", e)
        return {"success": False, "error": str(e)}
