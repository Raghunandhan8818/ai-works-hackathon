from __future__ import annotations

import json
import os
from typing import Any

from ripple.rib.graph.schema import ConsumerBelief, FieldNode, FieldUsage

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


_OPS_SYSTEM = """\
You classify how consumer code uses an API field based on source code snippets.
For each snippet, return one or more operations from this list:
  display        — value rendered/returned to a user directly
  compare_enum   — compared to a string/enum literal (e.g. === "ACTIVE", .equals("GOLD"))
  compare_number — compared to a numeric value (e.g. > 0, >= 100)
  divide         — divided (e.g. / 100, / 1000) — implies scale assumption
  multiply       — multiplied (e.g. * 100, * 1000)
  parse_date     — passed to a date parser or constructor (new Date(), moment(), LocalDate.parse)
  parse_number   — parsed to int/float (parseInt, Number(), Integer.parseInt)
  read_subfield  — accessed as object.property (implies field is an object, not a scalar)
  construct_body — used as a key in a request payload being built (e.g. { fieldName: value })
  store_local    — stored in state, localStorage, a variable for later use
  negate         — boolean-negated (!field, field == false)
  unknown        — cannot determine from the snippet

Return a JSON array, one entry per input snippet, preserving order:
[["op1", "op2"], ["op1"], ...]
Return [] for a snippet if the operation is truly unknown.
"""


_BATCH_SIZE = 50  # usages per LLM call — keeps input well within context window


def infer_operations_batch(
    usages: list[FieldUsage],
    api_key: str | None = None,
) -> list[FieldUsage]:
    """Infer semantic operations for usages that have source_context but no operations yet.

    Processes in chunks of _BATCH_SIZE to stay within LLM context limits.
    Usages already having operations (grep-derived) or lacking source_context are skipped.
    Returns a new list with .operations populated where inferred.
    """
    import json as _json
    import os
    import re as _re

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return usages

    # Only process usages that have source_context and no operations yet
    # (grep usages already have operations from regex extraction)
    to_enrich = [(i, u) for i, u in enumerate(usages) if u.source_context and not u.operations]
    if not to_enrich:
        return usages

    result = list(usages)

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=key)

        for chunk_start in range(0, len(to_enrich), _BATCH_SIZE):
            chunk = to_enrich[chunk_start: chunk_start + _BATCH_SIZE]
            snippets = [u.source_context[:400] for _, u in chunk]
            # max_tokens scales with batch size: ~60 tokens per entry is sufficient
            max_tok = min(len(chunk) * 60 + 128, 4096)

            try:
                msg = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=max_tok,
                    system=_OPS_SYSTEM,
                    messages=[{"role": "user", "content": _json.dumps(snippets)}],
                )
                raw = msg.content[0].text or "[]"
                m = _re.search(r"\[.*\]", raw, _re.DOTALL)
                if not m:
                    continue
                ops_list: list[list[str]] = _json.loads(m.group())
                for batch_idx, (original_idx, usage) in enumerate(chunk):
                    if batch_idx < len(ops_list) and isinstance(ops_list[batch_idx], list):
                        valid_ops = [op for op in ops_list[batch_idx] if isinstance(op, str) and op.strip()]
                        if valid_ops:
                            result[original_idx] = usage.model_copy(update={"operations": valid_ops})
            except Exception:
                continue  # one bad chunk doesn't break the rest

    except Exception:
        pass

    return result
