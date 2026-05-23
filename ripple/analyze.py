from __future__ import annotations

from temporalio.common import WorkflowIDConflictPolicy

from ripple.temporal_client import get_temporal_client
from ripple.workflows.analyze_pr import AnalyzePRWorkflow
from ripple.rib.graph.schema import AnalyzePRRequest, AnalyzeWorkflowStatus


async def start_analyze_workflow(request: AnalyzePRRequest) -> AnalyzeWorkflowStatus:
    client = await get_temporal_client()
    workflow_id = f"analyze-pr-{request.repo.replace('/', '-')}-{request.prNumber}"

    payload = {
        "repo_url": f"https://github.com/{request.repo}.git",
        "branch": request.branch,
        "base_branch": request.baseBranch,
        "pr_number": request.prNumber,
        "head_commit": request.headCommit,
        "producer_service": request.producerService,
        "github_token": request.githubToken,
    }

    handle = await client.start_workflow(
        AnalyzePRWorkflow.run,
        payload,
        id=workflow_id,
        task_queue="rib",
        id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
    )

    return AnalyzeWorkflowStatus(
        workflow_id=handle.id,
        run_id=handle.first_execution_run_id,
        status="running",
    )
