from __future__ import annotations

from datetime import datetime

from ripple.rib.graph.schema import (
    ConsumerBelief,
    Disagreement,
    DisagreementKind,
    FieldNode,
    SemanticProfile,
    Severity,
)

UNIT_EQUIVALENTS = {
    ("decimal", "currency_decimal"): False,
    ("integer_raw", "pence_to_pounds"): True,
    ("decimal", "pounds_to_pence"): True,
    ("pence_to_pounds", "pounds_to_pence"): True,
}


def detect_disagreements(
    field: FieldNode,
    profile: SemanticProfile | None,
    belief: ConsumerBelief,
) -> list[Disagreement]:
    disagreements: list[Disagreement] = []
    now = datetime.utcnow()

    if profile and profile.unit and belief.assumed_unit:
        if not _units_compatible(profile.unit, belief.assumed_unit):
            disagreements.append(
                Disagreement(
                    field_fqn=field.fqn,
                    consumer_service=belief.consumer_service,
                    kind=DisagreementKind.UNIT_MISMATCH,
                    producer_says=profile.unit,
                    consumer_assumes=belief.assumed_unit,
                    severity=Severity.CRITICAL,
                    evidence=belief.usage_expressions[:5],
                    explanation="",
                    detected_at=now,
                )
            )

    if belief.assumed_type and field.declared_type:
        if not _types_compatible(field.declared_type, belief.assumed_type):
            disagreements.append(
                Disagreement(
                    field_fqn=field.fqn,
                    consumer_service=belief.consumer_service,
                    kind=DisagreementKind.TYPE_CHANGED,
                    producer_says=field.declared_type,
                    consumer_assumes=belief.assumed_type,
                    severity=Severity.HIGH,
                    evidence=belief.usage_expressions[:5],
                    explanation="",
                    detected_at=now,
                )
            )

    # Only flag the dangerous direction: consumer assumes non-null but producer declares
    # nullable. A consumer defensively null-checking a non-nullable field is harmless.
    if belief.assumed_nullable is False and field.nullable is True:
        disagreements.append(
            Disagreement(
                field_fqn=field.fqn,
                consumer_service=belief.consumer_service,
                kind=DisagreementKind.NULLABLE_CHANGED,
                producer_says=str(field.nullable),
                consumer_assumes=str(belief.assumed_nullable),
                severity=Severity.HIGH,
                evidence=belief.usage_expressions[:5],
                explanation="",
                detected_at=now,
            )
        )

    format_constraints = [
        c.value for c in field.constraints if c.kind == "format"
    ]
    if belief.assumed_format and format_constraints:
        if belief.assumed_format not in format_constraints:
            disagreements.append(
                Disagreement(
                    field_fqn=field.fqn,
                    consumer_service=belief.consumer_service,
                    kind=DisagreementKind.FORMAT_MISMATCH,
                    producer_says=",".join(format_constraints),
                    consumer_assumes=belief.assumed_format,
                    severity=Severity.MEDIUM,
                    evidence=belief.usage_expressions[:5],
                    explanation="",
                    detected_at=now,
                )
            )

    # CONSTRAINT_UNKNOWN_TO_CONSUMER is intentionally not detected here.
    # Absence of constraint-checking code is not evidence of a conflict.
    # This kind is emitted only by LLM paths (cross_repo_graph_builder,
    # llm_disagreement_detector) which have actual code evidence to reason over.

    return disagreements


def _units_compatible(producer_unit: str, consumer_unit: str) -> bool:
    if producer_unit == consumer_unit:
        return True
    pair = (producer_unit, consumer_unit)
    if pair in UNIT_EQUIVALENTS:
        return UNIT_EQUIVALENTS[pair]
    inverse = (consumer_unit, producer_unit)
    if inverse in UNIT_EQUIVALENTS:
        return UNIT_EQUIVALENTS[inverse]
    return False


def _types_compatible(declared: str, assumed: str) -> bool:
    declared_lower = declared.lower()
    assumed_lower = assumed.lower()
    if declared_lower == assumed_lower:
        return True
    if "int" in declared_lower and assumed_lower == "integer":
        return True
    if "float" in declared_lower or "double" in declared_lower:
        return assumed_lower in ("float", "decimal", "currency_decimal")
    if "string" in declared_lower and assumed_lower in ("json_object", "email", "uuid"):
        return True
    return False
