"""
Activities for the ConsolidatedPRReviewWorkflow and LearnFromFeedbackWorkflow.

Queue assignments:
  rib-llm  — run_architectural_review_activity, process_learn_command_activity
  rib-io   — post_consolidated_review_activity
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx
from temporalio import activity

from ripple.rib.graph.factory import get_store
from ripple.rib.graph.schema import ArchitecturalIntent

logger = logging.getLogger(__name__)


def _sonnet(system: str, user: str, max_tokens: int = 2048) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


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
      workspace: str — path to the cloned repo workspace
      diff_content: str — the PR diff text
      repo_full: str — "owner/repo" used as lookup key for learned intents
      service_name: str — service name for DB lookup
    """
    workspace: str = payload["workspace"]
    diff_content: str = payload["diff_content"]
    repo_full: str = payload.get("repo_full", "")

    # Read ARCHITECTURE.md from workspace if it exists
    arch_md_path = Path(workspace) / "ARCHITECTURE.md"
    arch_md_content = ""
    if arch_md_path.exists():
        arch_md_content = arch_md_path.read_text(encoding="utf-8", errors="ignore")[:8000]

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
        raw = _sonnet(_ARCH_REVIEW_SYSTEM, user_prompt, max_tokens=2048)
        # Strip markdown code fences if present
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
        raw = _sonnet(_LEARN_SYSTEM, user_prompt, max_tokens=512)
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

    try:
        get_store().upsert_architecture_intent(intent)
        logger.info("Stored architectural intent from /learn: repo=%s type=%s", repo_full, intent.constraint_type)
    except Exception:
        logger.warning("Failed to store architectural intent", exc_info=True)

    # Post acknowledgement reply on PR
    if github_token and repo_full:
        ack_body = (
            f"**Ripple learned:** {intent.natural_language}\n\n"
            f"*This rule will be applied to future PR reviews for `{repo_full}`.*"
        )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.github.com/repos/{repo_full}/issues/{pr_number}/comments",
                    headers={
                        "Authorization": f"Bearer {github_token}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={"body": ack_body},
                )
        except Exception:
            logger.warning("Failed to post /learn acknowledgement", exc_info=True)

    return {"stored": True, "constraint_type": intent.constraint_type, "natural_language": intent.natural_language}


# ── Activity 3: Post consolidated GitHub review ───────────────────────────────

def _format_consolidated_review(
    producer_service: str,
    contract_findings: dict,
    arch_findings: dict,
) -> str:
    field_changes: list[dict] = contract_findings.get("field_changes", [])
    impacts: list[dict] = contract_findings.get("impacts", [])
    fix_results: list[dict] = contract_findings.get("fix_results", [])

    breaking = [i for i in impacts if i.get("breaks")]
    summary_emoji = "🔴" if breaking else "✅"

    lines: list[str] = ["## Ripple Review\n"]

    # ── Contract Drift ────────────────────────────────────────────────────────
    lines.append("### Contract Drift\n")
    if not field_changes:
        lines.append("✅ No contract changes detected.\n")
    else:
        lines.append(f"{summary_emoji} **{len(breaking)} breaking contract change(s)** in `{producer_service}`\n")
        successful_fixes = [r for r in fix_results if r.get("pr_url")]
        if successful_fixes:
            lines.append("**Auto-fix PRs raised:**")
            for r in successful_fixes:
                lines.append(f"· `{r.get('consumer_service', '?')}` → {r.get('pr_url', '')}")
            lines.append("")
        failed_fixes = [r for r in fix_results if not r.get("pr_url")]
        if failed_fixes:
            lines.append("**Needs manual review:**")
            for r in failed_fixes:
                lines.append(f"· `{r.get('consumer_service', '?')}`: {r.get('error', 'unknown')}")
            lines.append("")

    # ── Architectural Violations ──────────────────────────────────────────────
    arch_violations = arch_findings.get("architectural_violations", [])
    lines.append("### Architectural Violations\n")
    if not arch_violations:
        lines.append("✅ No architectural violations detected.\n")
    else:
        for v in arch_violations:
            sev = v.get("severity", "MEDIUM")
            emoji = {"HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(sev, "🟡")
            lines.append(f"{emoji} **{sev}** — {v.get('description', '')}")
            if v.get("file"):
                lines.append(f"  *File:* `{v['file']}`")
            if v.get("suggestion"):
                lines.append(f"  *Suggestion:* {v['suggestion']}")
        lines.append("")

    # ── Security Concerns ─────────────────────────────────────────────────────
    security = arch_findings.get("security_concerns", [])
    lines.append("### Security Concerns\n")
    if not security:
        lines.append("✅ No security concerns detected.\n")
    else:
        for s in security:
            sev = s.get("severity", "MEDIUM")
            emoji = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟡"}.get(sev, "🟠")
            lines.append(f"{emoji} **{sev}** — {s.get('description', '')}")
            if s.get("suggestion"):
                lines.append(f"  *Suggestion:* {s['suggestion']}")
        lines.append("")

    # ── Performance Suggestions ───────────────────────────────────────────────
    perf = arch_findings.get("performance_suggestions", [])
    lines.append("### Performance Suggestions\n")
    if not perf:
        lines.append("✅ No performance issues detected.\n")
    else:
        for p in perf:
            lines.append(f"💡 {p.get('description', '')}")
            if p.get("suggestion"):
                lines.append(f"  *Suggestion:* {p['suggestion']}")
        lines.append("")

    # ── Best Practices ────────────────────────────────────────────────────────
    best = arch_findings.get("best_practices", [])
    if best:
        lines.append("### Best Practices\n")
        for b in best:
            lines.append(f"📌 {b.get('description', '')}")
            if b.get("suggestion"):
                lines.append(f"  *Suggestion:* {b['suggestion']}")
        lines.append("")

    lines.append("\n---\n*[Ripple — Agentic Code Review with Architectural Intent Understanding]*")
    lines.append("\n*Reply `/learn <correction>` on this comment to teach Ripple about your architecture.*")
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

    import re
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
