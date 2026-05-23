"""
LLM-based disagreement detector — Priority 4.

Rules-based detection catches structural breaks (type, nullable, format).
This catches the fuzzy cases rules permanently miss:

  - Unit mismatches:   producer stores pence, consumer assumes pounds
  - Case sensitivity:  producer sends "GOLD", consumer checks "gold"
  - Range assumptions: consumer assumes >= 0, producer never guarantees it
  - Ordering:          consumer assumes array is sorted, producer doesn't
  - Semantic drift:    field meaning changed subtly with same type/name
  - Implicit formats:  consumer assumes ISO date, producer just says "string"

Uses Haiku for speed and cost. Input is kept tight (~800 tokens max).
Returns Disagreement objects with source=LLM, merged with rules output.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from ripple.rib.graph.schema import (
    BusinessContext,
    ConsumerBelief,
    Disagreement,
    DisagreementKind,
    DisagreementSource,
    FieldNode,
    FieldUsage,
    SemanticProfile,
    Severity,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a microservice contract auditor. Your job is to find semantic disagreements
between what a producer API field guarantees and what a consumer assumes in code.

Rules-based checks have already run and caught structural issues (type, nullable, format).
Your job is to find the FUZZY cases they miss:
- Unit mismatches (pence vs pounds, cents vs dollars, ms vs seconds)
- Case/enum value assumptions (GOLD vs gold vs Gold)
- Range/ordering assumptions not in the schema
- Implicit format assumptions (ISO date vs any string)
- Nullability in practice vs schema declaration
- Semantic meaning disagreements

Return a JSON array. Empty array [] if no disagreements found.
Each disagreement:
{
  "kind": one of: UNIT_MISMATCH | TYPE_CHANGED | FORMAT_MISMATCH | CONSTRAINT_UNKNOWN_TO_CONSUMER | ENUM_VALUE_CHANGED,
  "producer_says": "<what producer guarantees>",
  "consumer_assumes": "<what consumer code assumes>",
  "severity": one of: CRITICAL | HIGH | MEDIUM | LOW,
  "explanation": "<one clear sentence explaining the disagreement>"
}

Only return disagreements you have CLEAR CODE EVIDENCE for. Do not speculate.
"""


def detect_llm_disagreements(
    field: FieldNode,
    business_context: Optional[BusinessContext],
    belief: ConsumerBelief,
    usages: list[FieldUsage],
    existing_disagreement_kinds: set[str],
    api_key: Optional[str] = None,
) -> list[Disagreement]:
    """
    Run LLM-based disagreement detection for a single (field, consumer) pair.
    Skips kinds already detected by rules to avoid duplicates.
    Returns Disagreement objects with source=LLM.
    """
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    prompt = _build_prompt(field, business_context, belief, usages)
    raw = _call_haiku(prompt, api_key)
    if not raw:
        return []

    return _parse_response(raw, field, belief.consumer_service, existing_disagreement_kinds)


# ── Prompt assembly ───────────────────────────────────────────────────────────

def _build_prompt(
    field: FieldNode,
    ctx: Optional[BusinessContext],
    belief: ConsumerBelief,
    usages: list[FieldUsage],
) -> str:
    parts: list[str] = []

    # Field contract
    parts.append(
        f"FIELD: {field.name} (from {field.producer_service})\n"
        f"Type: {field.declared_type}  Nullable: {field.nullable}\n"
        f"Endpoint: {field.endpoint_or_topic}"
    )
    if field.constraints:
        parts[-1] += "\nConstraints: " + "; ".join(f"{c.kind}={c.value}" for c in field.constraints)

    # Business context — the ground truth
    if ctx:
        parts.append(
            f"PRODUCER INTENT (synthesised from code + docs):\n"
            f"Unit: {ctx.unit or 'not specified'}\n"
            f"Domain: {ctx.domain}\n"
            f"{ctx.producer_intent}\n"
            f"Invariants: {'; '.join(ctx.invariants) or 'none documented'}"
        )

    # Consumer belief
    parts.append(
        f"CONSUMER ({belief.consumer_service}) BELIEF:\n"
        f"Assumed type: {belief.assumed_type or 'unknown'}\n"
        f"Assumed unit: {belief.assumed_unit or 'unknown'}\n"
        f"Assumed nullable: {belief.assumed_nullable}\n"
        f"Assumed format: {belief.assumed_format or 'unknown'}\n"
        f"Inferred constraints: {'; '.join(belief.inferred_constraints) or 'none'}"
    )

    # Usage evidence — the actual code, capped to avoid token bloat
    if usages:
        usage_lines: list[str] = []
        for u in usages[:6]:
            line = f"  {u.file_path.split('/')[-1]}:{u.line}  {u.expression[:120]}"
            if u.local_var_name:
                line += f"  [var: {u.local_var_name}]"
            if u.operations:
                line += f"  [ops: {', '.join(u.operations)}]"
            usage_lines.append(line)
        parts.append("CONSUMER CODE EVIDENCE:\n" + "\n".join(usage_lines))

    return "\n\n".join(parts)


# ── LLM call ─────────────────────────────────────────────────────────────────

def _call_haiku(prompt: str, api_key: str) -> Optional[str]:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text
    except Exception as e:
        logger.warning("llm_disagreement_detector failed: %s", e)
        return None


# ── Response parsing ──────────────────────────────────────────────────────────

_VALID_KINDS = {k.value for k in DisagreementKind}
_VALID_SEVERITIES = {s.value for s in Severity}


def _parse_response(
    raw: str,
    field: FieldNode,
    consumer_service: str,
    existing_kinds: set[str],
) -> list[Disagreement]:
    m = re.search(r"\[.*\]", raw, re.DOTALL)
    if not m:
        return []
    try:
        items = json.loads(m.group())
    except json.JSONDecodeError:
        return []

    now = datetime.now(timezone.utc)
    results: list[Disagreement] = []

    for item in items:
        if not isinstance(item, dict):
            continue

        kind_raw = item.get("kind", "").upper()
        # Map to closest valid kind if needed
        if kind_raw not in _VALID_KINDS:
            kind_raw = _closest_kind(kind_raw)
        if not kind_raw:
            continue

        # Skip if rules already caught this kind for this (field, consumer)
        if kind_raw in existing_kinds:
            continue

        severity_raw = item.get("severity", "MEDIUM").upper()
        if severity_raw not in _VALID_SEVERITIES:
            severity_raw = "MEDIUM"

        producer_says = str(item.get("producer_says", ""))[:500]
        consumer_assumes = str(item.get("consumer_assumes", ""))[:500]
        explanation = str(item.get("explanation", ""))[:1000]

        if not producer_says or not consumer_assumes:
            continue

        results.append(Disagreement(
            field_fqn=field.fqn,
            consumer_service=consumer_service,
            kind=DisagreementKind(kind_raw),
            producer_says=producer_says,
            consumer_assumes=consumer_assumes,
            severity=Severity(severity_raw),
            evidence=[],
            explanation=explanation,
            detected_at=now,
            source=DisagreementSource.LLM,
        ))

    return results


def _closest_kind(raw: str) -> str:
    """Map non-standard kind strings to the closest valid DisagreementKind."""
    mapping = {
        "UNIT": "UNIT_MISMATCH",
        "TYPE": "TYPE_CHANGED",
        "NULLABLE": "NULLABLE_CHANGED",
        "FORMAT": "FORMAT_MISMATCH",
        "ENUM": "ENUM_VALUE_CHANGED",
        "CONSTRAINT": "CONSTRAINT_UNKNOWN_TO_CONSUMER",
        "FIELD_MISSING": "FIELD_REMOVED",
        "SEMANTIC": "CONSTRAINT_UNKNOWN_TO_CONSUMER",
        "RANGE": "CONSTRAINT_UNKNOWN_TO_CONSUMER",
        "ORDERING": "CONSTRAINT_UNKNOWN_TO_CONSUMER",
        "CASE": "ENUM_VALUE_CHANGED",
    }
    for key, val in mapping.items():
        if key in raw:
            return val
    return ""
