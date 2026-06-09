# Fix False-Positive Disagreements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate the 84 false-positive `CONSTRAINT_UNKNOWN_TO_CONSUMER` disagreements that appear on every initial ingest by removing a rule with no positive-evidence trigger, and tighten `NULLABLE_CHANGED` to only fire in the genuinely dangerous direction.

**Architecture:** Two targeted edits. (1) Remove the `CONSTRAINT_UNKNOWN_TO_CONSUMER` block from the rule-based detector — this kind requires code evidence, which only the LLM path has. (2) Change `NULLABLE_CHANGED` from a bidirectional check to a unidirectional one: only fire when the consumer assumes non-null but the producer declares nullable. (3) Update the Claude batch prompt to only emit `CONSTRAINT_UNKNOWN_TO_CONSUMER` when consumer operations directly conflict with the constraint.

**Tech Stack:** Python 3.11+, pytest, pydantic v2

---

### Task 1: Write failing tests for detect_disagreements

**Files:**
- Create: `tests/test_disagreement_detector.py`

These tests document the correct behaviour and will fail against the current code.

- [ ] **Step 1: Create test file**

```python
# tests/test_disagreement_detector.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/subbikchak/Desktop/Hackathon/ai-works-hackathon
python -m pytest tests/test_disagreement_detector.py -v 2>&1 | head -60
```

Expected: Several FAILED — specifically:
- `test_no_constraint_disagreement_when_consumer_has_no_evidence` — FAILS (current code fires CONSTRAINT_UNKNOWN_TO_CONSUMER)
- `test_nullable_changed_suppressed_for_safe_direction` — FAILS (current code fires NULLABLE_CHANGED in safe direction)
- All "still detected" tests may also FAIL if the detector hasn't been imported correctly yet

---

### Task 2: Fix detect_disagreements — remove CONSTRAINT_UNKNOWN_TO_CONSUMER and tighten NULLABLE_CHANGED

**Files:**
- Modify: `ripple/rib/enricher/disagreement_detector.py`

- [ ] **Step 1: Open the file and locate the two blocks to change**

The file is at `ripple/rib/enricher/disagreement_detector.py`.

- Block to REMOVE (lines ~77–112):
```python
    format_constraints = [
        c.value for c in field.constraints if c.kind == "format"
    ]
    if belief.assumed_format and format_constraints:
        if belief.assumed_format not in format_constraints:
            disagreements.append(...)  # FORMAT_MISMATCH — KEEP THIS

    unknown_constraints = [                          # ← DELETE from here
        c.kind for c in field.constraints if c.kind not in ("format", "enum")
    ]
    if unknown_constraints and not belief.inferred_constraints:
        disagreements.append(
            Disagreement(
                field_fqn=field.fqn,
                consumer_service=belief.consumer_service,
                kind=DisagreementKind.CONSTRAINT_UNKNOWN_TO_CONSUMER,
                producer_says=",".join(unknown_constraints),
                consumer_assumes="none_observed",
                severity=Severity.MEDIUM,
                evidence=[],
                explanation="",
                detected_at=now,
            )
        )                                            # ← DELETE to here
```

- Block to TIGHTEN (current NULLABLE_CHANGED check):
```python
    if belief.assumed_nullable is not None and belief.assumed_nullable != field.nullable:
```

- [ ] **Step 2: Apply the changes**

Replace the full file content with:

```python
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

    # Only flag the dangerous direction: consumer assumes non-null but producer
    # declares nullable. A consumer defensively null-checking a non-nullable field
    # is harmless and must not be flagged.
    if (
        belief.assumed_nullable is not None
        and belief.assumed_nullable is False
        and field.nullable is True
    ):
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

    # CONSTRAINT_UNKNOWN_TO_CONSUMER is intentionally NOT detected here.
    # Rule-based detection has no positive code evidence — "consumer didn't
    # pattern-match a constraint" is not the same as "consumer violates it".
    # This kind is only emitted by the LLM paths (cross_repo_graph_builder,
    # llm_disagreement_detector) which have real usage snippets to reason over.

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
```

- [ ] **Step 3: Run the tests**

```bash
cd /Users/subbikchak/Desktop/Hackathon/ai-works-hackathon
python -m pytest tests/test_disagreement_detector.py -v
```

Expected: All tests PASS. If any fail, check:
- `test_unit_mismatch_still_detected` — SemanticProfile must have `unit="pence"` and belief `assumed_unit="pounds"`, those strings must fail `_units_compatible`
- `test_type_changed_still_detected` — `boolean` vs `integer`, `_types_compatible("boolean", "integer")` must return False

- [ ] **Step 4: Commit**

```bash
cd /Users/subbikchak/Desktop/Hackathon/ai-works-hackathon
git add tests/test_disagreement_detector.py ripple/rib/enricher/disagreement_detector.py
git commit -m "fix: remove false-positive CONSTRAINT_UNKNOWN_TO_CONSUMER from rule-based detection; tighten NULLABLE_CHANGED to dangerous direction only"
```

---

### Task 3: Update Claude batch prompt — tighten CONSTRAINT_UNKNOWN_TO_CONSUMER instruction

**Files:**
- Modify: `ripple/activities/indexing/cross_repo_graph_builder.py`

The Claude prompt currently lists `CONSTRAINT_UNKNOWN_TO_CONSUMER` as a valid kind in the disagreements schema but gives no guidance on when NOT to use it. Claude can over-emit it on initial ingest just as the rule-based path did. Add a focused rule to the `Analysis rules:` section.

- [ ] **Step 1: Locate the analysis rules block in the prompt**

In `ripple/activities/indexing/cross_repo_graph_builder.py`, find the `Analysis rules:` section near the bottom of `user_prompt`. It currently ends with:

```python
- Only emit disagreements when there is a real conflict — not every field needs one"""
```

- [ ] **Step 2: Add the CONSTRAINT_UNKNOWN_TO_CONSUMER rule and inferred_constraints guidance**

Replace the last two lines of the `user_prompt` string:

```python
- Only emit disagreements when there is a real conflict — not every field needs one"""
```

With:

```python
- Only emit disagreements when there is a real conflict — not every field needs one
- CONSTRAINT_UNKNOWN_TO_CONSUMER: ONLY emit when consumer code shows an operation that CONFLICTS with the constraint — e.g. arithmetic producing values outside a declared minimum/maximum, comparison against a value outside an enum range, or dividing a field declared as already-normalised. Do NOT emit simply because the consumer doesn't explicitly validate the constraint. Absence of a validation check is not a disagreement.
- inferred_constraints in consumer_beliefs: populate with constraint-related behaviour you observe in the code (e.g. "non_negative" if consumer guards against negatives, "precision_2dp" if consumer calls toFixed(2), "enum_membership" if consumer compares against specific string values). Leave as [] only if the consumer code shows no constraint-sensitive behaviour."""
```

- [ ] **Step 3: Verify the file is syntactically valid**

```bash
cd /Users/subbikchak/Desktop/Hackathon/ai-works-hackathon
python -c "from ripple.activities.indexing.cross_repo_graph_builder import cross_repo_graph_builder_activity; print('OK')"
```

Expected output: `OK`

- [ ] **Step 4: Run all tests to confirm nothing regressed**

```bash
cd /Users/subbikchak/Desktop/Hackathon/ai-works-hackathon
python -m pytest tests/ -v
```

Expected: All tests pass (the new ones from Task 1 + the existing `test_scip_runner.py` tests).

- [ ] **Step 5: Commit**

```bash
cd /Users/subbikchak/Desktop/Hackathon/ai-works-hackathon
git add ripple/activities/indexing/cross_repo_graph_builder.py
git commit -m "fix: require code evidence for CONSTRAINT_UNKNOWN_TO_CONSUMER in Claude batch prompt; populate inferred_constraints from observed behaviour"
```

---

### Task 4: Verify end-to-end — re-ingest and confirm disagreement count drops

- [ ] **Step 1: Flush the database to start clean**

```bash
curl -s -X POST http://localhost:8081/api/flush | python3 -m json.tool
```

Expected:
```json
{"status": "flushed", "message": "All Ripple data cleared — ready for re-ingest"}
```

- [ ] **Step 2: Trigger a fresh ingest via the dashboard or API**

If the dashboard is running, click "Re-ingest" / submit the ingest form. Or via API:

```bash
curl -s -X POST http://localhost:8081/ingest-pipeline \
  -H "Content-Type: application/json" \
  -d @- << 'EOF'
{
  "tenant_id": "default",
  "services": [
    {"repo_url": "https://github.com/subbikcha/user-service",        "service_name": "user-service",        "roles": ["producer", "consumer"], "openapi_path": "openapi.yaml"},
    {"repo_url": "https://github.com/subbikcha/QuickBite",           "service_name": "quickbite",           "roles": ["producer", "consumer"], "openapi_path": "openapi.yaml"},
    {"repo_url": "https://github.com/subbikcha/order-service",       "service_name": "order-service",       "roles": ["producer", "consumer"], "openapi_path": "openapi.yaml"},
    {"repo_url": "https://github.com/subbikcha/recommendation-service","service_name": "recommendation-service","roles": ["producer", "consumer"], "openapi_path": "openapi.yaml"}
  ]
}
EOF
```

- [ ] **Step 3: Wait for ingestion to complete (~30–60s), then query disagreements**

```bash
curl -s http://localhost:8081/disagreements | python3 -c "
import json, sys
items = json.load(sys.stdin)
from collections import Counter
kinds = Counter(d['kind'] for d in items)
print(f'Total: {len(items)}')
for k, v in kinds.most_common():
    print(f'  {k}: {v}')
"
```

Expected: `CONSTRAINT_UNKNOWN_TO_CONSUMER` count is **0**. Total should be well under 84 — only genuine structural conflicts.

- [ ] **Step 4: Confirm dashboard reflects the correct count**

Open the dashboard at `http://localhost:3000`. The stats row should show a disagreement count that matches the API response above, and the "AUTO-FIXING" card should not be flooded with constraint disagreements.
