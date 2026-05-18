from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Iterable

from ripple.rib.graph.schema import ConsumerBelief, FieldUsage

UNIT_PATTERNS = [
    (re.compile(r"/\s*100\b"), "pence_to_pounds"),
    (re.compile(r"\*\s*100\b"), "pounds_to_pence"),
    (re.compile(r"\.toFixed\(\s*2\s*\)"), "currency_decimal"),
    (re.compile(r"Date\.parse|new Date\(|datetime"), "timestamp"),
]

TYPE_PATTERNS = [
    (re.compile(r"parseInt\(|Number\.parseInt"), "integer"),
    (re.compile(r"parseFloat\(|Number\.parseFloat"), "float"),
    (re.compile(r"Boolean\(|!!"), "boolean"),
    (re.compile(r"JSON\.parse"), "json_object"),
]

NULLABILITY_PATTERNS = [
    (re.compile(r"\?\."), "nullable_safe_access"),
    (re.compile(r"!\s*\.|assert\s+"), "assumed_non_null"),
    (re.compile(r"\|\|\s*0|\|\|\s*''|\?\?"), "default_if_null"),
]


def extract_beliefs_from_usages(
    usages: Iterable[FieldUsage],
) -> list[ConsumerBelief]:
    grouped: dict[tuple[str, str], list[FieldUsage]] = {}
    for usage in usages:
        key = (usage.consumer_service, usage.field_fqn)
        grouped.setdefault(key, []).append(usage)

    beliefs: list[ConsumerBelief] = []
    for (consumer_service, field_fqn), group in grouped.items():
        expressions = [u.expression for u in group if u.expression]
        context_blob = " ".join(
            u.surrounding_context for u in group if u.surrounding_context
        )
        combined = " ".join(expressions + [context_blob])
        beliefs.append(
            ConsumerBelief(
                consumer_service=consumer_service,
                field_fqn=field_fqn,
                assumed_unit=_infer_unit(combined),
                assumed_type=_infer_type(combined),
                assumed_nullable=_infer_nullable(combined),
                assumed_format=_infer_format(combined),
                inferred_constraints=_infer_constraints(combined),
                usage_expressions=expressions,
                confidence=_confidence_score(expressions),
                extracted_at=datetime.utcnow(),
                source_file_hash=_hash_text(combined),
            )
        )
    return beliefs


def _infer_unit(text: str) -> str | None:
    for pattern, label in UNIT_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _infer_type(text: str) -> str | None:
    for pattern, label in TYPE_PATTERNS:
        if pattern.search(text):
            return label
    return None


def _infer_nullable(text: str) -> bool | None:
    if re.search(r"!\.", text):
        return False
    if re.search(r"\?\.", text):
        return True
    return None


def _infer_format(text: str) -> str | None:
    if re.search(r"toISOString|YYYY-MM-DD", text):
        return "iso8601"
    if re.search(r"uuid|guid", text, re.IGNORECASE):
        return "uuid"
    if re.search(r"email", text, re.IGNORECASE):
        return "email"
    return None


def _infer_constraints(text: str) -> list[str]:
    constraints: list[str] = []
    if re.search(r"Math\.round|toFixed", text):
        constraints.append("numeric_precision_expected")
    if re.search(r">=\s*0|Math\.max\(0", text):
        constraints.append("non_negative")
    if re.search(r"enum|includes\(", text):
        constraints.append("enum_membership_check")
    return constraints


def _confidence_score(expressions: list[str]) -> float:
    if not expressions:
        return 0.2
    if len(expressions) >= 3:
        return 0.85
    if len(expressions) == 2:
        return 0.65
    return 0.45


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]
