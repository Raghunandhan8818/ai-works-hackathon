from __future__ import annotations

from ripple.rib.graph.schema import (
    IngestEcosystemRequest,
    IngestionRequest,
    IngestWorkflowStatus,
    ServiceRole,
    ServiceSpec,
)
from temporalio.common import WorkflowIDConflictPolicy

from ripple.temporal_client import get_temporal_client
from ripple.workflows.ingest_ecosystem import IngestEcosystemWorkflow


def ingestion_request_to_ecosystem(request: IngestionRequest) -> IngestEcosystemRequest:
    services: list[ServiceSpec] = [
        ServiceSpec(
            repo_url=request.producer_repo_url,
            roles=[ServiceRole.PRODUCER],
            openapi_path=request.openapi_path,
        )
    ]
    for consumer_url in request.consumer_repo_urls:
        services.append(
            ServiceSpec(repo_url=consumer_url, roles=[ServiceRole.CONSUMER])
        )
    return IngestEcosystemRequest(services=services)


async def start_ingest_workflow(
    request: IngestEcosystemRequest,
) -> IngestWorkflowStatus:
    client = await get_temporal_client()
    workflow_id = f"ingest-{request.tenant_id}-ecosystem"
    handle = await client.start_workflow(
        IngestEcosystemWorkflow.run,
        request.model_dump(mode="json"),
        id=workflow_id,
        task_queue="rib",
        id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
    )
    return IngestWorkflowStatus(
        workflow_id=handle.id,
        run_id=handle.first_execution_run_id,
        status="running",
    )


async def get_ingest_status(workflow_id: str) -> IngestWorkflowStatus:
    client = await get_temporal_client()
    handle = client.get_workflow_handle(workflow_id)
    description = await handle.describe()
    status = description.status.name.lower()

    progress: dict[str, str | int] = {}
    result = None
    try:
        progress = await handle.query(IngestEcosystemWorkflow.progress)
    except Exception:
        pass
    try:
        result = await handle.query(IngestEcosystemWorkflow.result)
    except Exception:
        pass

    if result is None and status in ("completed", "failed", "canceled", "terminated"):
        try:
            raw = await handle.result()
            from ripple.rib.graph.schema import IngestionResult

            result = IngestionResult.model_validate(raw)
        except Exception:
            pass

    return IngestWorkflowStatus(
        workflow_id=workflow_id,
        run_id=description.run_id,
        status=status,
        progress=progress,
        result=result,
    )
