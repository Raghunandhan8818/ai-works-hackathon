from __future__ import annotations

import asyncio
import re
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ripple.activities.fix_activities import comment_fix_prs_on_producer_activity
    from ripple.activities.git_activities import cleanup_workspace_activity, get_pr_diff_activity
    from ripple.activities.pr_activities import (
        assess_consumer_impact_activity,
        parse_pr_diff_activity,
        post_github_review_activity,
        upsert_pr_disagreements_activity,
    )
    from ripple.workflows.auto_fix_consumer import AutoFixConsumerWorkflow

IO_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
LLM_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=5))

# Change types that can have multiple valid business-level migrations
_NEEDS_HUMAN_TYPES = {"BEHAVIORAL_CHANGE", "SEMANTIC_CHANGE", "UNIT_CHANGE"}
_URGENT_SEVERITIES = {"CRITICAL", "HIGH"}


def _build_knowledge_gap_options(fc: dict) -> list[dict]:
    """Build context-aware mitigation options for a knowledge-gap interrupt."""
    change_type = fc.get("change_type", "")
    old_desc = fc.get("old_description", "")
    new_desc = fc.get("new_description", "")
    intent = fc.get("semantic_intent", "")
    field = fc.get("field_name", "field")

    if change_type == "UNIT_CHANGE":
        # Unit changes: consumers may need to convert OR the producer should accept both
        return [
            {
                "id": "consumers_convert",
                "label": f"Consumers adapt — convert from old unit",
                "description": (
                    f"The new unit ({new_desc}) is the correct standard going forward. "
                    f"Ripple will raise fix PRs in all consumers to convert values from {old_desc}."
                ),
            },
            {
                "id": "producer_adapts",
                "label": "Producer adapts — keep backward-compatible unit",
                "description": (
                    f"Revert the unit change in the producer and maintain {old_desc} for backward compatibility. "
                    f"A versioned endpoint may be cleaner long-term."
                ),
            },
            {
                "id": "manual",
                "label": "I'll coordinate with consumers manually",
                "description": "Dismiss. Log decision to audit trail — no auto-fix triggered.",
            },
        ]

    if change_type == "BEHAVIORAL_CHANGE":
        # Behavioral inversions / logic changes
        return [
            {
                "id": "new_behavior_intentional",
                "label": "New behavior is intentional — update consumers",
                "description": (
                    f"{intent or f'The new behavior of {field} is intentional.'} "
                    f"Ripple will raise fix PRs in all known consumers to align with the new behavior."
                ),
            },
            {
                "id": "revert_behavior",
                "label": "Revert — this change is unintentional",
                "description": (
                    f"The behavioral change from '{old_desc[:80]}' to '{new_desc[:80]}' was not intended. "
                    f"Flag for the producer team to revert before merging."
                ),
            },
            {
                "id": "manual",
                "label": "I'll coordinate with consumers manually",
                "description": "Dismiss. Decision logged to audit trail — no auto-fix triggered.",
            },
        ]

    # SEMANTIC_CHANGE and others
    return [
        {
            "id": "confirm_and_fix",
            "label": "Confirm change — Ripple will fix consumers",
            "description": (
                f"{intent or f'The semantic change to {field} is intentional.'} "
                f"Ripple will scan all known consumers and raise targeted fix PRs."
            ),
        },
        {
            "id": "manual",
            "label": "I'll coordinate with consumers manually",
            "description": "Dismiss. Decision logged to audit trail — no auto-fix triggered.",
        },
    ]


@workflow.defn(name="AnalyzePRWorkflow")
class AnalyzePRWorkflow:
    def __init__(self) -> None:
        self._status: str = "pending"
        self._diff_path: str = ""
        self._lines_changed: int = 0
        self._field_changes: int = 0
        self._impacts: int = 0

    @workflow.query
    def diff_info(self) -> dict:
        return {
            "status": self._status,
            "diff_path": self._diff_path,
            "lines_changed": self._lines_changed,
            "field_changes": self._field_changes,
            "impacts": self._impacts,
        }

    @workflow.run
    async def run(self, request: dict) -> dict:
        repo_url: str = request["repo_url"]
        branch: str = request["branch"]
        base_branch: str = request["base_branch"]
        pr_number: int = request["pr_number"]
        head_commit: str = request.get("head_commit", "")
        producer_service: str = request.get("producer_service", "")
        import os as _os
        github_token: str = request.get("github_token", "") or _os.environ.get("RIPPLE_GITHUB_TOKEN") or _os.environ.get("GITHUB_TOKEN", "")
        workflow_run_id = workflow.info().run_id

        # ── Step 1: Clone + compute diff ──────────────────────────────────────
        self._status = "cloning"
        diff_result = await workflow.execute_activity(
            get_pr_diff_activity,
            args=[repo_url, branch, base_branch, pr_number, workflow_run_id],
            task_queue="rib-io",
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=IO_RETRY,
        )

        self._diff_path = diff_result["diff_path"]
        self._lines_changed = diff_result["lines_changed"]
        diff_content: str = diff_result.get("diff_content", "")

        # ── Step 2: Parse diff → changed field contracts ──────────────────────
        field_changes: list[dict] = []
        if diff_content.strip():
            self._status = "analyzing_diff"
            field_changes = await workflow.execute_activity(
                parse_pr_diff_activity,
                args=[{"diff": diff_content, "producer_service": producer_service}],
                task_queue="rib-llm",
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=LLM_RETRY,
            )
        self._field_changes = len(field_changes)

        # ── Step 3: Assess consumer impact for each changed field (parallel) ──
        all_impacts: list[dict] = []
        if field_changes:
            self._status = "assessing_impact"
            impact_results = await asyncio.gather(*[
                workflow.execute_activity(
                    assess_consumer_impact_activity,
                    args=[{"field_change": change, "producer_service": producer_service}],
                    task_queue="rib-llm",
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=LLM_RETRY,
                )
                for change in field_changes
            ])
            all_impacts = [impact for impacts in impact_results for impact in impacts]

            # ── Step 3.1: Synthesize knowledge-gap interrupts ──────────────────
            # For BEHAVIORAL_CHANGE / SEMANTIC_CHANGE / UNIT_CHANGE with CRITICAL/HIGH
            # severity: if the impact assessment found no breaking consumer impacts that
            # require human decision, the KG may be incomplete. Raise a producer-side
            # interrupt so the behavioral change doesn't silently ship.

            for i, fc in enumerate(field_changes):
                if fc.get("change_type") not in _NEEDS_HUMAN_TYPES:
                    continue
                if fc.get("severity_hint") not in _URGENT_SEVERITIES:
                    continue

                field_impacts = impact_results[i]
                already_has_human_interrupt = any(
                    imp.get("breaks") and imp.get("requires_human_decision")
                    for imp in field_impacts
                )
                if already_has_human_interrupt:
                    continue

                # No human-decision impact found — synthesize one on the producer side
                all_impacts.append({
                    "consumer_service": producer_service,
                    "consumer_repo_url": "",
                    "field_fqn": fc.get("field_fqn", fc.get("field_name", "")),
                    "file_path": fc.get("file_path", ""),
                    "line": fc.get("line", 0),
                    "breaks": True,
                    "requires_human_decision": True,
                    "is_test_only": False,
                    "severity": fc.get("severity_hint", "HIGH"),
                    "explanation": (
                        f"{fc['change_type']} in '{fc['field_name']}': "
                        f"{fc.get('old_description', '')} → {fc.get('new_description', '')}. "
                        f"Consumer knowledge graph coverage may be incomplete — manual review required."
                    ),
                    "human_decision_reason": (
                        f"'{fc['field_name']}' has a behavioral change that cannot be safely "
                        f"auto-fixed. {fc.get('semantic_intent', 'Please confirm how all consumers should handle this.')} "
                        f"Multiple migration strategies may be valid."
                    ),
                    "mitigation_options": _build_knowledge_gap_options(fc),
                    "suggested_fix": "",
                    "evidence": [
                        f"Before: {fc.get('old_description', '')}",
                        f"After: {fc.get('new_description', '')}",
                    ],
                })

        self._impacts = len(all_impacts)

        # ── Step 3.3: Write breaking impacts to DB as Disagreement records ────────
        if all_impacts:
            await workflow.execute_activity(
                upsert_pr_disagreements_activity,
                args=[{
                    "breaking_impacts": [i for i in all_impacts if i.get("breaks")],
                    "field_changes": field_changes,
                }],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=IO_RETRY,
            )

        # ── Step 3.5: Auto-fix breaking consumer impacts ───────────────────────
        fix_results: list[dict] = []
        # Only auto-fix impacts that don't need human decision
        auto_fix_impacts = [i for i in all_impacts if i.get("breaks") and not i.get("requires_human_decision", False)]

        if auto_fix_impacts and github_token:
            self._status = "auto_fixing"

            # Build producer PR URL for back-reference in fix PR descriptions
            owner_repo_m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", repo_url)
            producer_pr_url = (
                f"https://github.com/{owner_repo_m.group(1)}/pull/{pr_number}"
                if owner_repo_m else ""
            )

            # Group auto-fix impacts by consumer service
            consumers_to_fix: dict[str, list[dict]] = {}
            for impact in auto_fix_impacts:
                svc = impact["consumer_service"]
                consumers_to_fix.setdefault(svc, []).append(impact)

            fix_futures = []
            for consumer_service_name, impacts in consumers_to_fix.items():
                consumer_repo_url = impacts[0].get("consumer_repo_url", "")
                if not consumer_repo_url:
                    fix_results.append({
                        "consumer_service": consumer_service_name,
                        "pr_url": "",
                        "success": False,
                        "error": "consumer_repo_url not available in knowledge graph",
                    })
                    continue

                fix_futures.append(
                    workflow.execute_child_workflow(
                        AutoFixConsumerWorkflow.run,
                        args=[{
                            "consumer_service": consumer_service_name,
                            "consumer_repo_url": consumer_repo_url,
                            "producer_service": producer_service,
                            "producer_pr_url": producer_pr_url,
                            "field_changes": field_changes,
                            "breaking_impacts": impacts,
                            "github_token": github_token,
                        }],
                        id=f"autofix-{workflow.info().run_id[:8]}-{consumer_service_name}",
                        task_queue="rib",
                    )
                )

            if fix_futures:
                raw_results = await asyncio.gather(*fix_futures, return_exceptions=True)
                for r in raw_results:
                    if isinstance(r, dict):
                        fix_results.append(r)
                    else:
                        fix_results.append({"consumer_service": "?", "pr_url": "", "success": False, "error": str(r)})

        # ── Step 4: Format + post GitHub review ───────────────────────────────
        self._status = "posting_review"
        comment = _format_review_comment(
            producer_service, pr_number, field_changes, all_impacts, fix_results
        )
        inline_comments = _build_inline_comments(field_changes, all_impacts)
        review_url = ""
        review_posted = False

        if github_token and head_commit:
            post_result = await workflow.execute_activity(
                post_github_review_activity,
                args=[{
                    "repo_url": repo_url,
                    "pr_number": pr_number,
                    "head_sha": head_commit,
                    "comment": comment,
                    "inline_comments": inline_comments,
                    "github_token": github_token,
                }],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=IO_RETRY,
            )
            review_url = post_result.get("url", "")
            review_posted = post_result.get("success", False)

        # ── Step 4.5: Post fix PR links back on producer PR ──────────────────
        if fix_results and github_token:
            await workflow.execute_activity(
                comment_fix_prs_on_producer_activity,
                args=[{
                    "repo_url": repo_url,
                    "pr_number": pr_number,
                    "fix_results": fix_results,
                    "github_token": github_token,
                }],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=IO_RETRY,
            )

        # ── Step 5: Cleanup ───────────────────────────────────────────────────
        await workflow.execute_activity(
            cleanup_workspace_activity,
            args=[diff_result["workspace"]],
            task_queue="rib-io",
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=IO_RETRY,
        )

        self._status = "completed"

        return {
            "diff_path": self._diff_path,
            "lines_changed": self._lines_changed,
            "field_changes": field_changes,
            "impacts": all_impacts,
            "fix_results": fix_results,
            "review_url": review_url,
            "review_posted": review_posted,
            "comment_preview": comment[:500],
        }


# ── Inline comment builder ────────────────────────────────────────────────────

_SEVERITY_EMOJI = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}


def _build_inline_comments(field_changes: list[dict], impacts: list[dict]) -> list[dict]:
    """
    Build GitHub inline review comments — one per changed field that has a file/line.
    Each comment is placed at the producer's changed line and lists consumer impacts.
    """
    inline: list[dict] = []

    for change in field_changes:
        file_path = change.get("file_path", "").strip()
        line = change.get("line", 0)
        if not file_path or not line:
            continue

        sev = change.get("severity_hint", "MEDIUM")
        emoji = _SEVERITY_EMOJI.get(sev, "🟡")
        change_type = change.get("change_type", "SEMANTIC_CHANGE")

        # Header
        body_lines = [
            f"{emoji} **Ripple** · `{change_type}` ({sev})",
            "",
            f"**Before:** {change.get('old_description', '—')}",
            f"**After:** {change.get('new_description', '—')}",
        ]

        # Consumer impacts for this field — match by field_fqn if present
        field_fqn = change.get("field_fqn", "")
        field_impacts = [
            i for i in impacts
            if not field_fqn or i.get("field_fqn", field_fqn) == field_fqn
        ] if field_fqn else impacts

        breaking = [i for i in field_impacts if i.get("breaks")]
        non_breaking = [i for i in field_impacts if not i.get("breaks")]

        if breaking:
            body_lines.append("")
            body_lines.append("**Breaking consumers:**")
            for i in breaking:
                consumer = i.get("consumer_service", "?")
                fname = i.get("file_path", "").split("/")[-1]
                lineno = i.get("line", "?")
                explanation = i.get("explanation", "")[:120]
                body_lines.append(f"- 🔴 `{consumer}` → `{fname}:{lineno}` — {explanation}")
                if i.get("suggested_fix"):
                    body_lines.append(f"  > **Fix:** {i['suggested_fix'][:200]}")
        elif non_breaking:
            body_lines.append("")
            body_lines.append("**Non-breaking consumer impacts:**")
            for i in non_breaking[:3]:
                consumer = i.get("consumer_service", "?")
                explanation = i.get("explanation", "")[:120]
                body_lines.append(f"- 🟡 `{consumer}` — {explanation}")

        if not breaking and not non_breaking:
            body_lines.append("")
            body_lines.append("*No consumers of this field found in the knowledge graph.*")

        inline.append({
            "path": file_path,
            "line": line,
            "side": "RIGHT",
            "body": "\n".join(body_lines),
        })

    return inline


# ── Comment formatter ─────────────────────────────────────────────────────────


def _format_review_comment(
    producer_service: str,
    pr_number: int,
    field_changes: list[dict],
    impacts: list[dict],
    fix_results: list[dict] | None = None,
) -> str:
    """Formats the top-level PR review body (summary). Inline comments carry the per-field detail."""
    if not field_changes:
        return (
            "## Ripple Contract Analysis\n\n"
            "✅ No semantic contract changes detected in this PR. "
            "Safe to merge from a consumer-compatibility perspective.\n\n"
            "*[Ripple — semantic contract firewall]*"
        )

    breaking = [i for i in impacts if i.get("breaks")]
    non_breaking = [i for i in impacts if not i.get("breaks")]

    summary_emoji = "🔴" if breaking else ("🟡" if non_breaking else "✅")
    lines: list[str] = [
        "## Ripple Contract Analysis\n",
        f"{summary_emoji} **{len(field_changes)} field contract(s) changed** "
        f"in `{producer_service}` · "
        f"**{len(breaking)} breaking** / {len(non_breaking)} non-breaking consumer impacts\n",
        "> Inline annotations on the changed lines show per-field impact details.\n",
    ]

    # Changed fields summary table
    lines.append("| Field | Change | Severity |")
    lines.append("|-------|--------|----------|")
    for change in field_changes:
        sev = change.get("severity_hint", "MEDIUM")
        emoji = _SEVERITY_EMOJI.get(sev, "🟡")
        lines.append(
            f"| `{change['field_name']}` "
            f"| {change['change_type']} "
            f"| {emoji} {sev} |"
        )

    if breaking:
        lines.append("\n---\n### 🔴 Breaking Consumer Impacts\n")
        lines.append("| Consumer | File | Line | Issue |")
        lines.append("|----------|------|------|-------|")
        for impact in breaking:
            sev = impact.get("severity", "HIGH")
            fname = impact.get("file_path", "").split("/")[-1]
            line_no = impact.get("line", "?")
            explanation = impact.get("explanation", "")[:100]
            consumer = impact.get("consumer_service", "?")
            lines.append(f"| `{consumer}` | `{fname}` | {line_no} | {explanation} |")

        lines.append("")
        for impact in breaking:
            if impact.get("suggested_fix"):
                consumer = impact.get("consumer_service", "?")
                lines.append(f"**Fix for `{consumer}`:** {impact['suggested_fix']}")

    elif non_breaking:
        lines.append("\n---\n### 🟡 Non-Breaking Impacts\n")
        for impact in non_breaking:
            consumer = impact.get("consumer_service", "?")
            explanation = impact.get("explanation", "")
            lines.append(f"- `{consumer}`: {explanation}")

    # Auto-fix summary
    if fix_results:
        successful_fixes = [r for r in fix_results if r.get("pr_url")]
        failed_fixes = [r for r in fix_results if not r.get("pr_url")]
        if successful_fixes:
            lines.append("\n---\n### 🤖 Auto-Fix PRs Raised\n")
            for r in successful_fixes:
                consumer = r.get("consumer_service", "?")
                pr_url = r.get("pr_url", "")
                lines.append(f"- **`{consumer}`** → {pr_url}")
        if failed_fixes:
            lines.append("\n**Could not auto-fix (manual review needed):**")
            for r in failed_fixes:
                lines.append(f"- `{r.get('consumer_service', '?')}`: {r.get('error', 'unknown error')}")

    lines.append("\n---\n*[Ripple — semantic contract firewall](https://github.com/)*")

    return "\n".join(lines)
