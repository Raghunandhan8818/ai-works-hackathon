from __future__ import annotations

import json
import os
from typing import Any

from ripple.rib.graph.schema import ConsumerBelief, FieldNode

BELIEF_PROMPT = """You infer how a consumer service uses an API field from usage snippets only.
Return JSON: {"assumed_unit": string|null, "assumed_type": string|null, "assumed_nullable": bool|null, "assumed_format": string|null, "inferred_constraints": [string], "confidence": float}
Ground answers in the snippets; use null when unknown."""


def enrich_belief(
    belief: ConsumerBelief,
    field: FieldNode,
    api_key: str | None = None,
) -> ConsumerBelief:
    payload = {
        "field_fqn": field.fqn,
        "declared_type": field.declared_type,
        "usage_expressions": belief.usage_expressions,
        "heuristic_unit": belief.assumed_unit,
        "heuristic_type": belief.assumed_type,
    }
    parsed = _call_llm(payload, api_key=api_key)
    return belief.model_copy(
        update={
            "assumed_unit": parsed.get("assumed_unit", belief.assumed_unit),
            "assumed_type": parsed.get("assumed_type", belief.assumed_type),
            "assumed_nullable": parsed.get("assumed_nullable", belief.assumed_nullable),
            "assumed_format": parsed.get("assumed_format", belief.assumed_format),
            "inferred_constraints": parsed.get("inferred_constraints")
            or belief.inferred_constraints,
            "confidence": float(parsed.get("confidence") or belief.confidence),
        }
    )


def _call_llm(payload: dict[str, Any], api_key: str | None = None) -> dict[str, Any]:
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key or not payload.get("usage_expressions"):
        return {}

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        message = client.messages.create(
            model="claude-3-5-haiku-latest",
            max_tokens=384,
            system=BELIEF_PROMPT,
            messages=[{"role": "user", "content": json.dumps(payload)}],
        )
        text = message.content[0].text if message.content else "{}"
        return json.loads(_extract_json(text))
    except Exception:
        return {}


def _extract_json(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return "{}"
