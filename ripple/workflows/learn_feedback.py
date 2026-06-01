from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ripple.activities.review_activities import process_learn_command_activity
    from ripple.activities.git_activities import get_pr_diff_activity, cleanup_workspace_activity

IO_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
LLM_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=5))


@workflow.defn(name="LearnFromFeedbackWorkflow")
class LearnFromFeedbackWorkflow:

    @workflow.run
    async def run(self, request: dict) -> dict:
        """
        request keys:
          correction_text: str   — text after /learn
          repo_full: str         — "owner/repo"
          pr_number: int
          comment_id: str
          branch: str            — PR head branch (for cloning diff context)
          base_branch: str
          github_token: str
        """
        import os as _os
        correction_text: str = request["correction_text"]
        repo_full: str = request["repo_full"]
        pr_number: int = request["pr_number"]
        comment_id: str = request.get("comment_id", "")
        branch: str = request.get("branch", "")
        base_branch: str = request.get("base_branch", "main")
        github_token: str = request.get("github_token", "") or _os.environ.get("RIPPLE_GITHUB_TOKEN", "") or _os.environ.get("GITHUB_TOKEN", "")
        workflow_run_id = workflow.info().run_id

        repo_url = f"https://github.com/{repo_full}.git"

        # Fetch diff for context (best-effort — skip if branch unknown)
        diff_content = ""
        workspace = ""
        if branch:
            try:
                diff_result = await workflow.execute_activity(
                    get_pr_diff_activity,
                    args=[repo_url, branch, base_branch, pr_number, workflow_run_id],
                    task_queue="rib-io",
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=IO_RETRY,
                )
                diff_content = diff_result.get("diff_content", "")
                workspace = diff_result.get("workspace", "")
            except Exception:
                pass  # Proceed without diff context

        try:
            # Extract and store the architectural constraint
            result = await workflow.execute_activity(
                process_learn_command_activity,
                args=[{
                    "correction_text": correction_text,
                    "diff_content": diff_content,
                    "repo_full": repo_full,
                    "pr_number": pr_number,
                    "comment_id": comment_id,
                    "github_token": github_token,
                }],
                task_queue="rib-llm",
                start_to_close_timeout=timedelta(minutes=3),
                retry_policy=LLM_RETRY,
            )
        finally:
            if workspace:
                await workflow.execute_activity(
                    cleanup_workspace_activity,
                    args=[workspace],
                    task_queue="rib-io",
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=IO_RETRY,
                )

        return result
