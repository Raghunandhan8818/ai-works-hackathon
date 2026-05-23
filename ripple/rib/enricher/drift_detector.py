"""
Semantic drift detector — Priority 5.

On every re-ingest, compares the new BusinessContext producer_intent against
the previously stored one using Haiku. Detects meaning changes that are
invisible to schema diffing:

  "amount is in pence"   →  "amount is in pounds"   →  CRITICAL drift
  "tier is GOLD/SILVER"  →  "tier is gold/silver"   →  HIGH drift (case change)
  "nullable means N/A"   →  "nullable means unknown" →  MEDIUM drift

Stores a DriftEvent for every detected change. These accumulate over time
giving you a semantic changelog of the API contract — something no schema
diff tool can produce.

This is the architectural moat: drift that looks like no change to git diff.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

from ripple.rib.graph.schema import BusinessContext, ConsumerBelief, DriftEvent, Severity

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a semantic contract auditor comparing two versions of an API field description.

Determine whether the MEANING of the field has changed between the previous and current version.
Focus on:
- Unit changes (pence → pounds, ms → seconds, cents → dollars)
- Domain changes (status → metric, identity → free-text)
- Nullability meaning changes ("null means N/A" → "null means unknown")
- Enum value changes (GOLD → gold, case sensitivity)
- Range/invariant changes (was always positive → can now be negative)
- Purpose changes (field repurposed for different use)

Ignore: wording improvements, added detail, rephrasing that preserves meaning.

Return JSON:
{
  "has_drifted": true | false,
  "severity": "CRITICAL" | "HIGH" | "MEDIUM" | "LOW",
  "is_breaking": true | false,
  "explanation": "<one clear sentence: what specifically changed in meaning>"
}

has_drifted=false if meaning is equivalent.
is_breaking=true if consumers relying on old meaning will silently produce wrong results.
"""

# Minimum character difference to bother calling the LLM
# (avoids API calls for trivial rewording)
_MIN_DIFF_CHARS = 30


def _should_skip_drift(
    previous_context: Optional[BusinessContext],
    current_context: BusinessContext,
) -> tuple[bool, str, str]:
    """Returns (skip, prev_intent, curr_intent)."""
    if previous_context is None:
        return True, "", ""
    prev_intent = (previous_context.producer_intent or "").strip()
    curr_intent = (current_context.producer_intent or "").strip()
    if not prev_intent or not curr_intent:
        return True, prev_intent, curr_intent
    if prev_intent == curr_intent:
        return True, prev_intent, curr_intent
    if _char_diff(prev_intent, curr_intent) < _MIN_DIFF_CHARS:
        return True, prev_intent, curr_intent
    return False, prev_intent, curr_intent


def detect_drift(
    field_fqn: str,
    previous_context: Optional[BusinessContext],
    current_context: BusinessContext,
    api_key: Optional[str] = None,
) -> Optional[DriftEvent]:
    skip, prev_intent, curr_intent = _should_skip_drift(previous_context, current_context)
    if skip:
        return None

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        event = _llm_detect(field_fqn, prev_intent, curr_intent, api_key)
        if event:
            return event

    return _heuristic_detect(field_fqn, prev_intent, curr_intent)


async def detect_drift_async(
    field_fqn: str,
    previous_context: Optional[BusinessContext],
    current_context: BusinessContext,
    api_key: Optional[str] = None,
) -> Optional[DriftEvent]:
    skip, prev_intent, curr_intent = _should_skip_drift(previous_context, current_context)
    if skip:
        return None

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if api_key:
        event = await _llm_detect_async(field_fqn, prev_intent, curr_intent, api_key)
        if event:
            return event

    return _heuristic_detect(field_fqn, prev_intent, curr_intent)


async def detect_cross_consumer_drift(
    field_fqn: str,
    consumer_beliefs: list["ConsumerBelief"],
    api_key: Optional[str] = None,
) -> list[DriftEvent]:
    """Detect semantic drift by comparing beliefs across multiple consumers of the same field.

    If Consumer A believes 'price is in dollars' and Consumer B believes 'price is in cents',
    that divergence reveals undocumented semantic drift — independent of any PR.
    Returns one DriftEvent per detected divergence pair.
    """
    if len(consumer_beliefs) < 2:
        return []

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []

    # Build a compact belief summary per consumer
    summaries = []
    for b in consumer_beliefs:
        parts = []
        if b.assumed_unit:
            parts.append(f"unit={b.assumed_unit}")
        if b.assumed_type:
            parts.append(f"type={b.assumed_type}")
        if b.assumed_format:
            parts.append(f"format={b.assumed_format}")
        if b.inferred_constraints:
            parts.append(f"constraints={'; '.join(b.inferred_constraints[:2])}")
        if b.usage_expressions:
            parts.append(f"uses={b.usage_expressions[0][:80]}")
        summaries.append(f"  {b.consumer_service}: {', '.join(parts) or 'no strong beliefs'}")

    prompt = (
        f"Field: {field_fqn}\n\n"
        f"Multiple consumers have different beliefs about this field:\n"
        + "\n".join(summaries)
        + "\n\nAre any of these beliefs CONTRADICTORY (e.g. one assumes dollars, another assumes cents)?"
        " If so, identify which pairs contradict and what the conflict is.\n\n"
        "Return JSON:\n"
        '{"has_conflict": true|false, "severity": "CRITICAL|HIGH|MEDIUM|LOW", "is_breaking": true|false,'
        ' "explanation": "<one sentence describing the conflict>"}'
    )

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text or "{}"
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            return []
        data = json.loads(m.group())
        if not data.get("has_conflict"):
            return []

        severity_raw = data.get("severity", "MEDIUM").upper()
        if severity_raw not in {s.value for s in Severity}:
            severity_raw = "MEDIUM"

        prev = f"Beliefs: {summaries[0]}"
        curr = f"Conflicting: {'; '.join(summaries[1:])}"

        logger.info(
            "cross_consumer_drift CONFLICT field=%s severity=%s: %s",
            field_fqn, severity_raw, data.get("explanation", ""),
        )
        return [DriftEvent(
            field_fqn=field_fqn,
            detected_at=datetime.now(timezone.utc),
            previous_intent=prev[:2000],
            current_intent=curr[:2000],
            drift_explanation=str(data.get("explanation", "Consumer belief divergence detected"))[:1000],
            severity=Severity(severity_raw),
            is_breaking=bool(data.get("is_breaking", False)),
        )]
    except Exception as e:
        logger.warning("cross_consumer_drift failed field=%s: %s", field_fqn, e)
        return []


# ── LLM detection ─────────────────────────────────────────────────────────────

def _build_drift_prompt(prev_intent: str, curr_intent: str) -> str:
    return (
        f"PREVIOUS MEANING:\n{prev_intent[:600]}\n\n"
        f"CURRENT MEANING:\n{curr_intent[:600]}"
    )


def _llm_detect(
    field_fqn: str,
    prev_intent: str,
    curr_intent: str,
    api_key: str,
) -> Optional[DriftEvent]:
    prompt = _build_drift_prompt(prev_intent, curr_intent)
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text
        return _parse_llm_response(field_fqn, prev_intent, curr_intent, raw)
    except Exception as e:
        logger.warning("drift_detector LLM failed field=%s: %s", field_fqn, e)
        return None


async def _llm_detect_async(
    field_fqn: str,
    prev_intent: str,
    curr_intent: str,
    api_key: str,
) -> Optional[DriftEvent]:
    prompt = _build_drift_prompt(prev_intent, curr_intent)
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text
        return _parse_llm_response(field_fqn, prev_intent, curr_intent, raw)
    except Exception as e:
        logger.warning("drift_detector LLM failed field=%s: %s", field_fqn, e)
        return None


def _parse_llm_response(
    field_fqn: str,
    prev_intent: str,
    curr_intent: str,
    raw: str,
) -> Optional[DriftEvent]:
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None
    try:
        data = json.loads(m.group())
    except json.JSONDecodeError:
        return None

    if not data.get("has_drifted", False):
        return None

    severity_raw = data.get("severity", "MEDIUM").upper()
    valid_severities = {s.value for s in Severity}
    if severity_raw not in valid_severities:
        severity_raw = "MEDIUM"

    explanation = str(data.get("explanation", "Semantic drift detected"))[:1000]
    is_breaking = bool(data.get("is_breaking", False))

    logger.info(
        "drift_detector DRIFT DETECTED field=%s severity=%s breaking=%s",
        field_fqn, severity_raw, is_breaking,
    )

    return DriftEvent(
        field_fqn=field_fqn,
        detected_at=datetime.now(timezone.utc),
        previous_intent=prev_intent[:2000],
        current_intent=curr_intent[:2000],
        drift_explanation=explanation,
        severity=Severity(severity_raw),
        is_breaking=is_breaking,
    )


# ── Heuristic fallback ────────────────────────────────────────────────────────

# Pairs of terms that signal a unit/meaning change if one appears and the other disappears
_DRIFT_SIGNALS = [
    ({"pence", "cents", "minor unit"}, {"pounds", "dollars", "major unit"}),
    ({"milliseconds", "ms"}, {"seconds", "s"}),
    ({"uppercase", "UPPER"}, {"lowercase", "lower"}),
    ({"nullable means", "null indicates"}, set()),  # any change in null semantics
    ({"non-negative", "positive"}, {"negative", "deficit"}),
    ({"integer", "int"}, {"float", "decimal", "double"}),
]


def _heuristic_detect(
    field_fqn: str,
    prev_intent: str,
    curr_intent: str,
) -> Optional[DriftEvent]:
    prev_lower = prev_intent.lower()
    curr_lower = curr_intent.lower()

    for group_a, group_b in _DRIFT_SIGNALS:
        prev_has_a = any(t in prev_lower for t in group_a)
        curr_has_b = any(t in curr_lower for t in group_b) if group_b else False
        curr_has_a = any(t in curr_lower for t in group_a)

        # A → B transition
        if prev_has_a and curr_has_b and not curr_has_a:
            explanation = (
                f"Heuristic: terms {group_a} present previously, "
                f"replaced by {group_b} in current version"
            )
            return DriftEvent(
                field_fqn=field_fqn,
                detected_at=datetime.now(timezone.utc),
                previous_intent=prev_intent[:2000],
                current_intent=curr_intent[:2000],
                drift_explanation=explanation,
                severity=Severity.HIGH,
                is_breaking=True,
            )

    return None


# ── Utilities ─────────────────────────────────────────────────────────────────

def _char_diff(a: str, b: str) -> int:
    """Rough measure of how different two strings are."""
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    changed = len(words_a.symmetric_difference(words_b))
    return changed * 5  # approximate char equivalent
