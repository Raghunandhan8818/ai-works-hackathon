"""
Business context builder — the LLM synthesis layer.

Assembles all MLKI layers into a single rich context payload and calls Claude
to synthesize a BusinessContext: the ground-truth meaning of a field.

Input layers:
  - Layer 4: OpenAPI contract (FieldNode)
  - Layer 5: Git history (HistorySignal)
  - Layer 1: Producer code structure (CodeClass, CodeMethod with docstrings)
  - Layer 1: Consumer usages with local var names and operations (FieldUsage)
  - Layer 3: Test evidence (TestEvidence) — strongest semantic signal
  - Layer 4: Existing semantic profile (SemanticProfile)

Output: BusinessContext with producer_intent, consumer_guidance, unit, domain,
invariants — stored once, used by every downstream LLM call.
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
    CodeClass,
    CodeMethod,
    FieldNode,
    FieldUsage,
    HistorySignal,
    SemanticProfile,
    TestEvidence,
)

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a senior software architect analysing API field contracts across microservices.

Given evidence about a single API field — its declaration, producer code, consumer usage
patterns, test assertions, and git history — synthesise a precise BusinessContext.

Your output must be JSON with exactly these keys:
{
  "unit": "<physical unit or null>",
  "domain": "<business domain: financial, temporal, identity, status, metric, text, boolean, other>",
  "producer_intent": "<one paragraph: what this field represents, its unit, invariants, and any gotchas>",
  "consumer_guidance": "<one paragraph: what consumers MUST know to use this field correctly>",
  "invariants": ["<list of hard constraints>"],
  "confidence": <0.0-1.0>
}

Rules:
- Be concrete. Say "integer pence (GBP×100)" not "some monetary value".
- Local variable names in consumer code are strong unit signals: amountInPounds → consumer treats as pounds.
- Test assertions are the strongest signal: assertEquals(100, amount) in testAmountInPence → unit=pence.
- Operations on the value: divide_by_100 → consumer converts from smaller unit (e.g., pence) to larger (pounds).
- Docstrings from the producer class/method are authoritative.
- If evidence contradicts itself, explain the contradiction in producer_intent.
- confidence: 0.9+ if you have test evidence or docstrings; 0.6-0.8 for strong code signals; 0.3-0.5 for heuristics only.
"""


def build_business_context(
    field: FieldNode,
    semantic_profile: Optional[SemanticProfile] = None,
    history_signals: Optional[list[HistorySignal]] = None,
    producer_classes: Optional[list[CodeClass]] = None,
    producer_methods: Optional[list[CodeMethod]] = None,
    consumer_usages: Optional[list[FieldUsage]] = None,
    test_evidences: Optional[list[TestEvidence]] = None,
    api_key: Optional[str] = None,
) -> BusinessContext:
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    payload = _assemble_payload(
        field, semantic_profile, history_signals or [],
        producer_classes or [], producer_methods or [],
        consumer_usages or [], test_evidences or [],
    )

    if api_key:
        ctx = _call_llm(field.fqn, payload, api_key)
        if ctx:
            return ctx

    return _heuristic_context(field, semantic_profile, consumer_usages or [], test_evidences or [])


async def build_business_context_async(
    field: FieldNode,
    semantic_profile: Optional[SemanticProfile] = None,
    history_signals: Optional[list[HistorySignal]] = None,
    producer_classes: Optional[list[CodeClass]] = None,
    producer_methods: Optional[list[CodeMethod]] = None,
    consumer_usages: Optional[list[FieldUsage]] = None,
    test_evidences: Optional[list[TestEvidence]] = None,
    api_key: Optional[str] = None,
) -> BusinessContext:
    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    payload = _assemble_payload(
        field, semantic_profile, history_signals or [],
        producer_classes or [], producer_methods or [],
        consumer_usages or [], test_evidences or [],
    )

    if api_key:
        ctx = await _call_llm_async(field.fqn, payload, api_key)
        if ctx:
            return ctx

    return _heuristic_context(field, semantic_profile, consumer_usages or [], test_evidences or [])


# ── Payload assembly ──────────────────────────────────────────────────────────

def _assemble_payload(
    field: FieldNode,
    profile: Optional[SemanticProfile],
    history: list[HistorySignal],
    producer_classes: list[CodeClass],
    producer_methods: list[CodeMethod],
    usages: list[FieldUsage],
    tests: list[TestEvidence],
) -> str:
    parts: list[str] = []

    # ── Layer 4: API contract ──
    parts.append(f"## FIELD CONTRACT (OpenAPI)\n"
                 f"Field name: {field.name}\n"
                 f"Producer service: {field.producer_service}\n"
                 f"Endpoint: {field.endpoint_or_topic}\n"
                 f"Field path: {field.field_path}\n"
                 f"Declared type: {field.declared_type}\n"
                 f"Nullable: {field.nullable}\n"
                 f"Deprecated: {field.deprecated}")

    if field.constraints:
        c_str = "; ".join(f"{c.kind}={c.value}" for c in field.constraints)
        parts[-1] += f"\nConstraints: {c_str}"

    # ── Layer 4: Existing semantic profile ──
    if profile:
        parts.append(
            f"## EXISTING SEMANTIC PROFILE\n"
            f"Unit: {profile.unit}\nDomain: {profile.domain}\n"
            f"Invariants: {'; '.join(profile.invariants)}\n"
            f"Risk flags: {'; '.join(profile.risk_flags)}\n"
            f"Confidence: {profile.confidence}"
        )

    # ── Layer 1: Producer classes with docstrings ──
    if producer_classes:
        class_docs = [
            f"  {c.class_name} ({c.file_path}:{c.line_start})\n"
            f"  Superclasses: {', '.join(c.superclasses) or 'none'}\n"
            f"  Docstring: {c.docstring or '(none)'}"
            for c in producer_classes[:5]
        ]
        parts.append("## PRODUCER CLASSES\n" + "\n\n".join(class_docs))

    # ── Layer 1: Producer methods with docstrings ──
    if producer_methods:
        method_docs = [
            f"  {m.class_name or '(module)'}.{m.method_name}  ({m.file_path}:{m.line})\n"
            f"  Signature: {m.signature}\n"
            f"  Docstring: {m.docstring or '(none)'}"
            for m in producer_methods[:8]
        ]
        parts.append("## PRODUCER METHODS\n" + "\n\n".join(method_docs))

    # ── Layer 3: Test evidence (strongest signal) ──
    if tests:
        test_blocks = [
            f"  Test: {t.test_method}  (in {t.test_file})\n"
            f"  Assertion:\n{_indent(t.assertion_code, 4)}"
            for t in tests[:10]
        ]
        parts.append(
            "## TEST EVIDENCE  ← STRONGEST SIGNAL: tests encode business rules\n"
            + "\n\n".join(test_blocks)
        )

    # ── Layer 1: Consumer usages with local var names and operations ──
    if usages:
        usage_blocks: list[str] = []
        for u in usages[:15]:
            block = (
                f"  Service: {u.consumer_service}  File: {u.file_path}:{u.line}\n"
                f"  Class: {u.containing_class or '?'}  Method: {u.containing_function or '?'}\n"
                f"  Expression: {u.expression}\n"
            )
            if u.local_var_name:
                block += f"  Local var name: {u.local_var_name}  ← developer named this\n"
            if u.operations:
                block += f"  Operations on value: {', '.join(u.operations)}\n"
            block += f"  Context:\n{_indent(u.surrounding_context, 4)}"
            usage_blocks.append(block)
        parts.append("## CONSUMER USAGES\n" + "\n\n".join(usage_blocks))

    # ── Layer 5: Git history ──
    if history:
        risk_commits = [
            f"  [{h.committed_at.date()}] {h.author}: {h.commit_message[:120]}"
            + (f"  [risk: {', '.join(h.risk_keywords)}]" if h.risk_keywords else "")
            for h in history[:10]
        ]
        parts.append("## GIT HISTORY (risk signals)\n" + "\n".join(risk_commits))

    return "\n\n" + ("\n\n" + "─" * 60 + "\n\n").join(parts)


# ── LLM call ─────────────────────────────────────────────────────────────────

def _build_context_from_response(field_fqn: str, payload: str, data: dict) -> BusinessContext:
    return BusinessContext(
        field_fqn=field_fqn,
        unit=data.get("unit"),
        domain=data.get("domain", ""),
        producer_intent=data.get("producer_intent", ""),
        consumer_guidance=data.get("consumer_guidance", ""),
        invariants=data.get("invariants", []),
        confidence=float(data.get("confidence", 0.5)),
        evidence_sources=_evidence_sources_used(payload),
        synthesized_at=datetime.now(timezone.utc),
    )


def _call_llm(field_fqn: str, payload: str, api_key: str) -> Optional[BusinessContext]:
    try:
        import anthropic

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
        )
        raw = message.content[0].text
        data = _extract_json(raw)
        if not data:
            logger.warning("business_context_builder bad LLM response field=%s", field_fqn)
            return None
        return _build_context_from_response(field_fqn, payload, data)
    except Exception as e:
        logger.warning("business_context_builder LLM failed field=%s err=%s", field_fqn, e)
        return None


async def _call_llm_async(field_fqn: str, payload: str, api_key: str) -> Optional[BusinessContext]:
    try:
        import anthropic

        client = anthropic.AsyncAnthropic(api_key=api_key)
        message = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
        )
        raw = message.content[0].text
        data = _extract_json(raw)
        if not data:
            logger.warning("business_context_builder bad LLM response field=%s", field_fqn)
            return None
        return _build_context_from_response(field_fqn, payload, data)
    except Exception as e:
        logger.warning("business_context_builder LLM failed field=%s err=%s", field_fqn, e)
        return None


def _extract_json(text: str) -> Optional[dict]:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group())
    except json.JSONDecodeError:
        return None


def _evidence_sources_used(payload: str) -> list[str]:
    sources = []
    if "FIELD CONTRACT" in payload:
        sources.append("openapi")
    if "PRODUCER CLASSES" in payload:
        sources.append("producer_classes")
    if "PRODUCER METHODS" in payload:
        sources.append("producer_methods")
    if "TEST EVIDENCE" in payload:
        sources.append("test_evidence")
    if "CONSUMER USAGES" in payload:
        sources.append("consumer_usages")
    if "GIT HISTORY" in payload:
        sources.append("git_history")
    return sources


# ── Heuristic fallback ────────────────────────────────────────────────────────

def _heuristic_context(
    field: FieldNode,
    profile: Optional[SemanticProfile],
    usages: list[FieldUsage],
    tests: list[TestEvidence],
) -> BusinessContext:
    unit = profile.unit if profile else None
    domain = profile.domain if profile else ""

    # Infer unit from operations in consumer usages
    all_ops: list[str] = []
    for u in usages:
        all_ops.extend(u.operations)

    if not unit:
        if "divide_by_100" in all_ops:
            unit = "pence (÷100 for display)"
        elif "multiply_by_100" in all_ops:
            unit = "decimal (×100 = pence)"
        elif "construct_date" in all_ops or "datetime_operation" in all_ops:
            unit = "timestamp"
        elif "parse_int" in all_ops:
            unit = "integer (stored as string)"

    # Infer domain from field name heuristics
    name_lower = field.name.lower()
    if not domain:
        if any(k in name_lower for k in ("amount", "price", "cost", "fee", "total", "balance")):
            domain = "financial"
        elif any(k in name_lower for k in ("at", "date", "time", "created", "updated", "expires")):
            domain = "temporal"
        elif any(k in name_lower for k in ("id", "uuid", "key", "token")):
            domain = "identity"
        elif any(k in name_lower for k in ("status", "state", "tier", "level", "type")):
            domain = "status"
        else:
            domain = "unknown"

    # Build invariants from constraints
    invariants = []
    for c in field.constraints:
        invariants.append(f"{c.kind}: {c.value}")
    if not field.nullable:
        invariants.append("never null")

    # Collect local var name evidence
    var_names = list({u.local_var_name for u in usages if u.local_var_name})

    producer_intent = (
        f"Field '{field.name}' from {field.producer_service}. "
        f"Declared type: {field.declared_type}. "
        f"Unit: {unit or 'unknown'}. Domain: {domain}."
        + (f" Consumer local var names: {', '.join(var_names)}." if var_names else "")
    )
    consumer_guidance = (
        f"This field is of type {field.declared_type} with unit {unit or 'unknown'}. "
        + ("It is never null. " if not field.nullable else "It may be null. ")
        + (f"Observed operations: {', '.join(set(all_ops))}." if all_ops else "")
    )

    confidence = 0.35
    if unit:
        confidence = 0.5
    if tests:
        confidence = 0.65
    if profile and profile.confidence > confidence:
        confidence = profile.confidence * 0.8  # heuristic can't match LLM

    return BusinessContext(
        field_fqn=field.fqn,
        unit=unit,
        domain=domain,
        producer_intent=producer_intent,
        consumer_guidance=consumer_guidance,
        invariants=invariants,
        confidence=round(confidence, 2),
        evidence_sources=["heuristic"],
        synthesized_at=datetime.now(timezone.utc),
    )


def _indent(text: str, spaces: int) -> str:
    pad = " " * spaces
    return "\n".join(pad + line for line in text.splitlines())
