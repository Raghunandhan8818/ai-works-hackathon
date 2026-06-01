from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from temporalio import activity

from ripple.rib.enricher.disagreement_detector import detect_disagreements
from ripple.rib.enricher.semantic_verifier import verify_semantic_disagreement
from ripple.rib.graph.factory import get_store
from ripple.rib.graph.schema import (
    ConsumerBelief,
    Disagreement,
    DisagreementKind,
    DisagreementSource,
    FieldNode,
    ServiceRecord,
    ServiceRole,
    Severity,
    TransportKind,
)

logger = logging.getLogger(__name__)

_SEVERITY_MAP = {
    "CRITICAL": Severity.CRITICAL,
    "HIGH": Severity.HIGH,
    "MEDIUM": Severity.MEDIUM,
    "LOW": Severity.LOW,
}

_KIND_MAP = {k.value: k for k in DisagreementKind}


@activity.defn(name="write_graph_to_store")
async def write_graph_to_store_activity(graph: dict, services: list[dict]) -> dict:
    """
    Write the knowledge graph produced by CrossRepoGraphBuilderActivity into Postgres.
    Validates each record before writing — bad records are skipped and logged.
    """
    store = get_store()
    now = datetime.now(timezone.utc)

    fields_written = 0
    beliefs_written = 0
    disagreements_written = 0
    errors: list[str] = []

    # Upsert service records
    for svc in services:
        name = svc.get("service_name", "")
        roles = svc.get("roles", [])
        if not name:
            continue
        role_str = "both" if len(roles) > 1 else (roles[0] if roles else "")
        try:
            store.upsert_service(ServiceRecord(
                name=name,
                repo_url=svc.get("repo_url", ""),
                role=role_str,
                last_indexed_at=now,
            ))
        except Exception as exc:
            logger.warning("write_graph service upsert failed name=%s err=%s", name, exc)

    # Write FieldNodes
    for raw in graph.get("fields", []):
        try:
            field = _parse_field(raw)
            store.upsert_field(field)
            fields_written += 1
        except Exception as exc:
            msg = f"field fqn={raw.get('fqn','?')} err={exc}"
            errors.append(msg)
            logger.warning("write_graph skip field %s", msg)

    # Write ConsumerBeliefs
    for raw in graph.get("consumer_beliefs", []):
        try:
            belief = _parse_belief(raw, now)
            store.upsert_consumer_belief(belief)
            beliefs_written += 1
        except Exception as exc:
            msg = f"belief consumer={raw.get('consumer_service','?')} field={raw.get('field_fqn','?')} err={exc}"
            errors.append(msg)
            logger.warning("write_graph skip belief %s", msg)

    # Write Disagreements from Claude's graph output
    for raw in graph.get("disagreements", []):
        try:
            disagreement = _parse_disagreement(raw, now)
            store.upsert_disagreement(disagreement)
            disagreements_written += 1
        except Exception as exc:
            msg = f"disagreement field={raw.get('field_fqn','?')} err={exc}"
            errors.append(msg)
            logger.warning("write_graph skip disagreement %s", msg)

    # Run drift detection against ALL stored beliefs in DB for complete coverage
    drift_count = await _run_drift_detection(store, now)
    disagreements_written += drift_count

    logger.info(
        "write_graph done fields=%d beliefs=%d disagreements=%d (drift=%d) errors=%d",
        fields_written, beliefs_written, disagreements_written, drift_count, len(errors),
    )
    return {
        "fields_written": fields_written,
        "beliefs_written": beliefs_written,
        "disagreements_written": disagreements_written,
        "errors": errors[:20],
    }


async def _run_drift_detection(store, now: datetime) -> int:
    """
    Load all stored fields + consumer beliefs from DB and run rule-based drift detection.
    Uses blast radius to get per-field beliefs for all consumers.
    Idempotent — safe to re-run on every pipeline ingestion.
    """
    written = 0
    semantic_pending: list[tuple[Disagreement, object]] = []

    all_fields = store.get_all_fields()
    logger.info("drift_detection scanning %d fields", len(all_fields))

    for field in all_fields:
        producer = field.fqn.split("::")[0] if "::" in field.fqn else ""
        profile = store.get_semantic_profile(field.fqn)

        try:
            blast = store.get_blast_radius(field.fqn)
        except Exception as exc:
            logger.warning("drift_detection blast_radius failed field=%s err=%s", field.fqn, exc)
            continue

        for entry in blast.consumers:
            if not entry.belief:
                continue
            consumer_service = entry.consumer_service
            if producer and consumer_service == producer:
                continue  # skip self-referential

            for d in detect_disagreements(field, profile, entry.belief):
                if d.kind.value == "SEMANTIC_INTENT_MISMATCH":
                    semantic_pending.append((d, verify_semantic_disagreement(
                        field_fqn=d.field_fqn,
                        producer_service=producer,
                        consumer_service=consumer_service,
                        producer_says=d.producer_says,
                        consumer_assumes=d.consumer_assumes,
                        evidence=d.evidence,
                    )))
                else:
                    try:
                        store.upsert_disagreement(d)
                        written += 1
                    except Exception as exc:
                        logger.warning("drift_detection upsert failed field=%s err=%s", field.fqn, exc)

    # Verify all semantic disagreements in parallel
    if semantic_pending:
        coros = [coro for _, coro in semantic_pending]
        results = await asyncio.gather(*coros, return_exceptions=True)
        for (d, _), result in zip(semantic_pending, results):
            if isinstance(result, Exception):
                logger.warning("semantic_verifier error field=%s: %s — keeping", d.field_fqn, result)
                verified, reason = True, f"Verification error — kept"
            else:
                verified, reason = result
            if verified:
                d.explanation = f"{d.explanation} [VERIFIED: {reason}]".strip()
                try:
                    store.upsert_disagreement(d)
                    written += 1
                except Exception as exc:
                    logger.warning("drift_detection semantic upsert failed field=%s err=%s", d.field_fqn, exc)
            else:
                logger.info("drift_detection suppressed semantic field=%s reason=%s", d.field_fqn, reason)

    logger.info("drift_detection disagreements_written=%d", written)
    return written


def _parse_field(raw: dict) -> FieldNode:
    transport_raw = raw.get("transport", "REST")
    try:
        transport = TransportKind(transport_raw)
    except ValueError:
        transport = TransportKind.REST

    constraints = [
        {**c, "source": c.get("source", "openapi")} if isinstance(c, dict) else c
        for c in raw.get("constraints", [])
    ]
    return FieldNode(
        fqn=raw["fqn"],
        name=raw["name"],
        producer_service=raw["producer_service"],
        transport=transport,
        endpoint_or_topic=raw.get("endpoint_or_topic", ""),
        field_path=raw.get("field_path", raw["name"]),
        declared_type=raw.get("declared_type", "string"),
        nullable=bool(raw.get("nullable", False)),
        deprecated=bool(raw.get("deprecated", False)),
        constraints=constraints,
    )


def _parse_belief(raw: dict, now: datetime) -> ConsumerBelief:
    return ConsumerBelief(
        consumer_service=raw["consumer_service"],
        field_fqn=raw["field_fqn"],
        assumed_type=raw.get("assumed_type"),
        assumed_nullable=raw.get("assumed_nullable"),
        assumed_unit=raw.get("assumed_unit"),
        assumed_format=raw.get("assumed_format"),
        inferred_constraints=raw.get("inferred_constraints", []),
        usage_expressions=raw.get("usage_expressions", []),
        confidence=float(raw.get("confidence", 0.5)),
        extracted_at=now,
    )


def _parse_disagreement(raw: dict, now: datetime) -> Disagreement:
    kind_str = raw.get("kind", "BEHAVIORAL_CHANGE")
    kind = _KIND_MAP.get(kind_str, DisagreementKind.BEHAVIORAL_CHANGE)

    severity_str = raw.get("severity", "MEDIUM")
    severity = _SEVERITY_MAP.get(severity_str, Severity.MEDIUM)

    return Disagreement(
        field_fqn=raw["field_fqn"],
        consumer_service=raw["consumer_service"],
        kind=kind,
        producer_says=raw.get("producer_says", ""),
        consumer_assumes=raw.get("consumer_assumes", ""),
        severity=severity,
        explanation=raw.get("explanation", ""),
        detected_at=now,
        source=DisagreementSource.LLM,
    )
