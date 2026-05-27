"""
AutoFixConsumerWorkflow

Spawned as a child workflow by AnalyzePRWorkflow when breaking consumer impacts
are detected. Fully autonomous: clones the consumer repo, runs Claude Code in
headless mode to apply the fix, pushes the branch, and opens a GitHub PR.

Steps:
  1. clone_and_branch_activity   (rib-io)  — clone + checkout ripple/fix-* branch
  2. run_claude_code_fix_activity (rib-cpu) — headless `claude -p <prompt>`
  3. commit_push_fix_activity    (rib-io)  — git add/commit/push
  4. create_fix_pr_activity      (rib-io)  — GitHub API: open PR
  5. cleanup_workspace_activity  (rib-io)  — rm workspace
"""
from __future__ import annotations

import re
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ripple.activities.fix_activities import (
        clone_and_branch_activity,
        commit_push_fix_activity,
        create_fix_pr_activity,
        run_claude_code_fix_activity,
    )
    from ripple.activities.git_activities import cleanup_workspace_activity
    from ripple.activities.pr_activities import record_fix_pr_activity

IO_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
NO_RETRY = RetryPolicy(maximum_attempts=1)


@workflow.defn(name="AutoFixConsumerWorkflow")
class AutoFixConsumerWorkflow:
    @workflow.run
    async def run(self, request: dict) -> dict:
        consumer_service: str = request["consumer_service"]
        consumer_repo_url: str = request["consumer_repo_url"]
        producer_service: str = request["producer_service"]
        producer_pr_url: str = request.get("producer_pr_url", "")
        field_changes: list[dict] = request["field_changes"]
        breaking_impacts: list[dict] = request["breaking_impacts"]
        github_token: str = request.get("github_token", "")
        run_id = workflow.info().run_id

        field_name = field_changes[0]["field_name"] if field_changes else "contract"
        branch_name = _make_branch_name(producer_service, field_name, run_id)

        workspace = ""
        try:
            # ── Step 1: Clone + branch ─────────────────────────────────────────
            clone_result = await workflow.execute_activity(
                clone_and_branch_activity,
                args=[{
                    "consumer_repo_url": consumer_repo_url,
                    "branch_name": branch_name,
                    "github_token": github_token,
                    "workflow_run_id": run_id,
                }],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=IO_RETRY,
            )
            workspace = clone_result["workspace"]

            # ── Step 2: Apply fix with Claude Code ────────────────────────────
            fix_result = await workflow.execute_activity(
                run_claude_code_fix_activity,
                args=[{
                    "workspace": workspace,
                    "producer_service": producer_service,
                    "field_changes": field_changes,
                    "breaking_impacts": breaking_impacts,
                }],
                task_queue="rib-cpu",
                start_to_close_timeout=timedelta(minutes=20),
                retry_policy=NO_RETRY,
            )

            if not fix_result["success"]:
                return {
                    "consumer_service": consumer_service,
                    "pr_url": "",
                    "success": False,
                    "error": f"Claude Code fix failed: {fix_result['output'][:200]}",
                }

            # ── Step 3: Commit + push ─────────────────────────────────────────
            push_result = await workflow.execute_activity(
                commit_push_fix_activity,
                args=[{
                    "workspace": workspace,
                    "branch_name": branch_name,
                    "producer_service": producer_service,
                    "field_name": field_name,
                    "github_token": github_token,
                    "consumer_repo_url": consumer_repo_url,
                }],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=IO_RETRY,
            )

            if not push_result.get("pushed"):
                reason = push_result.get("reason", "unknown")
                return {
                    "consumer_service": consumer_service,
                    "pr_url": "",
                    "success": False,
                    "error": f"Nothing to push ({reason}) — Claude Code may not have changed any files",
                }

            # ── Step 4: Open PR ───────────────────────────────────────────────
            pr_result = await workflow.execute_activity(
                create_fix_pr_activity,
                args=[{
                    "consumer_repo_url": consumer_repo_url,
                    "branch_name": branch_name,
                    "producer_service": producer_service,
                    "producer_pr_url": producer_pr_url,
                    "field_changes": field_changes,
                    "breaking_impacts": breaking_impacts,
                    "github_token": github_token,
                }],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=IO_RETRY,
            )

            pr_url = pr_result.get("pr_url", "")
            if pr_url:
                field_fqns = list({
                    impact.get("field_fqn", "")
                    for impact in breaking_impacts
                    if impact.get("field_fqn")
                })
                if field_fqns:
                    await workflow.execute_activity(
                        record_fix_pr_activity,
                        args=[{
                            "pr_url": pr_url,
                            "consumer_service": consumer_service,
                            "field_fqns": field_fqns,
                        }],
                        task_queue="rib-io",
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=IO_RETRY,
                    )

            return {
                "consumer_service": consumer_service,
                "pr_url": pr_url,
                "success": pr_result.get("success", False),
                "error": pr_result.get("error", ""),
            }

        finally:
            if workspace:
                await workflow.execute_activity(
                    cleanup_workspace_activity,
                    args=[workspace],
                    task_queue="rib-io",
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=IO_RETRY,
                )


def _make_branch_name(producer_service: str, field_name: str, run_id: str) -> str:
    raw = f"ripple/fix-{producer_service}-{field_name}-{run_id[:8]}"
    # Lowercase, replace anything that isn't alphanumeric, /, or - with -
    sanitized = re.sub(r"[^a-z0-9/\-]", "-", raw.lower())
    return sanitized[:80]
