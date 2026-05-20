from __future__ import annotations

import os
from typing import Optional

from fastapi import FastAPI, HTTPException

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
)

app = FastAPI(title="Ripple Intelligence Backend", version="0.2.0")


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


@app.post("/ingest", response_model=IngestWorkflowStatus)
async def ingest_ecosystem(request: IngestEcosystemRequest):
    return await start_ingest_workflow(request)


@app.post("/ingest/legacy", response_model=IngestWorkflowStatus)
async def ingest_legacy(request: IngestionRequest):
    ecosystem = ingestion_request_to_ecosystem(request)
    return await start_ingest_workflow(ecosystem)


@app.get("/ingest/{workflow_id}", response_model=IngestWorkflowStatus)
async def ingest_status(workflow_id: str):
    return await get_ingest_status(workflow_id)


@app.post("/api/analyze", response_model=AnalyzeWorkflowStatus)
async def analyze_pr(request: AnalyzePRRequest):
    return await start_analyze_workflow(request)
