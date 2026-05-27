"""
PostMergeWorkflow

Triggered when a producer PR merges to main. Two steps:
  1. Re-index the producer service against the new main branch
  2. Mark all active disagreements for that producer as producer_merged

No auto-fixes are re-triggered — the merge is a developer decision.
Consumer fix PRs that are already open continue independently.
"""
from __future__ import annotations

import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ripple.activities.post_merge_activities import mark_producer_merged_activity
    from ripple.workflows.ingest_service import IngestServiceWorkflow

IO_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))

@workflow.defn(name="PostMergeWorkflow")
class PostMergeWorkflow:
    @workflow.run
    async def run(self, request: dict) -> dict:
        producer_service: str = request["producer_service"]
        repo_url: str = request["repo_url"]
        github_token: str = request.get("github_token", "")

        # Step 1: Re-index the producer against new main
        service_payload = {
            "repo_url": repo_url,
            "service_name": producer_service,
            "roles": ["producer"],
            "openapi_path": "openapi.yaml",
        }
        await workflow.execute_child_workflow(
            IngestServiceWorkflow.run,
            args=[service_payload, workflow.info().run_id],
            id=f"post-merge-reindex-{producer_service}-{workflow.info().run_id[:8]}",
            task_queue="rib",
            execution_timeout=timedelta(minutes=30),
        )

        # Step 2: Mark all active disagreements for this producer as producer_merged
        count = await workflow.execute_activity(
            mark_producer_merged_activity,
            args=[producer_service],
            task_queue="rib-io",
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=IO_RETRY,
        )

        return {
            "producer_service": producer_service,
            "disagreements_marked": count,
            "status": "completed",
        }
