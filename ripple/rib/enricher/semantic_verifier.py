"""
Semantic disagreement verifier — second-opinion LLM pass for SEMANTIC_INTENT_MISMATCH.

The drift detector and PR analyzer catch potential semantic conflicts using one LLM
call that only sees two text descriptions.  That single call can't tell whether the
consumer code is actually *sensitive* to the change — it may just be passing the
field through, or the "conflict" may be a same-service snapshot artefact.

This verifier runs after a candidate SEMANTIC_INTENT_MISMATCH is produced and asks
a targeted question: given the real consumer code evidence, does this consumer
genuinely depend on the old semantic meaning in a way that will break?

A verified=False result suppresses the disagreement before it reaches the store.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Optional

logger = logging.getLogger(__name__)

_SYSTEM = """\
You are a senior engineer verifying whether a flagged API contract disagreement is real.

A tool has detected a potential SEMANTIC_INTENT_MISMATCH between a producer service
and a consumer service. Your job is to decide whether this is a genuine breaking issue
that requires developer attention, or a false positive that should be suppressed.

Rules for verified=false (suppress):
- The consumer and producer are the same service (a service cannot break its own contract).
- The consumer code only stores, forwards, or logs the field — no semantic dependency.
- The "conflict" is a rewording with no change in how the field would be used.
- The evidence shows the field name in unrelated context (e.g. a variable that happens to match).

Rules for verified=true (keep):
- The consumer does arithmetic, comparisons, or conditional logic on the field value.
- The consumer displays the raw value to a user (unit changes would silently mislead).
- The consumer enforces business rules that depend on the old meaning.
- The evidence clearly shows the field being consumed with semantic intent.

Return ONLY valid JSON, no other text:
{
  "verified": true | false,
  "confidence": "HIGH" | "MEDIUM" | "LOW",
  "reason": "<one clear sentence explaining the verdict>"
}
"""


async def verify_semantic_disagreement(
    field_fqn: str,
    producer_service: str,
    consumer_service: str,
    producer_says: str,
    consumer_assumes: str,
    evidence: list[str],
    api_key: Optional[str] = None,
) -> tuple[bool, str]:
    """
    Verify a candidate SEMANTIC_INTENT_MISMATCH disagreement.

    Returns (verified: bool, reason: str).
    If verification cannot run (no API key, LLM error), defaults to True
    so no real disagreement is silently lost.
    """
    # Hard rule: never a cross-service issue when consumer == producer
    fqn_producer = field_fqn.split("::")[0] if "::" in field_fqn else ""
    if fqn_producer and consumer_service == fqn_producer:
        return False, "Self-referential: consumer and producer are the same service."

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("semantic_verifier no API key — defaulting to verified=True for %s", field_fqn)
        return True, "Unverified (no API key) — treated as real."

    evidence_text = "\n".join(f"  • {e}" for e in evidence[:6]) or "  (no evidence available)"

    prompt = f"""\
FIELD: {field_fqn}
PRODUCER SERVICE: {producer_service}
CONSUMER SERVICE: {consumer_service}

WHAT THE PRODUCER NOW SAYS:
  {producer_says}

WHAT THE CONSUMER ASSUMES:
  {consumer_assumes}

ACTUAL CONSUMER CODE EVIDENCE:
{evidence_text}

Is this a genuine breaking contract disagreement that requires developer attention?"""

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key)
        msg = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = msg.content[0].text or "{}"
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            logger.warning("semantic_verifier unparseable response for %s: %s", field_fqn, raw[:100])
            return True, "Verification parse error — treated as real."

        data = json.loads(m.group())
        verified = bool(data.get("verified", True))
        confidence = data.get("confidence", "LOW")
        reason = str(data.get("reason", ""))

        logger.info(
            "semantic_verifier field=%s consumer=%s verified=%s confidence=%s reason=%s",
            field_fqn, consumer_service, verified, confidence, reason,
        )
        return verified, f"[{confidence}] {reason}"

    except Exception as exc:
        logger.warning("semantic_verifier failed for %s: %s — defaulting to verified=True", field_fqn, exc)
        return True, f"Verification error ({exc}) — treated as real."
