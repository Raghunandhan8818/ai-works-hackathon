from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from ripple.rib.graph.schema import FieldNode, HistorySignal, SemanticProfile

PROFILE_PROMPT = """You analyze API contract fields. Given structured field metadata only, return JSON:
{"unit": string|null, "domain": string|null, "invariants": [string], "risk_flags": [string], "confidence": float, "evidence": [string]}
Do not invent facts not supported by the input."""


def _build_payload(field: FieldNode, history_signals: list[HistorySignal]) -> dict[str, Any]:
    return {
        "fqn": field.fqn,
        "name": field.name,
        "declared_type": field.declared_type,
        "nullable": field.nullable,
        "constraints": [c.model_dump() for c in field.constraints],
        "history": [
            {"message": s.commit_message, "risk_keywords": s.risk_keywords}
            for s in history_signals[:10]
        ],
    }


def _to_profile(field: FieldNode, parsed: dict[str, Any]) -> SemanticProfile:
    return SemanticProfile(
        field_fqn=field.fqn,
        unit=parsed.get("unit"),
        domain=parsed.get("domain"),
        invariants=parsed.get("invariants") or [],
        risk_flags=parsed.get("risk_flags") or [],
        confidence=float(parsed.get("confidence") or 0.5),
        evidence=parsed.get("evidence") or [],
        generated_at=datetime.utcnow(),
        source_commit_hash="",
    )


def profile_field(
    field: FieldNode,
    history_signals: list[HistorySignal] | None = None,
    api_key: str | None = None,
) -> SemanticProfile:
    history_signals = history_signals or []
    payload = _build_payload(field, history_signals)
    parsed = _call_llm(payload, api_key=api_key)
    return _to_profile(field, parsed)


async def profile_field_async(
    field: FieldNode,
    history_signals: list[HistorySignal] | None = None,
    api_key: str | None = None,
) -> SemanticProfile:
    history_signals = history_signals or []
    payload = _build_payload(field, history_signals)
    parsed = await _call_llm_async(payload, api_key=api_key)
    return _to_profile(field, parsed)


def _call_llm(payload: dict[str, Any], api_key: str | None = None) -> dict[str, Any]:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return _heuristic_profile(payload)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=512,
            system=PROFILE_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        text = message.content[0].text if message.content else "{}"
        return json.loads(_extract_json(text))
    except Exception:
        return _heuristic_profile(payload)


async def _call_llm_async(payload: dict[str, Any], api_key: str | None = None) -> dict[str, Any]:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return _heuristic_profile(payload)

    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=key)
        message = await client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=512,
            system=PROFILE_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        text = message.content[0].text if message.content else "{}"
        return json.loads(_extract_json(text))
    except Exception:
        return _heuristic_profile(payload)


def _heuristic_profile(payload: dict[str, Any]) -> dict[str, Any]:
    constraints = payload.get("constraints") or []
    risk_flags: list[str] = []
    unit = None
    domain = None
    for constraint in constraints:
        kind = constraint.get("kind")
        value = str(constraint.get("value", "")).lower()
        if kind == "format" and value in ("int64", "int32", "integer"):
            unit = "integer_raw"
        if kind == "format" and value in ("float", "double", "decimal"):
            unit = "decimal"
            domain = "numeric"
        if kind == "format" and value in ("date-time", "date"):
            domain = "temporal"
        if kind == "enum":
            risk_flags.append("enum_constrained")
    history = payload.get("history") or []
    for entry in history:
        risk_flags.extend(entry.get("risk_keywords") or [])
    return {
        "unit": unit,
        "domain": domain,
        "invariants": [],
        "risk_flags": sorted(set(risk_flags)),
        "confidence": 0.4 if not constraints else 0.6,
        "evidence": ["heuristic_fallback"],
    }


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return "{}"
