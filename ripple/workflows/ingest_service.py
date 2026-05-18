from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ripple.activities.git_activities import cleanup_workspace_activity, clone_repo_activity
    from ripple.activities.index_activities import (
        ensure_scip_index_activity,
        index_consumer_activity,
        index_producer_activity,
    )
    from ripple.rib.graph.schema import ServiceRole, ServiceSpec

IO_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
LLM_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10))


@workflow.defn(name="IngestServiceWorkflow")
class IngestServiceWorkflow:
    @workflow.run
    async def run(self, service: dict, workflow_run_id: str) -> dict:
        spec = ServiceSpec.model_validate(service)
        service_name = spec.service_name or _name_from_url(spec.repo_url)
        roles = {role.value for role in spec.roles}

        clone_result = await workflow.execute_activity(
            clone_repo_activity,
            args=[spec.repo_url, workflow_run_id],
            task_queue="rib-io",
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=IO_RETRY,
        )
        workspace = clone_result["workspace"]
        counts: dict[str, int] = {}
        needs_scip = (
            ServiceRole.PRODUCER.value in roles or ServiceRole.CONSUMER.value in roles
        )

        try:
            if needs_scip:
                scip_result = await workflow.execute_activity(
                    ensure_scip_index_activity,
                    args=[workspace, service_name],
                    task_queue="rib-io",
                    start_to_close_timeout=timedelta(minutes=45),
                    retry_policy=IO_RETRY,
                )
                counts["scip_reused"] = int(bool(scip_result.get("reused_committed")))
                counts["scip_generated"] = int(bool(scip_result.get("generated")))

            if ServiceRole.PRODUCER.value in roles:
                producer_counts = await workflow.execute_activity(
                    index_producer_activity,
                    args=[workspace, service_name, spec.openapi_path],
                    task_queue="rib-llm",
                    start_to_close_timeout=timedelta(minutes=30),
                    retry_policy=LLM_RETRY,
                )
                counts.update(producer_counts)

            if ServiceRole.CONSUMER.value in roles:
                consumer_counts = await workflow.execute_activity(
                    index_consumer_activity,
                    args=[workspace, service_name],
                    task_queue="rib-cpu",
                    start_to_close_timeout=timedelta(minutes=30),
                    retry_policy=IO_RETRY,
                )
                for key, value in consumer_counts.items():
                    counts[key] = counts.get(key, 0) + value
        finally:
            await workflow.execute_activity(
                cleanup_workspace_activity,
                args=[workspace],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=IO_RETRY,
            )

        return {"service_name": service_name, "counts": counts}


def _name_from_url(repo_url: str) -> str:
    name = repo_url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name
