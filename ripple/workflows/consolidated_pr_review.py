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
        upsert_pr_disagreements_activity,
    )
    from ripple.activities.review_activities import (
        post_consolidated_review_activity,
        read_arch_md_activity,
        run_architectural_review_activity,
    )
    from ripple.workflows.auto_fix_consumer import AutoFixConsumerWorkflow

IO_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
LLM_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=5))

_NEEDS_HUMAN_TYPES = {"BEHAVIORAL_CHANGE", "SEMANTIC_CHANGE", "UNIT_CHANGE"}
_URGENT_SEVERITIES = {"CRITICAL", "HIGH"}


@workflow.defn(name="ConsolidatedPRReviewWorkflow")
class ConsolidatedPRReviewWorkflow:
    def __init__(self) -> None:
        self._status: str = "pending"

    @workflow.query
    def status(self) -> str:
        return self._status

    @workflow.run
    async def run(self, request: dict) -> dict:
        import os as _os
        repo_url: str = request["repo_url"]
        branch: str = request["branch"]
        base_branch: str = request["base_branch"]
        pr_number: int = request["pr_number"]
        head_commit: str = request.get("head_commit", "")
        producer_service: str = request.get("producer_service", "")
        github_token: str = request.get("github_token", "") or _os.environ.get("RIPPLE_GITHUB_TOKEN", "") or _os.environ.get("GITHUB_TOKEN", "")
        workflow_run_id = workflow.info().run_id

        # Extract repo_full ("owner/repo") for architectural intent lookup
        m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", repo_url)
        repo_full = m.group(1) if m else ""

        # ── Step 1: Clone + compute diff ─────────────────────────────────────
        self._status = "cloning"
        diff_result = await workflow.execute_activity(
            get_pr_diff_activity,
            args=[repo_url, branch, base_branch, pr_number, workflow_run_id],
            task_queue="rib-io",
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=IO_RETRY,
        )
        workspace: str = diff_result["workspace"]
        diff_content: str = diff_result.get("diff_content", "")

        # ── Step 1.5: Read ARCHITECTURE.md on rib-io (co-located with workspace) ─
        arch_md_content: str = await workflow.execute_activity(
            read_arch_md_activity,
            args=[workspace],
            task_queue="rib-io",
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=IO_RETRY,
        )

        try:
            # ── Step 2: Run contract analysis + architectural review in parallel ─
            self._status = "reviewing"

            # Contract analysis (same activities as AnalyzePRWorkflow steps 2-3)
            async def _run_contract_analysis() -> dict:
                if not diff_content.strip():
                    return {"field_changes": [], "impacts": []}

                field_changes = await workflow.execute_activity(
                    parse_pr_diff_activity,
                    args=[{"diff": diff_content, "producer_service": producer_service}],
                    task_queue="rib-llm",
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=LLM_RETRY,
                )

                all_impacts: list[dict] = []
                if field_changes:
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

                    # Synthesize knowledge-gap interrupts (same logic as AnalyzePRWorkflow)
                    for i, fc in enumerate(field_changes):
                        if fc.get("change_type") not in _NEEDS_HUMAN_TYPES:
                            continue
                        if fc.get("severity_hint") not in _URGENT_SEVERITIES:
                            continue
                        field_impacts = impact_results[i]
                        if any(imp.get("breaks") and imp.get("requires_human_decision") for imp in field_impacts):
                            continue
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
                            "explanation": fc.get("semantic_intent", "") or (fc.get("old_description", "") + " → " + fc.get("new_description", "")),
                            "human_decision_reason": f"'{fc['field_name']}' has a behavioral change requiring human confirmation.",
                            "mitigation_options": [],
                            "suggested_fix": "",
                            "evidence": [f"Before: {fc.get('old_description', '')}", f"After: {fc.get('new_description', '')}"],
                        })

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

                return {"field_changes": field_changes, "impacts": all_impacts}

            # Run contract analysis and architectural review concurrently
            gather_results = await asyncio.gather(
                _run_contract_analysis(),
                workflow.execute_activity(
                    run_architectural_review_activity,
                    args=[{
                        "arch_md_content": arch_md_content,
                        "diff_content": diff_content,
                        "repo_full": repo_full,
                    }],
                    task_queue="rib-llm",
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=LLM_RETRY,
                ),
                return_exceptions=True,
            )
            contract_result = gather_results[0] if isinstance(gather_results[0], dict) else {"field_changes": [], "impacts": []}
            arch_findings = gather_results[1] if isinstance(gather_results[1], dict) else {"architectural_violations": [], "security_concerns": [], "performance_suggestions": [], "best_practices": []}

            field_changes = contract_result["field_changes"]
            all_impacts = contract_result["impacts"]

            # ── Step 3: Auto-fix breaking consumer impacts ────────────────────────
            fix_results: list[dict] = []
            auto_fix_impacts = [i for i in all_impacts if i.get("breaks") and not i.get("requires_human_decision", False)]
            if auto_fix_impacts and github_token:
                self._status = "auto_fixing"
                producer_pr_url = f"https://github.com/{repo_full}/pull/{pr_number}" if repo_full else ""

                consumers_to_fix: dict[str, list[dict]] = {}
                for impact in auto_fix_impacts:
                    consumers_to_fix.setdefault(impact["consumer_service"], []).append(impact)

                fix_futures = []
                for consumer_service_name, impacts in consumers_to_fix.items():
                    consumer_repo_url = impacts[0].get("consumer_repo_url", "")
                    if not consumer_repo_url:
                        fix_results.append({"consumer_service": consumer_service_name, "pr_url": "", "success": False, "error": "no repo_url"})
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
                        fix_results.append(r if isinstance(r, dict) else {"consumer_service": "?", "pr_url": "", "success": False, "error": str(r)})

            # ── Step 4: Post single consolidated GitHub review ────────────────────
            self._status = "posting_review"
            post_result = await workflow.execute_activity(
                post_consolidated_review_activity,
                args=[{
                    "repo_url": repo_url,
                    "pr_number": pr_number,
                    "head_sha": head_commit,
                    "github_token": github_token,
                    "producer_service": producer_service,
                    "contract_findings": {
                        "field_changes": field_changes,
                        "impacts": all_impacts,
                        "fix_results": fix_results,
                    },
                    "arch_findings": arch_findings,
                }],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=IO_RETRY,
            )

            # ── Step 4.5: Post fix PR links on producer PR ─────────────────────────
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

        finally:
            # ── Step 5: Cleanup ───────────────────────────────────────────────────
            await workflow.execute_activity(
                cleanup_workspace_activity,
                args=[workspace],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=IO_RETRY,
            )

        self._status = "completed"
        return {
            "field_changes": field_changes,
            "impacts": all_impacts,
            "fix_results": fix_results,
            "arch_findings": arch_findings,
            "review_url": post_result.get("url", ""),
            "review_posted": post_result.get("success", False),
        }
