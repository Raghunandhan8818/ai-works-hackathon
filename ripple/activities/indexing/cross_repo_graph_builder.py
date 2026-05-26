from __future__ import annotations

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
_MAX_FIELDS_IN_PROMPT = int(os.environ.get("RIPPLE_MAX_FIELDS_PROMPT", "60"))
_MAX_USAGES_PER_FIELD = int(os.environ.get("RIPPLE_MAX_USAGES_PER_FIELD", "5"))

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

    if not all_fields:
        logger.warning("no fields from any producer OpenAPI spec — returning empty graph")
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

    field_contexts = []
    for field in all_fields[:_MAX_FIELDS_IN_PROMPT]:
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
        if any([b.assumed_type, b.assumed_unit, b.assumed_nullable is not None])
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
      "kind": "NULLABLE_CHANGED|TYPE_CHANGED|UNIT_MISMATCH|FIELD_REMOVED|NEW_REQUIRED_FIELD",
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
- ops=[divide_by_100] → consumer assumes cents/pence; producer declares dollars → UNIT_MISMATCH
- ops=[safe_navigation] or ops=[null_check] → consumer treats field as nullable
- ops=[parse_int] or ops=[cast_int] → consumer expects integer
- Only emit disagreements when there is a real conflict — not every field needs one"""

    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    try:
        response = client.messages.create(
            model=_GRAPH_MODEL,
            max_tokens=8192,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text
        logger.info("Claude API response tokens=%d", response.usage.output_tokens)
        return _parse_json_response(raw, all_fields, regex_beliefs)
    except Exception as exc:
        logger.error("Claude API call failed: %s — falling back to regex-only graph", exc)
        return _build_fallback_graph(all_fields, regex_beliefs)


def _parse_json_response(raw: str, all_fields, regex_beliefs) -> dict:
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end])
        except json.JSONDecodeError as exc:
            logger.warning("JSON parse failed: %s — snippet: %s", exc, raw[start:start + 200])
    logger.warning("no JSON found in Claude response — falling back to regex-only graph")
    return _build_fallback_graph(all_fields, regex_beliefs)


def _build_fallback_graph(all_fields, regex_beliefs) -> dict:
    return {
        "fields": [
            {
                "fqn": f.fqn,
                "name": f.name,
                "producer_service": f.producer_service,
                "transport": f.transport.value,
                "endpoint_or_topic": f.endpoint_or_topic,
                "field_path": f.field_path,
                "declared_type": f.declared_type,
                "nullable": f.nullable,
                "constraints": [{"kind": c.kind, "value": c.value} for c in f.constraints],
            }
            for f in all_fields
        ],
        "consumer_beliefs": [
            {
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
            }
            for b in regex_beliefs
        ],
        "disagreements": [],
    }
