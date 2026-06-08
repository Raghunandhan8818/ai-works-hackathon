from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import anthropic
from temporalio import activity

from ripple.rib.graph.factory import get_store
from ripple.rib.indexer.belief_extractor import extract_beliefs_from_usages
from ripple.rib.indexer.contract_parsers.openapi_parser import parse_openapi
from ripple.rib.indexer.field_finder import find_field_usages

logger = logging.getLogger(__name__)

_GRAPH_MODEL = os.environ.get("RIPPLE_GRAPH_MODEL", "claude-sonnet-4-6")
_MAX_FIELDS_IN_PROMPT = int(os.environ.get("RIPPLE_MAX_FIELDS_PROMPT", "20"))
_MAX_USAGES_PER_FIELD = int(os.environ.get("RIPPLE_MAX_USAGES_PER_FIELD", "5"))
_MAX_PARALLEL_BATCHES = int(os.environ.get("RIPPLE_MAX_PARALLEL_BATCHES", "8"))

_SYSTEM_PROMPT = """\
You are a cross-repo API contract analyst for a microservice ecosystem.

You receive pre-gathered evidence:
1. Producer field contracts from OpenAPI specs — the DECLARED truth
2. Consumer code usages found by static grep — what consumers actually DO
3. Regex-inferred belief hints — pattern-matched starting points

Your job: produce a structured knowledge graph. Return ONLY valid JSON, no markdown, no preamble."""


@activity.defn(name="cross_repo_graph_builder")
async def cross_repo_graph_builder_activity(
    shared_root: str,
    index_result: dict,
    services: list[dict],
) -> dict:
    """
    Build cross-repo knowledge graph in 4 fast steps:
      1. Parse producer OpenAPI specs → FieldNodes         (~ms)
      2. grep each field across consumer repos → usages    (~1-5s)
      3. Regex patterns → initial ConsumerBeliefs          (~ms)
      4. Single Claude API call → enrich + detect diffs    (~15-30s)

    Total: ~20-40s vs the previous 10+ min Claude Code headless approach.
    """
    root = Path(shared_root)
    producers = [s for s in services if "producer" in (s.get("roles") or [])]
    consumers = [s for s in services if "consumer" in (s.get("roles") or [])]

    # ── Step 1: Parse all producer OpenAPI specs ─────────────────────────────
    all_fields = []
    for producer in producers:
        service_name = producer.get("service_name", "")
        openapi_rel = producer.get("openapi_path", "openapi.yaml")
        openapi_path = root / service_name / openapi_rel

        if not openapi_path.exists():
            # Fallback: search under the service dir
            candidates = list((root / service_name).rglob("openapi.yaml")) if (root / service_name).exists() else []
            if candidates:
                openapi_path = candidates[0]

        if openapi_path.exists():
            fields = parse_openapi(openapi_path, service_name)
            all_fields.extend(fields)
            logger.info("openapi parsed service=%s fields=%d path=%s", service_name, len(fields), openapi_path)
        else:
            logger.warning("openapi not found service=%s tried=%s", service_name, openapi_path)

    if not all_fields and consumers:
        # Consumer-only re-ingest — load producer fields already in DB
        logger.info("no producers in request, loading existing fields from DB for consumer re-index")
        try:
            all_fields = list(get_store().get_all_fields())
            logger.info("loaded %d fields from DB", len(all_fields))
        except Exception as exc:
            logger.warning("failed to load fields from DB: %s", exc)

    if not all_fields:
        logger.warning("no fields from any producer OpenAPI spec or DB — returning empty graph")
        return {"fields": [], "consumer_beliefs": [], "disagreements": []}

    # ── Step 2: Find all usages across consumer repos (grep) ─────────────────
    all_usages = []
    for consumer in consumers:
        consumer_name = consumer.get("service_name", "")
        consumer_root = root / consumer_name
        if not consumer_root.exists():
            logger.warning("consumer dir missing: %s", consumer_root)
            continue
        for field in all_fields:
            # Skip grepping a service for its own fields — it always "uses" them internally,
            # creating false consumer beliefs and self-referential disagreements.
            if field.producer_service == consumer_name:
                continue
            usages = find_field_usages(consumer_root, field.name, field.fqn, consumer_name)
            all_usages.extend(usages)

    logger.info(
        "grep complete: fields=%d consumers=%d usages=%d",
        len(all_fields), len(consumers), len(all_usages),
    )

    # ── Step 3: Regex-based belief extraction ────────────────────────────────
    regex_beliefs = extract_beliefs_from_usages(all_usages)
    logger.info("regex beliefs=%d", len(regex_beliefs))

    # ── Step 4: Single Claude API call for reasoning ──────────────────────────
    graph = await _reason_with_claude(all_fields, all_usages, regex_beliefs)

    # Merge regex-inferred beliefs so they're always stored even if Claude batches failed.
    # Claude-enriched beliefs take priority; regex fills in the rest.
    _merge_regex_beliefs(graph, regex_beliefs)

    # Write field_usages directly to DB — too large to pass through Temporal payload
    # (get_blast_radius needs these to find consumers during PR analysis)
    _write_usages_to_store(all_usages)

    logger.info(
        "cross_repo_graph_builder done fields=%d usages=%d beliefs=%d disagreements=%d",
        len(graph.get("fields", [])),
        len(all_usages),
        len(graph.get("consumer_beliefs", [])),
        len(graph.get("disagreements", [])),
    )
    return graph


def _merge_regex_beliefs(graph: dict, regex_beliefs: list) -> None:
    """Add regex-inferred beliefs that Claude didn't cover. Claude entries win on conflict."""
    existing = {
        (b.get("consumer_service"), b.get("field_fqn"))
        for b in graph.get("consumer_beliefs", [])
    }
    for b in regex_beliefs:
        if (b.consumer_service, b.field_fqn) in existing:
            continue
        if not any([b.assumed_type, b.assumed_unit, b.assumed_nullable is not None, b.assumed_format]):
            continue  # skip empty beliefs
        graph["consumer_beliefs"].append({
            "consumer_service": b.consumer_service,
            "field_fqn": b.field_fqn,
            "assumed_type": b.assumed_type,
            "assumed_nullable": b.assumed_nullable,
            "assumed_unit": b.assumed_unit,
            "assumed_format": b.assumed_format,
            "inferred_constraints": b.inferred_constraints,
            "usage_expressions": b.usage_expressions[:5],
            "confidence": b.confidence,
            "from_test": False,
            "evidence": "",
        })


def _write_usages_to_store(all_usages: list) -> None:
    if not all_usages:
        return
    try:
        store = get_store()
        written = 0
        for u in all_usages:
            try:
                store.upsert_usage(u)
                written += 1
            except Exception as exc:
                logger.warning("skip usage field=%s file=%s err=%s", u.field_fqn, u.file_path, exc)
        logger.info("field_usages written=%d", written)
    except Exception as exc:
        logger.error("_write_usages_to_store failed: %s", exc)


async def _reason_with_claude(all_fields, all_usages, regex_beliefs) -> dict:
    usage_by_fqn: dict[str, list] = {}
    for u in all_usages:
        usage_by_fqn.setdefault(u.field_fqn, []).append(u)

    # Only analyse fields that consumers actually reference — skip unreferenced fields.
    # Sort by usage count descending so the most-depended-on fields always go first.
    fields_with_usages = sorted(
        [f for f in all_fields if usage_by_fqn.get(f.fqn)],
        key=lambda f: -len(usage_by_fqn.get(f.fqn, [])),
    )
    fields_without_usages = [f for f in all_fields if not usage_by_fqn.get(f.fqn)]

    # Process in batches so no field is silently dropped due to the cap
    batches = [
        fields_with_usages[i:i + _MAX_FIELDS_IN_PROMPT]
        for i in range(0, max(len(fields_with_usages), 1), _MAX_FIELDS_IN_PROMPT)
    ]
    logger.info(
        "_reason_with_claude fields_with_usages=%d fields_without=%d batches=%d",
        len(fields_with_usages), len(fields_without_usages), len(batches),
    )

    merged: dict = {"fields": [], "consumer_beliefs": [], "disagreements": []}
    seen_fqns: set[str] = set()

    # Run batches in parallel with a concurrency cap to avoid rate limits
    sem = asyncio.Semaphore(_MAX_PARALLEL_BATCHES)

    async def _bounded(batch):
        async with sem:
            return await _call_claude_batch(batch, usage_by_fqn, regex_beliefs)

    logger.info("running %d claude batches in parallel (max_concurrent=%d)", len(batches), _MAX_PARALLEL_BATCHES)
    batch_results = await asyncio.gather(
        *[_bounded(batch) for batch in batches],
        return_exceptions=True,
    )

    for batch_idx, batch_result in enumerate(batch_results):
        if isinstance(batch_result, Exception):
            logger.error("claude batch %d failed: %s", batch_idx + 1, batch_result)
            continue

        # Merge fields (deduplicate by fqn)
        for f in batch_result.get("fields", []):
            if f.get("fqn") not in seen_fqns:
                merged["fields"].append(f)
                seen_fqns.add(f.get("fqn", ""))

        # Merge beliefs and disagreements (always append — deduplicated at DB upsert)
        merged["consumer_beliefs"].extend(batch_result.get("consumer_beliefs", []))
        merged["disagreements"].extend(batch_result.get("disagreements", []))

    # Always include ALL fields — both with and without usages — even if Claude batch failed
    for f in fields_with_usages + fields_without_usages:
        if f.fqn not in seen_fqns:
            merged["fields"].append({
                "fqn": f.fqn, "name": f.name,
                "producer_service": f.producer_service,
                "transport": f.transport.value if hasattr(f.transport, "value") else str(f.transport),
                "endpoint_or_topic": f.endpoint_or_topic,
                "field_path": f.field_path,
                "declared_type": f.declared_type,
                "nullable": f.nullable,
                "constraints": [],
            })
            seen_fqns.add(f.fqn)

    return merged


async def _call_claude_batch(batch_fields, usage_by_fqn, regex_beliefs) -> dict:
    """Single Claude API call for one batch of fields."""
    field_contexts = []
    batch_fqns = {f.fqn for f in batch_fields}

    for field in batch_fields:
        usages = usage_by_fqn.get(field.fqn, [])
        prod = [u for u in usages if not u.is_test]
        tests = [u for u in usages if u.is_test]
        top = (prod[:3] + tests[:2])[:_MAX_USAGES_PER_FIELD]

        usage_snippets = []
        for u in top:
            tag = " [TEST]" if u.is_test else ""
            ops = f" ops=[{','.join(u.operations)}]" if u.operations else ""
            var = f" var={u.local_var_name}" if u.local_var_name else ""
            ctx = "\n    ".join(u.surrounding_context.splitlines()[:6]) if u.surrounding_context else ""
            usage_snippets.append(
                f"{u.file_path}:{u.line}{tag}{ops}{var}\n"
                f"    {u.expression[:200]}"
                + (f"\n    {ctx}" if ctx else "")
            )

        field_contexts.append({
            "fqn": field.fqn,
            "name": field.name,
            "producer": field.producer_service,
            "endpoint": field.endpoint_or_topic,
            "field_path": field.field_path,
            "declared_type": field.declared_type,
            "nullable": field.nullable,
            "constraints": [f"{c.kind}={c.value}" for c in field.constraints],
            "total_usages": len(usages),
            "consumer_usages": usage_snippets,
        })

    belief_hints = [
        {
            "consumer": b.consumer_service,
            "field_fqn": b.field_fqn,
            "regex_inferred": {
                "type": b.assumed_type,
                "unit": b.assumed_unit,
                "nullable": b.assumed_nullable,
                "constraints": b.inferred_constraints,
            },
            "confidence": b.confidence,
        }
        for b in regex_beliefs
        if b.field_fqn in batch_fqns
        and any([b.assumed_type, b.assumed_unit, b.assumed_nullable is not None])
    ]

    user_prompt = f"""Analyze these API fields and their consumer code usages.

PRODUCER FIELDS WITH CONSUMER USAGES:
{json.dumps(field_contexts, indent=2)}

REGEX-INFERRED BELIEF HINTS (use as starting points, enhance with code evidence):
{json.dumps(belief_hints, indent=2) if belief_hints else "[]"}

Return ONLY this JSON (no markdown, no explanation):
{{
  "fields": [
    {{
      "fqn": "<fqn>",
      "name": "<name>",
      "producer_service": "<service>",
      "transport": "REST",
      "endpoint_or_topic": "<endpoint>",
      "field_path": "<path>",
      "declared_type": "<type>",
      "nullable": <bool>,
      "constraints": []
    }}
  ],
  "consumer_beliefs": [
    {{
      "consumer_service": "<service>",
      "field_fqn": "<fqn>",
      "assumed_type": "<type or null>",
      "assumed_nullable": <bool or null>,
      "assumed_unit": "<unit or null>",
      "assumed_format": "<format or null>",
      "inferred_constraints": [],
      "usage_expressions": ["<key expression>"],
      "confidence": <0.0-1.0>,
      "from_test": <bool>,
      "evidence": "<file:line snippet>"
    }}
  ],
  "disagreements": [
    {{
      "field_fqn": "<fqn>",
      "consumer_service": "<service>",
      "kind": "UNIT_MISMATCH|TYPE_CHANGED|NULLABLE_CHANGED|ENUM_VALUE_CHANGED|CONSTRAINT_UNKNOWN_TO_CONSUMER|FORMAT_MISMATCH|FIELD_REMOVED|NEW_REQUIRED_FIELD|ANNOTATION_CHANGE|STRUCTURE_CHANGE|BEHAVIORAL_CHANGE|SEMANTIC_INTENT_MISMATCH",
      "producer_says": "<what producer declares>",
      "consumer_assumes": "<what consumer code does>",
      "severity": "CRITICAL|HIGH|MEDIUM|LOW",
      "explanation": "<one sentence>"
    }}
  ]
}}

Analysis rules:
- Only emit consumer_beliefs for fields that have actual usages in the evidence above
- Test assertions marked [TEST] are GROUND TRUTH — weight them at confidence ≥ 0.9
- ops=[divide_by_100] → consumer assumes the value is already in base units; if producer multiplies by 100 server-side → BEHAVIORAL_CHANGE or UNIT_MISMATCH
- ops=[multiply_by_100] → consumer is converting to cents before sending; check if producer also multiplies → UNIT_MISMATCH (double-multiplication)
- ops=[safe_navigation] or ops=[null_check] → consumer is being defensively safe; do NOT flag NULLABLE_CHANGED — defensive null-checks in TypeScript/Kotlin/Swift are expected and do not indicate a contract mismatch
- NULLABLE_CHANGED should only be flagged in the dangerous direction: consumer accesses a field WITHOUT any null guard (no `?.`, no `?? fallback`, no null check) but the producer declares that field as nullable — consumer will crash when null arrives
- ops=[parse_int] or ops=[cast_int] → consumer expects integer; if producer declares float/double → TYPE_CHANGED
- ops=[compare_enum] → consumer compares enum values by string; if producer changed enum casing (e.g. MALE→male) → ENUM_VALUE_CHANGED
- Role/logic inversion (e.g. role='user' now returns different data than before) → BEHAVIORAL_CHANGE
- Field renamed on wire (e.g. jwtToken→accessToken, @JsonProperty changed) → ANNOTATION_CHANGE
- Response shape changed (e.g. role was string, now object) → STRUCTURE_CHANGE
- Only emit disagreements when there is a real conflict — not every field needs one
- camelCase vs snake_case naming differences (e.g. producer declares boost_score, consumer reads boostScore) are NOT disagreements. Most stacks have automatic serialization conversion: Java/Spring Jackson serializes camelCase by default, Python Flask/FastAPI to_dict() methods explicitly convert, and JavaScript consumers expect camelCase. Only flag ANNOTATION_CHANGE or SEMANTIC_INTENT_MISMATCH for a naming difference if you have concrete evidence in the code that the conversion is MISSING and the consumer would receive the wrong field name at runtime (e.g. consumer reads snake_case key directly from raw JSON with no conversion, or you can see the serialization config explicitly disabling conversion).
- CONSTRAINT_UNKNOWN_TO_CONSUMER: ONLY emit when consumer code shows an operation that CONFLICTS with a constraint — e.g. arithmetic producing values outside a declared minimum/maximum, or comparison against a value outside an allowed enum range. Do NOT emit simply because the consumer doesn't explicitly validate the constraint. Absence of a validation check is not a disagreement.
- inferred_constraints in consumer_beliefs: populate with constraint-sensitive behaviour you observe — e.g. "non_negative" if consumer guards against negatives, "precision_2dp" if consumer calls toFixed(2), "enum_membership" if consumer compares against specific string values. Leave as [] only when the consumer code shows no constraint-sensitive behaviour."""

    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    try:
        response = await client.messages.create(
            model=_GRAPH_MODEL,
            max_tokens=16384,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
        logger.info("claude batch response tokens=%d", response.usage.output_tokens)
        return _parse_json_response(raw)
    except Exception as exc:
        logger.error("Claude batch call failed: %s — returning empty batch result", exc)
        return {"fields": [], "consumer_beliefs": [], "disagreements": []}


def _parse_json_response(raw: str) -> dict:
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError as exc:
            logger.warning("JSON parse failed: %s — snippet: %s", exc, raw[start:start + 200])
    logger.warning("no JSON found in Claude response — returning empty batch result")
    return {"fields": [], "consumer_beliefs": [], "disagreements": []}
