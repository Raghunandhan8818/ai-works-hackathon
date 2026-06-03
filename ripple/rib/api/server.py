from __future__ import annotations

import hashlib
import hmac
import httpx
import logging
import os
import re
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
from ripple.workflows.consolidated_pr_review import ConsolidatedPRReviewWorkflow
from ripple.workflows.ecosystem_pipeline import EcosystemPipelineWorkflow
from ripple.workflows.learn_feedback import LearnFromFeedbackWorkflow
from temporalio.common import WorkflowIDConflictPolicy


class InterruptResolveRequest(BaseModel):
    field_fqn: str
    consumer_service: str
    option_id: str
    option_label: str
    option_description: str = ""


class ServiceReviewSettingRequest(BaseModel):
    enabled: bool

logger = logging.getLogger(__name__)


def _deduplicate_disagreements(items):
    """
    Collapse endpoint-level duplicates into one logical interrupt per
    (producer_service, canonical_field_name, consumer_service, kind).

    Also removes self-referential disagreements (consumer == the service
    that owns the field — e.g. recommendation-service flagging its own fields).
    """
    from collections import defaultdict
    from ripple.rib.graph.schema import Severity

    _SEV = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}

    def _producer(fqn: str) -> str:
        return fqn.split("::")[0] if "::" in fqn else ""

    def _base_field(fqn: str) -> str:
        parts = fqn.split("::")
        raw = parts[-1] if parts else fqn
        for prefix in ("response.200.", "response.201.", "response.400.",
                        "response.201.", "request."):
            if raw.startswith(prefix):
                return raw[len(prefix):]
        return raw

    best: dict = {}
    for d in items:
        producer = _producer(d.field_fqn)
        # Drop self-referential: consumer flagging its own produced fields
        if producer and d.consumer_service == producer:
            continue
        # Drop non-standard FQNs that don't have a service prefix (cross-repo artefacts)
        if not producer:
            continue
        base = _base_field(d.field_fqn)
        key = (producer, base, d.consumer_service, d.kind.value)
        if key not in best or _SEV.get(d.severity.value, 0) > _SEV.get(best[key].severity.value, 0):
            best[key] = d

    # Sort: CRITICAL first, then HIGH, then by field name
    return sorted(
        best.values(),
        key=lambda d: (-_SEV.get(d.severity.value, 0), d.field_fqn),
    )

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


@app.get("/disagreements/all")
def list_all_disagreements():
    store = get_store()
    items = store.get_all_disagreements()
    return [d.model_dump() for d in _deduplicate_disagreements(items)]


@app.get("/disagreements")
def list_disagreements(field_fqn: Optional[str] = None):
    store = get_store()
    if field_fqn:
        items = store.get_disagreements_for_field(field_fqn)
        items = [d for d in items if d.resolved_at is None]
        return [d.model_dump() for d in items]
    else:
        items = store.get_active_disagreements()
        return [d.model_dump() for d in _deduplicate_disagreements(items)]


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

    if request.option_id in ("manual", "investigate", "producer_compat"):
        return {"status": "resolved", "workflow_id": None}

    all_services = store.get_all_services()
    producer_service = request.field_fqn.split("::")[0]

    # Knowledge-gap interrupt: consumer_service was set to producer_service because no
    # consumers were found during impact assessment. Fan out to all indexed consumers instead.
    is_knowledge_gap = request.consumer_service == producer_service
    if is_knowledge_gap:
        actual_consumers = [s for s in all_services if s.name != producer_service and s.repo_url]
        if not actual_consumers:
            return {"status": "resolved", "workflow_id": None}
        # Pick the first known consumer for the single-workflow response;
        # a future improvement can fan out to all.
        consumer_svc = actual_consumers[0]
    else:
        consumer_svc = next((s for s in all_services if s.name == request.consumer_service), None)

    consumer_repo_url = consumer_svc.repo_url if consumer_svc else ""

    if not consumer_repo_url:
        raise HTTPException(status_code=400, detail=f"No repo_url for consumer service {request.consumer_service}")

    github_token = os.environ.get("RIPPLE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")

    chosen_strategy = f"{request.option_label}: {request.option_description}".strip(": ")

    # Extract meaningful field name and endpoint from the FQN.
    # FQN format: "producer::transport::ENDPOINT::field.path"
    # e.g. "spring-backend::REST::GET /hobbies/homepage::response.200"
    fqn_parts = request.field_fqn.split("::")
    raw_field = request.field_fqn.split(".")[-1]
    # If the last segment is just a status code, use the field path level above it
    is_status_code = re.match(r"^\d{3}$", raw_field)
    if is_status_code:
        # Use the endpoint path as field identifier
        endpoint_raw = fqn_parts[2] if len(fqn_parts) > 2 else raw_field
        raw_field = re.sub(r"^(GET|POST|PUT|DELETE|PATCH)\s+\/?", "", endpoint_raw).strip()

    # Extract the endpoint path for use as a search term (e.g. "hobbies/homepage")
    endpoint_segment = fqn_parts[2] if len(fqn_parts) > 2 else ""
    ep_match = re.match(r"(?:GET|POST|PUT|DELETE|PATCH)\s+(.+?)(?:\s|$)", endpoint_segment)
    endpoint_path = ep_match.group(1).strip("/ ") if ep_match else ""

    field_change = {
        "field_name": raw_field,
        "old_field_name": raw_field,
        "field_fqn": request.field_fqn,
        "endpoint_path": endpoint_path,
        "change_type": disagreement.kind.value,
        "old_description": disagreement.consumer_assumes,
        "new_description": disagreement.producer_says,
        "semantic_intent": f"{disagreement.consumer_assumes} → {disagreement.producer_says}",
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

    resolved_consumer_service = consumer_svc.name if consumer_svc else request.consumer_service

    from ripple.workflows.auto_fix_consumer import AutoFixConsumerWorkflow
    client = await get_temporal_client()
    field_slug = request.field_fqn.split("::")[-1][:30].replace("/", "-")
    workflow_id = f"manual-fix-{resolved_consumer_service[:20]}-{field_slug}"

    handle = await client.start_workflow(
        AutoFixConsumerWorkflow.run,
        args=[{
            "consumer_service": resolved_consumer_service,
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


@app.get("/api/settings/review-enabled")
async def get_review_enabled_global():
    store = get_store()
    enabled = store.get_architectural_review_globally_enabled()
    return {"architectural_review_enabled": enabled}


@app.post("/api/settings/review-enabled")
async def set_review_enabled_global(body: ServiceReviewSettingRequest):
    store = get_store()
    store.set_architectural_review_globally_enabled(body.enabled)
    return {"architectural_review_enabled": body.enabled}


# Keep per-service endpoints for backward compat
@app.get("/api/services/{service_name}/review-enabled")
async def get_review_enabled(service_name: str):
    store = get_store()
    enabled = store.get_architectural_review_globally_enabled()
    return {"service": service_name, "architectural_review_enabled": enabled}


@app.post("/api/services/{service_name}/review-enabled")
async def set_review_enabled(service_name: str, body: ServiceReviewSettingRequest):
    store = get_store()
    store.set_architectural_review_globally_enabled(body.enabled)
    return {"service": service_name, "architectural_review_enabled": body.enabled}


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


class PostMergeRequest(BaseModel):
    repo_url: str
    producer_service: str
    pr_number: int = 0
    github_token: str = ""


class PostMergeStatus(BaseModel):
    workflow_id: str
    run_id: str
    status: str


@app.post("/api/flush")
def flush_db():
    """
    Truncate all Ripple tables — wipes fields, beliefs, disagreements (interrupts),
    usages, services, profiles, drift events, and all indexed metadata.
    """
    import psycopg2
    db_url = os.environ.get("RIB_DATABASE_URL", "")
    if not db_url:
        raise HTTPException(status_code=500, detail="RIB_DATABASE_URL not set")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""
        TRUNCATE TABLE
            disagreements,
            consumer_beliefs,
            semantic_profiles,
            history_signals,
            field_usages,
            symbols,
            fields,
            indexed_files,
            services,
            business_contexts,
            code_classes,
            code_methods,
            drift_events,
            test_evidences
        RESTART IDENTITY CASCADE
    """)
    cur.close()
    conn.close()
    logger.info("api/flush: all tables truncated")
    return {"status": "flushed", "message": "All Ripple data cleared — ready for re-ingest"}


@app.post("/api/post-merge", response_model=PostMergeStatus)
async def post_merge(request: PostMergeRequest):
    """
    Trigger post-merge processing for a producer PR:
    1. Re-index producer against new main
    2. Mark all active disagreements as producer_merged
    """
    from ripple.workflows.post_merge import PostMergeWorkflow

    github_token = request.github_token or os.environ.get("RIPPLE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")

    client = await get_temporal_client()
    workflow_id = f"post-merge-{request.producer_service}-{request.pr_number}"

    handle = await client.start_workflow(
        PostMergeWorkflow.run,
        args=[{
            "producer_service": request.producer_service,
            "repo_url": request.repo_url,
            "github_token": github_token,
        }],
        id=workflow_id,
        task_queue="rib",
        id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
    )

    return PostMergeStatus(
        workflow_id=handle.id,
        run_id=handle.result_run_id or "",
        status="running",
    )


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
        pr_data = payload.get("pull_request", {})
        pr_number = pr_data.get("number", 0)

        if action == "closed" and pr_data.get("merged"):
            repo_full = payload.get("repository", {}).get("full_name", "")
            repo_url = f"https://github.com/{repo_full}"
            producer_service = _find_service_by_repo(get_store(), payload.get("repository", {}).get("clone_url", "")) or repo_full.split("/")[-1]

            github_token = (
                os.environ.get("RIPPLE_GITHUB_TOKEN")
                or os.environ.get("GITHUB_TOKEN", "")
            )

            from ripple.workflows.post_merge import PostMergeWorkflow
            client = await get_temporal_client()
            logger.info(
                "webhook github PR merged repo=%s pr=%s service=%s — triggering PostMergeWorkflow",
                repo_full, pr_number, producer_service,
            )
            await client.start_workflow(
                PostMergeWorkflow.run,
                args=[{
                    "producer_service": producer_service,
                    "repo_url": repo_url,
                    "github_token": github_token,
                }],
                id=f"post-merge-{producer_service}-{pr_number}",
                task_queue="rib",
                id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
            )
            return {"status": "post_merge_triggered", "producer_service": producer_service}

        if action not in ("opened", "synchronize", "reopened"):
            return {"status": "ignored", "reason": f"action={action}"}

        pr = pr_data
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

        # Global toggle — applies to all ingested repos
        arch_review_enabled = False
        try:
            arch_review_enabled = store.get_architectural_review_globally_enabled()
        except Exception:
            pass

        if arch_review_enabled:
            client = await get_temporal_client()
            consolidated_request = {
                "repo_url": f"https://github.com/{repo_full_name}",
                "branch": pr["head"]["ref"],
                "base_branch": pr["base"]["ref"],
                "pr_number": pr["number"],
                "head_commit": pr["head"]["sha"],
                "producer_service": producer_service,
                "github_token": github_token,
            }
            wf = await client.start_workflow(
                ConsolidatedPRReviewWorkflow.run,
                args=[consolidated_request],
                id=f"consolidated-review-{repo_full_name.replace('/', '-')}-{pr['number']}",
                task_queue="rib",
                id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
            )
            return {"status": "consolidated_review_triggered", "workflow_id": wf.id}
        else:
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

    elif event == "issue_comment":
        action = payload.get("action", "")
        if action != "created":
            return {"status": "ignored", "reason": "not a new comment"}

        comment_body: str = payload.get("comment", {}).get("body", "").strip()
        if not comment_body.lower().startswith("/learn"):
            return {"status": "ignored", "reason": "not a /learn command"}

        # Only process on PRs (issue_comment fires on both issues and PRs)
        issue = payload.get("issue", {})
        if "pull_request" not in issue:
            return {"status": "ignored", "reason": "not on a PR"}

        correction_text = comment_body[len("/learn"):].strip()
        repo = payload["repository"]
        repo_full_name = repo["full_name"]
        pr_number = issue["number"]
        comment_id = str(payload.get("comment", {}).get("id", ""))

        github_token = os.environ.get("RIPPLE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        branch = ""
        base_branch = "main"
        if github_token:
            try:
                async with httpx.AsyncClient(timeout=10) as gh_client:
                    resp = await gh_client.get(
                        f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}",
                        headers={"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"},
                    )
                    if resp.status_code == 200:
                        pr_data = resp.json()
                        branch = pr_data.get("head", {}).get("ref", "")
                        base_branch = pr_data.get("base", {}).get("ref", "main")
            except Exception:
                pass

        learn_request = {
            "correction_text": correction_text,
            "repo_full": repo_full_name,
            "pr_number": pr_number,
            "comment_id": comment_id,
            "branch": branch,
            "base_branch": base_branch,
            "github_token": github_token,
        }

        temporal_client = await get_temporal_client()
        wf = await temporal_client.start_workflow(
            LearnFromFeedbackWorkflow.run,
            args=[learn_request],
            id=f"learn-{repo_full_name.replace('/', '-')}-{pr_number}-{comment_id}",
            task_queue="rib",
            id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
        )
        logger.info("LearnFromFeedbackWorkflow triggered repo=%s pr=%s", repo_full_name, pr_number)
        return {"status": "learn_triggered", "workflow_id": wf.id}

    elif event == "pull_request_review_comment":
        action = payload.get("action", "")
        if action != "created":
            return {"status": "ignored", "reason": "not a new comment"}

        comment_body: str = payload.get("comment", {}).get("body", "").strip()
        if not comment_body.lower().startswith("/learn"):
            return {"status": "ignored", "reason": "not a /learn command"}

        correction_text = comment_body[len("/learn"):].strip()
        repo = payload["repository"]
        repo_full_name = repo["full_name"]
        pr_data = payload.get("pull_request", {})
        pr_number = pr_data.get("number", 0)
        comment_id = str(payload.get("comment", {}).get("id", ""))
        branch = pr_data.get("head", {}).get("ref", "")
        base_branch = pr_data.get("base", {}).get("ref", "main")

        github_token = os.environ.get("RIPPLE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")

        learn_request = {
            "correction_text": correction_text,
            "repo_full": repo_full_name,
            "pr_number": pr_number,
            "comment_id": comment_id,
            "branch": branch,
            "base_branch": base_branch,
            "github_token": github_token,
        }

        temporal_client = await get_temporal_client()
        wf = await temporal_client.start_workflow(
            LearnFromFeedbackWorkflow.run,
            args=[learn_request],
            id=f"learn-{repo_full_name.replace('/', '-')}-{pr_number}-{comment_id}",
            task_queue="rib",
            id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
        )
        logger.info(
            "LearnFromFeedbackWorkflow triggered (review comment) repo=%s pr=%s comment=%s",
            repo_full_name, pr_number, comment_id,
        )
        return {"status": "learn_triggered", "workflow_id": wf.id}

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
