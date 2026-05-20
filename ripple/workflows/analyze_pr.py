from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ripple.activities.git_activities import cleanup_workspace_activity, get_pr_diff_activity

IO_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))


@workflow.defn(name="AnalyzePRWorkflow")
class AnalyzePRWorkflow:
    def __init__(self) -> None:
        self._status: str = "pending"
        self._diff_path: str = ""
        self._lines_changed: int = 0

    @workflow.query
    def diff_info(self) -> dict:
        return {
            "status": self._status,
            "diff_path": self._diff_path,
            "lines_changed": self._lines_changed,
        }

    @workflow.run
    async def run(self, request: dict) -> dict:
        repo_url = request["repo_url"]
        branch = request["branch"]
        base_branch = request["base_branch"]
        pr_number = request["pr_number"]
        workflow_run_id = workflow.info().run_id

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
        self._status = "diff_ready"

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
        }
