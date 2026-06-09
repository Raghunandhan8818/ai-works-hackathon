from __future__ import annotations

from datetime import datetime

from ripple.rib.enricher.disagreement_detector import detect_disagreements
from ripple.rib.graph.schema import (
    ConsumerBelief,
    Constraint,
    DisagreementKind,
    FieldNode,
    SemanticProfile,
    TransportKind,
)


def _make_field(
    name: str = "amount",
    declared_type: str = "integer",
    nullable: bool = False,
    constraints: list[Constraint] | None = None,
) -> FieldNode:
    return FieldNode(
        fqn=f"order-service::REST::GET /orders::{name}",
        name=name,
        producer_service="order-service",
        transport=TransportKind.REST,
        endpoint_or_topic="GET /orders",
        field_path=name,
        declared_type=declared_type,
        nullable=nullable,
        constraints=constraints or [],
    )


def _make_belief(
    consumer: str = "quickbite",
    field_fqn: str = "order-service::REST::GET /orders::amount",
    assumed_type: str | None = None,
    assumed_nullable: bool | None = None,
    assumed_unit: str | None = None,
    assumed_format: str | None = None,
    inferred_constraints: list[str] | None = None,
) -> ConsumerBelief:
    return ConsumerBelief(
        consumer_service=consumer,
        field_fqn=field_fqn,
        assumed_type=assumed_type,
        assumed_nullable=assumed_nullable,
        assumed_unit=assumed_unit,
        assumed_format=assumed_format,
        inferred_constraints=inferred_constraints or [],
        usage_expressions=[],
        confidence=0.8,
        extracted_at=datetime.utcnow(),
    )


# ── CONSTRAINT_UNKNOWN_TO_CONSUMER ────────────────────────────────────────────

def test_no_constraint_disagreement_when_consumer_has_no_evidence():
    """
    A field has minimum/maximum constraints but the consumer code has no
    pattern-matched constraint evidence (empty inferred_constraints).
    Rule-based detection must NOT fire — absence of evidence is not a conflict.
    """
    field = _make_field(
        constraints=[
            Constraint(kind="minimum", value="0", source="openapi"),
            Constraint(kind="maximum", value="10000", source="openapi"),
        ]
    )
    belief = _make_belief(inferred_constraints=[])
    result = detect_disagreements(field, None, belief)
    kinds = [d.kind for d in result]
    assert DisagreementKind.CONSTRAINT_UNKNOWN_TO_CONSUMER not in kinds, (
        "Rule-based CONSTRAINT_UNKNOWN_TO_CONSUMER must never fire — it has no positive evidence"
    )


def test_no_constraint_disagreement_when_field_has_format_enum_constraints_only():
    """format and enum constraints were already excluded; this should still not fire."""
    field = _make_field(
        constraints=[
            Constraint(kind="format", value="date-time", source="openapi"),
            Constraint(kind="enum", value="ACTIVE,INACTIVE", source="openapi"),
        ]
    )
    belief = _make_belief(inferred_constraints=[])
    result = detect_disagreements(field, None, belief)
    kinds = [d.kind for d in result]
    assert DisagreementKind.CONSTRAINT_UNKNOWN_TO_CONSUMER not in kinds


def test_no_constraint_disagreement_when_no_constraints():
    """Field with no constraints — obviously no CONSTRAINT_UNKNOWN_TO_CONSUMER."""
    field = _make_field(constraints=[])
    belief = _make_belief(inferred_constraints=[])
    result = detect_disagreements(field, None, belief)
    kinds = [d.kind for d in result]
    assert DisagreementKind.CONSTRAINT_UNKNOWN_TO_CONSUMER not in kinds


# ── NULLABLE_CHANGED ─────────────────────────────────────────────────────────

def test_nullable_changed_fires_for_dangerous_direction():
    """
    Consumer assumes the field is NEVER null (assumed_nullable=False),
    but producer declares it IS nullable (field.nullable=True).
    Consumer code will crash when null arrives — this IS a real disagreement.
    """
    field = _make_field(nullable=True)
    belief = _make_belief(assumed_nullable=False)
    result = detect_disagreements(field, None, belief)
    kinds = [d.kind for d in result]
    assert DisagreementKind.NULLABLE_CHANGED in kinds, (
        "Must flag: consumer assumes non-null but producer can send null"
    )


def test_nullable_changed_suppressed_for_safe_direction():
    """
    Consumer defensively null-checks a non-nullable field (assumed_nullable=True)
    but producer declares it non-nullable (field.nullable=False).
    Defensive checks are harmless — this must NOT be flagged.
    """
    field = _make_field(nullable=False)
    belief = _make_belief(assumed_nullable=True)
    result = detect_disagreements(field, None, belief)
    kinds = [d.kind for d in result]
    assert DisagreementKind.NULLABLE_CHANGED not in kinds, (
        "Must NOT flag: consumer is defensively null-safe on a non-nullable field"
    )


def test_nullable_changed_suppressed_when_both_agree_nullable():
    """Both producer and consumer agree the field is nullable — no disagreement."""
    field = _make_field(nullable=True)
    belief = _make_belief(assumed_nullable=True)
    result = detect_disagreements(field, None, belief)
    kinds = [d.kind for d in result]
    assert DisagreementKind.NULLABLE_CHANGED not in kinds


def test_nullable_changed_suppressed_when_both_agree_non_nullable():
    """Both agree non-nullable — no disagreement."""
    field = _make_field(nullable=False)
    belief = _make_belief(assumed_nullable=False)
    result = detect_disagreements(field, None, belief)
    kinds = [d.kind for d in result]
    assert DisagreementKind.NULLABLE_CHANGED not in kinds


def test_nullable_no_belief_does_not_fire():
    """belief.assumed_nullable is None means no evidence — must not fire."""
    field = _make_field(nullable=True)
    belief = _make_belief(assumed_nullable=None)
    result = detect_disagreements(field, None, belief)
    kinds = [d.kind for d in result]
    assert DisagreementKind.NULLABLE_CHANGED not in kinds


# ── Existing behaviours still work ───────────────────────────────────────────

def test_unit_mismatch_still_detected():
    """UNIT_MISMATCH from the semantic profile path must be unaffected."""
    field = _make_field()
    profile = SemanticProfile(
        field_fqn=field.fqn,
        unit="pence",
        domain="billing",
        confidence=0.9,
        generated_at=datetime.utcnow(),
    )
    belief = _make_belief(assumed_unit="pounds")
    result = detect_disagreements(field, profile, belief)
    kinds = [d.kind for d in result]
    assert DisagreementKind.UNIT_MISMATCH in kinds


def test_type_changed_still_detected():
    """TYPE_CHANGED from field declared_type vs belief assumed_type must be unaffected."""
    field = _make_field(declared_type="boolean")
    belief = _make_belief(assumed_type="integer")
    result = detect_disagreements(field, None, belief)
    kinds = [d.kind for d in result]
    assert DisagreementKind.TYPE_CHANGED in kinds


def test_clean_field_produces_no_disagreements():
    """A field and belief that fully agree must produce zero disagreements."""
    field = _make_field(declared_type="integer", nullable=False)
    belief = _make_belief(assumed_type="integer", assumed_nullable=False)
    result = detect_disagreements(field, None, belief)
    assert result == [], f"Expected no disagreements, got: {result}"
