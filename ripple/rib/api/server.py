from __future__ import annotations

import hashlib
import hmac
import logging
import os
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ripple.ingest import (
    get_ingest_status,
    ingestion_request_to_ecosystem,
    start_ingest_workflow,
)
from ripple.analyze import start_analyze_workflow
from ripple.rib.graph.factory import get_store
from ripple.rib.graph.schema import (
    AnalyzePRRequest,
    AnalyzeWorkflowStatus,
    IngestEcosystemRequest,
    IngestionRequest,
    IngestWorkflowStatus,
    ServiceRecord,
)
from ripple.temporal_client import get_temporal_client
from ripple.workflows.ecosystem_pipeline import EcosystemPipelineWorkflow
from temporalio.common import WorkflowIDConflictPolicy


class InterruptResolveRequest(BaseModel):
    field_fqn: str
    consumer_service: str
    option_id: str
    option_label: str
    option_description: str = ""

logger = logging.getLogger(__name__)

app = FastAPI(title="Ripple Intelligence Backend", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    try:
        get_store().ping()
        return {"status": "ok", "database": "postgres"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/fields")
def list_fields(service: Optional[str] = None):
    store = get_store()
    if service:
        return [f.model_dump() for f in store.get_fields_for_service(service)]
    return [f.model_dump() for f in store.get_all_fields()]


@app.get("/fields/{field_fqn:path}")
def get_field(field_fqn: str):
    store = get_store()
    field = store.get_field(field_fqn)
    if field is None:
        raise HTTPException(status_code=404, detail="Field not found")
    profile = store.get_semantic_profile(field_fqn)
    return {
        "field": field.model_dump(),
        "semantic_profile": profile.model_dump() if profile else None,
    }


@app.get("/blast-radius/{field_fqn:path}")
def blast_radius(field_fqn: str):
    store = get_store()
    try:
        radius = store.get_blast_radius(field_fqn)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return radius.model_dump()


@app.get("/disagreements")
def list_disagreements(field_fqn: Optional[str] = None):
    store = get_store()
    if field_fqn:
        items = store.get_disagreements_for_field(field_fqn)
        items = [d for d in items if d.resolved_at is None]
    else:
        items = store.get_active_disagreements()
    return [d.model_dump() for d in items]


@app.post("/api/interrupt/resolve")
async def resolve_interrupt(request: InterruptResolveRequest):
    """
    Resolve a human interrupt:
    - 'manual' or 'investigate' → just mark disagreement resolved
    - any other option_id → mark resolved + trigger AutoFixConsumerWorkflow with chosen strategy
    """
    store = get_store()

    # Find the disagreement to get field change context
    disagreements = store.get_disagreements_for_field(request.field_fqn)
    disagreement = next(
        (d for d in disagreements if d.consumer_service == request.consumer_service and d.resolved_at is None),
        None,
    )
    if not disagreement:
        raise HTTPException(status_code=404, detail="Active disagreement not found")

    # Mark as resolved
    store.resolve_disagreement(request.field_fqn, request.consumer_service)

    if request.option_id in ("manual", "investigate"):
        return {"status": "resolved", "workflow_id": None}

    # Trigger AutoFixConsumerWorkflow with the chosen strategy
    all_services = store.get_all_services()
    consumer_svc = next((s for s in all_services if s.name == request.consumer_service), None)
    consumer_repo_url = consumer_svc.repo_url if consumer_svc else ""

    if not consumer_repo_url:
        raise HTTPException(status_code=400, detail=f"No repo_url for consumer service {request.consumer_service}")

    producer_service = request.field_fqn.split(".")[0]
    github_token = os.environ.get("RIPPLE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")

    chosen_strategy = f"{request.option_label}: {request.option_description}".strip(": ")

    field_change = {
        "field_name": request.field_fqn.split(".")[-1],
        "field_fqn": request.field_fqn,
        "change_type": disagreement.kind.value,
        "old_description": disagreement.consumer_assumes,
        "new_description": disagreement.producer_says,
        "severity_hint": disagreement.severity.value,
    }
    breaking_impact = {
        "consumer_service": request.consumer_service,
        "consumer_repo_url": consumer_repo_url,
        "file_path": "",
        "line": 0,
        "breaks": True,
        "explanation": disagreement.explanation,
        "suggested_fix": chosen_strategy,
        "chosen_strategy": chosen_strategy,
        "evidence": disagreement.evidence,
    }

    from ripple.workflows.auto_fix_consumer import AutoFixConsumerWorkflow
    client = await get_temporal_client()
    workflow_id = f"manual-fix-{request.consumer_service[:20]}-{request.field_fqn[:20]}"

    handle = await client.start_workflow(
        AutoFixConsumerWorkflow.run,
        args=[{
            "consumer_service": request.consumer_service,
            "consumer_repo_url": consumer_repo_url,
            "producer_service": producer_service,
            "producer_pr_url": "",
            "field_changes": [field_change],
            "breaking_impacts": [breaking_impact],
            "github_token": github_token,
        }],
        id=workflow_id,
        task_queue="rib",
        id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
    )

    return {"status": "fix_triggered", "workflow_id": handle.id}


@app.post("/ingest", response_model=IngestWorkflowStatus)
async def ingest_ecosystem(request: IngestEcosystemRequest):
    return await start_ingest_workflow(request)


@app.post("/ingest-pipeline", response_model=IngestWorkflowStatus)
async def ingest_pipeline(request: IngestEcosystemRequest):
    """
    Cross-repo knowledge graph pipeline.
    Phase 1: clone all repos in parallel into shared workspace.
    Phase 2: build combined code index (codebase-memory-mcp or codegraph) on shared root.
    Phase 3: Claude Code headless with MCP tools extracts full knowledge graph.
    Phase 4: write FieldNodes + ConsumerBeliefs + Disagreements to Postgres.
    """
    client = await get_temporal_client()
    workflow_id = f"pipeline-{request.tenant_id}-ecosystem"
    handle = await client.start_workflow(
        EcosystemPipelineWorkflow.run,
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


@app.post("/ingest/legacy", response_model=IngestWorkflowStatus)
async def ingest_legacy(request: IngestionRequest):
    ecosystem = ingestion_request_to_ecosystem(request)
    return await start_ingest_workflow(ecosystem)


@app.get("/ingest/{workflow_id}", response_model=IngestWorkflowStatus)
async def ingest_status(workflow_id: str):
    return await get_ingest_status(workflow_id)


@app.get("/services", response_model=list[ServiceRecord])
def list_services():
    return get_store().get_all_services()


@app.post("/api/analyze", response_model=AnalyzeWorkflowStatus)
async def analyze_pr(request: AnalyzePRRequest):
    return await start_analyze_workflow(request)


# ── GitHub Webhooks ───────────────────────────────────────────────────────────

@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_github_event: Optional[str] = Header(None),
    x_hub_signature_256: Optional[str] = Header(None),
):
    """
    Receives GitHub webhook events.

    Handles two events:
    - pull_request (action=opened/synchronize) → trigger AnalyzePRWorkflow
    - push to default branch → re-index the affected service (partial re-ingest)

    Set GITHUB_WEBHOOK_SECRET env var to validate the signature.
    Set RIPPLE_GITHUB_TOKEN env var as the default token for posting reviews.
    """
    body = await request.body()

    webhook_secret = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
    if webhook_secret:
        if not _verify_github_signature(body, webhook_secret, x_hub_signature_256 or ""):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

    payload = await request.json()
    event = x_github_event or ""

    if event == "pull_request":
        action = payload.get("action", "")
        if action not in ("opened", "synchronize", "reopened"):
            return {"status": "ignored", "reason": f"action={action}"}

        pr = payload["pull_request"]
        repo = payload["repository"]
        repo_full_name = repo["full_name"]  # owner/repo

        # Look up producer_service by matching repo_url in our services table
        store = get_store()
        producer_service = _find_service_by_repo(store, repo["clone_url"]) or ""

        github_token = (
            os.environ.get("RIPPLE_GITHUB_TOKEN")
            or os.environ.get("GITHUB_TOKEN", "")
        )
        analyze_request = AnalyzePRRequest(
            repo=repo_full_name,
            prNumber=pr["number"],
            branch=pr["head"]["ref"],
            baseBranch=pr["base"]["ref"],
            headCommit=pr["head"]["sha"],
            producerService=producer_service,
            githubToken=github_token,
        )

        logger.info(
            "webhook github PR event repo=%s pr=%s service=%s",
            repo_full_name, pr["number"], producer_service,
        )
        status = await start_analyze_workflow(analyze_request)
        return {"status": "triggered", "workflow_id": status.workflow_id}

    elif event == "push":
        # Only re-index on pushes to the default branch (merges)
        default_branch = payload.get("repository", {}).get("default_branch", "main")
        pushed_ref = payload.get("ref", "")
        if pushed_ref != f"refs/heads/{default_branch}":
            return {"status": "ignored", "reason": "not default branch"}

        repo = payload["repository"]
        clone_url = repo["clone_url"]

        store = get_store()
        service_name = _find_service_by_repo(store, clone_url)
        if not service_name:
            logger.warning("webhook push: no service found for repo=%s", clone_url)
            return {"status": "ignored", "reason": "service not indexed"}

        all_services = store.get_all_services()
        service_record = next((s for s in all_services if s.name == service_name), None)
        if not service_record or not service_record.repo_url:
            return {"status": "ignored", "reason": "service has no repo_url"}

        # Trigger re-ingest of this service to update the knowledge graph
        from ripple.rib.graph.schema import IngestEcosystemRequest, ServiceRole, ServiceSpec
        reindex_request = IngestEcosystemRequest(
            services=[ServiceSpec(
                repo_url=service_record.repo_url,
                service_name=service_name,
                roles=[ServiceRole.PRODUCER],
                openapi_path="openapi.yaml",
            )],
        )

        logger.info("webhook push: re-indexing service=%s repo=%s", service_name, clone_url)
        status = await start_ingest_workflow(reindex_request)
        return {"status": "reindex_triggered", "workflow_id": status.workflow_id, "service": service_name}

    return {"status": "ignored", "reason": f"unhandled event={event}"}


def _verify_github_signature(body: bytes, secret: str, signature_header: str) -> bool:
    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"), body, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def _find_service_by_repo(store, repo_url: str) -> Optional[str]:
    """Match a GitHub clone URL to a known service by repo_url similarity."""
    # Normalise: strip .git, lowercase
    def _norm(url: str) -> str:
        return url.lower().rstrip("/").removesuffix(".git")

    target = _norm(repo_url)
    for svc in store.get_all_services():
        if svc.repo_url and _norm(svc.repo_url) == target:
            return svc.name
    return None
