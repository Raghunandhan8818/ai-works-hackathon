 # Fix: False-Positive Disagreements on Initial Ingest

**Date:** 2026-06-08  
**Problem:** 84 `CONSTRAINT_UNKNOWN_TO_CONSUMER` disagreements appear on initial ingest, all classified as AUTO-FIXING. These are false positives — not real contract breaks.

---

## Root Causes

### Root Cause 1 — Rule-based drift detection has no-evidence trigger

`write_graph.py:_run_drift_detection` calls `detect_disagreements` (rule-based) after every ingest. The `CONSTRAINT_UNKNOWN_TO_CONSUMER` check fires when:
- Field has any constraint that isn't `format` or `enum` (OpenAPI commonly has `minimum`, `maximum`, `pattern`, `minLength`, etc.)
- `belief.inferred_constraints == []` — which is **always** the case because the Claude batch prompt template hardcodes `"inferred_constraints": []`

Absence of observed constraint behavior ≠ a contract disagreement. The rule equates "no code evidence of constraint awareness" with "consumer disagrees with the constraint." That's a false positive by design.

**Math:** ~28 fields with non-format/enum constraints × 3 consumer services = 84 disagreements.

### Root Cause 2 — NULLABLE_CHANGED fires in the safe direction

`detect_disagreements` fires `NULLABLE_CHANGED` whenever `belief.assumed_nullable != field.nullable`, regardless of direction. This includes the safe case: consumer defensively null-checks a non-nullable field. Only the dangerous direction matters: consumer assumes non-null but producer declares nullable (will crash when null arrives).

---

## Design (Option A)

### Change 1: Remove CONSTRAINT_UNKNOWN_TO_CONSUMER from rule-based detection

**File:** `ripple/rib/enricher/disagreement_detector.py`

Remove the entire `unknown_constraints` block (lines 96–112). This kind of disagreement requires actual code evidence showing the consumer violates a constraint. The rule-based pass has no such evidence — it only knows a constraint exists and the consumer hasn't pattern-matched it.

`CONSTRAINT_UNKNOWN_TO_CONSUMER` remains valid and will still be emitted by:
- Claude's semantic batch in `cross_repo_graph_builder.py` (has real code evidence)
- `llm_disagreement_detector.py` (has real code evidence)

### Change 2: Tighten NULLABLE_CHANGED to dangerous direction only

**File:** `ripple/rib/enricher/disagreement_detector.py`

Current condition: `belief.assumed_nullable is not None and belief.assumed_nullable != field.nullable`

New condition: only fire when `belief.assumed_nullable == False` AND `field.nullable == True`  
(consumer assumes the value is always present, but producer can send null — will crash)

The reverse (consumer is defensively null-checking a required field) is harmless and should not create a disagreement.

### Change 3: Tighten Claude's CONSTRAINT_UNKNOWN_TO_CONSUMER instruction

**File:** `ripple/activities/indexing/cross_repo_graph_builder.py`

Update the analysis rules in the Claude prompt to explicitly say: only emit `CONSTRAINT_UNKNOWN_TO_CONSUMER` when there is clear code evidence that the consumer performs operations CONFLICTING with the constraint (e.g., arithmetic that produces values violating a range constraint, comparison against a value outside allowed range). Do not emit it simply because the consumer doesn't explicitly check the constraint.

---

## What Does NOT Change

- `UNIT_MISMATCH`, `TYPE_CHANGED`, `FORMAT_MISMATCH` — these stay in rule-based detection unchanged (structural, deterministic, no evidence ambiguity)
- The LLM path (`cross_repo_graph_builder.py`, `llm_disagreement_detector.py`) continues to emit all disagreement kinds including `CONSTRAINT_UNKNOWN_TO_CONSUMER` when evidence supports it
- `_run_drift_detection` continues to run after every ingest — it just won't produce false positives for constraint absence

---

## Expected Outcome

After these changes:
- Initial ingest produces 0 `CONSTRAINT_UNKNOWN_TO_CONSUMER` disagreements from rule-based drift detection
- Real CONSTRAINT_UNKNOWN_TO_CONSUMER disagreements (where Claude has code evidence) still surface
- NULLABLE_CHANGED only flags genuinely dangerous null assumptions
- The dashboard disagreement count reflects actual contract breaks, not detection noise
- The AUTO-FIXING queue doesn't attempt to "fix" non-existent issues

---

## Files Changed

| File | Change |
|---|---|
| `ripple/rib/enricher/disagreement_detector.py` | Remove CONSTRAINT_UNKNOWN_TO_CONSUMER block; tighten NULLABLE_CHANGED direction |
| `ripple/activities/indexing/cross_repo_graph_builder.py` | Add explicit CONSTRAINT_UNKNOWN_TO_CONSUMER evidence requirement to Claude prompt |
