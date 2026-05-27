from __future__ import annotations

import logging
from datetime import datetime, timezone

from temporalio import activity

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

    # Write Disagreements
    for raw in graph.get("disagreements", []):
        try:
            disagreement = _parse_disagreement(raw, now)
            store.upsert_disagreement(disagreement)
            disagreements_written += 1
        except Exception as exc:
            msg = f"disagreement field={raw.get('field_fqn','?')} err={exc}"
            errors.append(msg)
            logger.warning("write_graph skip disagreement %s", msg)

    logger.info(
        "write_graph done fields=%d beliefs=%d disagreements=%d errors=%d",
        fields_written, beliefs_written, disagreements_written, len(errors),
    )
    return {
        "fields_written": fields_written,
        "beliefs_written": beliefs_written,
        "disagreements_written": disagreements_written,
        "errors": errors[:20],
    }


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
