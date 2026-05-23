from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from ripple.rib.enricher.belief_enricher import enrich_belief
from ripple.rib.enricher.business_context_builder import build_business_context_async
from ripple.rib.enricher.disagreement_detector import detect_disagreements
from ripple.rib.enricher.drift_detector import detect_drift_async
from ripple.rib.enricher.field_profiler import profile_field_async
from ripple.rib.graph.schema import FieldNode, FieldUsage, ServiceRecord
from ripple.rib.graph.store import RippleStore
from ripple.rib.indexer.belief_extractor import extract_beliefs_from_usages
from ripple.rib.indexer.code_indexer import index_repo as index_code
from ripple.rib.indexer.contract_parsers.openapi_parser import parse_openapi
from ripple.rib.indexer.field_finder import find_field_usages
from ripple.rib.indexer.git_analyzer import analyze_field_history
from ripple.rib.indexer.scip_cli import resolve_readable_index
from ripple.rib.indexer.scip_loader import extract_ts_interface_beliefs, load_scip_index
from ripple.rib.indexer.scip_runner import RepoLanguage, detect_language, ensure_scip_index

# Max concurrent Haiku calls — keeps us under rate limits while still parallelising
_LLM_CONCURRENCY = 20


def find_scip_index(repo_path: Path) -> Path | None:
    return resolve_readable_index(repo_path)


def prepare_scip(
    repo_path: Path, service_name: str, store: RippleStore
) -> dict[str, str | bool]:
    result = ensure_scip_index(repo_path, service_name, store)
    logger.info("prepare_scip service=%s result=%s", service_name, result)
    return result


async def index_producer(
    repo_path: Path,
    service_name: str,
    openapi_path: str,
    store: RippleStore,
) -> dict[str, int]:
    counts = {
        "fields": 0, "history_signals": 0, "profiles": 0,
        "symbols": 0, "classes": 0, "methods": 0,
        "test_evidences": 0, "business_contexts": 0,
    }

    spec_file = repo_path / openapi_path
    logger.info("index_producer start service=%s openapi=%s", service_name, spec_file)

    if not spec_file.exists():
        logger.warning("index_producer openapi missing service=%s path=%s", service_name, spec_file)
        return counts

    # ── OpenAPI fields ──
    fields = parse_openapi(spec_file, service_name)
    for field in fields:
        store.upsert_field(field)
    counts["fields"] = len(fields)

    # ── Git history ──
    for field in fields:
        for signal in analyze_field_history(repo_path, field.name, field.fqn):
            store.upsert_history_signal(signal)
            counts["history_signals"] += 1

    # ── AST — classes and methods with docstrings ──
    classes, methods = index_code(repo_path, service_name)
    for cls in classes:
        store.upsert_code_class(cls)
    for method in methods:
        store.upsert_code_method(method)
    counts["classes"] = len(classes)
    counts["methods"] = len(methods)

    # ── Test evidence from producer tests ──
    from ripple.rib.indexer.test_extractor import extract_test_evidences
    test_evidences = extract_test_evidences(repo_path, fields, service_name)
    for evidence in test_evidences:
        store.upsert_test_evidence(evidence)
    counts["test_evidences"] = len(test_evidences)

    # ── Semantic profiles — all fields in parallel ──
    logger.info("index_producer profiling %d fields in parallel service=%s", len(fields), service_name)
    all_history = {f.fqn: store.get_history_signals(f.fqn) for f in fields}
    profiles = await _gather_limited([
        profile_field_async(f, all_history[f.fqn])
        for f in fields
    ])
    for profile in profiles:
        store.upsert_semantic_profile(profile)
    counts["profiles"] = len(profiles)
    logger.info("index_producer profiles done service=%s", service_name)

    # ── Business context — first pass (producer evidence only), all fields in parallel ──
    await _rebuild_business_contexts_async(service_name, fields, store, counts)

    # ── SCIP symbols (non-blocking, backward compat) ──
    field_fqns = [f.fqn for f in fields]
    scip_file = find_scip_index(repo_path)
    if scip_file:
        try:
            symbols, _ = load_scip_index(scip_file, service_name, field_fqns)
            for symbol in symbols:
                store.upsert_symbol(symbol)
            counts["symbols"] = len(symbols)
        except Exception as e:
            logger.warning("index_producer scip load failed service=%s err=%s", service_name, e)

    # ── Register service record ──
    store.upsert_service(ServiceRecord(
        name=service_name,
        repo_url=_git_remote_url(repo_path),
        language=detect_language(repo_path).value,
        last_indexed_at=_now(),
    ))

    logger.info("index_producer done service=%s counts=%s", service_name, counts)
    return counts


async def index_consumer(
    repo_path: Path,
    service_name: str,
    store: RippleStore,
) -> dict[str, int]:
    counts = {
        "usages": 0, "scip_usages": 0, "grep_usages": 0,
        "beliefs": 0, "ts_interface_beliefs": 0,
        "disagreements": 0, "test_evidences": 0,
    }

    all_fields = store.get_all_fields()
    logger.info(
        "index_consumer start service=%s repo=%s known_fields=%d",
        service_name, repo_path, len(all_fields),
    )

    # ── Detect language — determines whether scip-typescript runs ──
    language = detect_language(repo_path)
    is_ts = language == RepoLanguage.TYPESCRIPT
    logger.info("index_consumer language=%s service=%s", language.value, service_name)

    # ── SCIP path for TypeScript / React / JS repos ──
    scip_usages_by_field: dict[str, list[FieldUsage]] = {}
    if is_ts:
        scip_result = ensure_scip_index(repo_path, service_name, store)
        if scip_result.get("scip_path"):
            scip_index = resolve_readable_index(repo_path)
            if scip_index:
                field_fqns = [f.fqn for f in all_fields]
                _, ts_usages = load_scip_index(scip_index, service_name, field_fqns)
                for u in ts_usages:
                    scip_usages_by_field.setdefault(u.field_fqn, []).append(u)
                counts["scip_usages"] = len(ts_usages)
                logger.info(
                    "index_consumer scip_usages=%d service=%s", len(ts_usages), service_name
                )

                # TypeScript interface belief extraction
                ts_beliefs = extract_ts_interface_beliefs(scip_index, service_name, field_fqns)
                for belief in ts_beliefs:
                    field = store.get_field(belief.field_fqn)
                    if field is None:
                        continue
                    enriched = enrich_belief(belief, field)
                    store.upsert_consumer_belief(enriched)
                    counts["ts_interface_beliefs"] += 1
        else:
            logger.warning(
                "index_consumer scip-typescript failed service=%s — falling back to grep",
                service_name,
            )

    # ── Multi-strategy grep + tree-sitter (all languages) ──
    all_usages: list[FieldUsage] = []
    for field in all_fields:
        grep_hits = find_field_usages(
            repo_path=repo_path,
            field_name=field.name,
            field_fqn=field.fqn,
            consumer_service=service_name,
        )
        scip_hits = scip_usages_by_field.get(field.fqn, [])
        merged = _merge_usages(scip_hits, grep_hits)
        counts["grep_usages"] += len(grep_hits)

        for usage in merged:
            store.upsert_usage(usage)
        all_usages.extend(merged)

    counts["usages"] = len(all_usages)

    # ── Test evidence from consumer tests ──
    from ripple.rib.indexer.test_extractor import extract_test_evidences
    test_evidences = extract_test_evidences(repo_path, all_fields, service_name)
    for evidence in test_evidences:
        store.upsert_test_evidence(evidence)
    counts["test_evidences"] = len(test_evidences)

    # ── Belief extraction + enrichment + rules-based disagreement detection ──
    beliefs = extract_beliefs_from_usages(all_usages)
    for belief in beliefs:
        field = store.get_field(belief.field_fqn)
        if field is None:
            continue
        enriched = enrich_belief(belief, field)
        store.upsert_consumer_belief(enriched)
        counts["beliefs"] += 1

        profile = store.get_semantic_profile(belief.field_fqn)
        for d in detect_disagreements(field, profile, enriched):
            store.upsert_disagreement(d)
            counts["disagreements"] += 1

    # ── Rebuild business contexts with consumer evidence — all producer services in parallel ──
    producer_services = {f.producer_service for f in all_fields}
    bc_counts: dict[str, int] = {}
    for producer_svc in producer_services:
        producer_fields = store.get_fields_for_service(producer_svc)
        await _rebuild_business_contexts_async(producer_svc, producer_fields, store, bc_counts)
    counts["business_contexts_rebuilt"] = bc_counts.get("business_contexts", 0)

    # ── Register service record ──
    store.upsert_service(ServiceRecord(
        name=service_name,
        repo_url=_git_remote_url(repo_path),
        language=language.value,
        last_indexed_at=_now(),
    ))

    logger.info("index_consumer done service=%s counts=%s", service_name, counts)
    return counts


# ── Async helpers ─────────────────────────────────────────────────────────────

async def _gather_limited(coros: list, limit: int = _LLM_CONCURRENCY) -> list:
    """Run coroutines with a concurrency cap to avoid rate limit bursts."""
    sem = asyncio.Semaphore(limit)

    async def _wrap(coro):
        async with sem:
            return await coro

    return list(await asyncio.gather(*[_wrap(c) for c in coros]))


async def _rebuild_business_contexts_async(
    service_name: str,
    fields: list,
    store: RippleStore,
    counts: dict,
) -> None:
    all_classes = store.get_code_classes_for_service(service_name)
    all_methods = store.get_code_methods_for_service(service_name)

    # Step 1: collect all evidence synchronously (DB reads)
    field_evidence = []
    for field in fields:
        history = store.get_history_signals(field.fqn)
        profile = store.get_semantic_profile(field.fqn)
        test_ev = store.get_test_evidences_for_field(field.fqn)
        consumer_usages = store.get_usages_for_field(field.fqn)
        relevant_methods = _filter_relevant_methods(all_methods, field)
        relevant_classes = _filter_relevant_classes(all_classes, field)
        previous_ctx = store.get_business_context(field.fqn)
        field_evidence.append((
            field, profile, history, relevant_classes,
            relevant_methods, consumer_usages, test_ev, previous_ctx,
        ))

    if not field_evidence:
        return

    logger.info(
        "business_contexts building %d in parallel service=%s",
        len(field_evidence), service_name,
    )

    # Step 2: build all business contexts in parallel
    contexts = await _gather_limited([
        build_business_context_async(
            field=fe[0], semantic_profile=fe[1], history_signals=fe[2],
            producer_classes=fe[3], producer_methods=fe[4],
            consumer_usages=fe[5], test_evidences=fe[6],
        )
        for fe in field_evidence
    ])

    # Step 3: detect drift in parallel (no-ops on first ingest)
    drift_results = await _gather_limited([
        detect_drift_async(fe[0].fqn, fe[7], ctx)
        for fe, ctx in zip(field_evidence, contexts)
    ])

    # Step 4: persist results
    n = 0
    drift_count = 0
    for ctx, drift in zip(contexts, drift_results):
        if drift:
            store.upsert_drift_event(drift)
            drift_count += 1
            logger.warning(
                "SEMANTIC DRIFT field=%s severity=%s breaking=%s: %s",
                ctx.field_fqn, drift.severity.value, drift.is_breaking, drift.drift_explanation,
            )
        store.upsert_business_context(ctx)
        n += 1

    counts["business_contexts"] = counts.get("business_contexts", 0) + n
    counts["drift_events"] = counts.get("drift_events", 0) + drift_count
    logger.info(
        "business_contexts done service=%s built=%d drifts=%d",
        service_name, n, drift_count,
    )


# ── Sync helpers ──────────────────────────────────────────────────────────────

def _merge_usages(
    scip_hits: list[FieldUsage],
    grep_hits: list[FieldUsage],
) -> list[FieldUsage]:
    if not scip_hits:
        return grep_hits
    if not grep_hits:
        return scip_hits

    scip_covered: set[tuple[str, int]] = set()
    for u in scip_hits:
        for delta in range(-3, 4):
            scip_covered.add((u.file_path, u.line + delta))

    merged = list(scip_hits)
    for u in grep_hits:
        if (u.file_path, u.line) not in scip_covered:
            merged.append(u)
    return merged


def _filter_relevant_methods(methods: list, field: "FieldNode") -> list:
    from ripple.rib.indexer.field_finder import field_name_variants
    variants = {v.lower() for v in field_name_variants(field.name)}
    relevant = []
    for m in methods:
        name_lower = m.method_name.lower()
        doc_lower = (m.docstring or "").lower()
        sig_lower = m.signature.lower()
        if any(v in name_lower or v in doc_lower or v in sig_lower for v in variants):
            relevant.append(m)
    return relevant[:10]


def _filter_relevant_classes(classes: list, field: "FieldNode") -> list:
    from ripple.rib.indexer.field_finder import field_name_variants
    variants = {v.lower() for v in field_name_variants(field.name)}
    endpoint_tokens = {
        t.lower() for t in field.endpoint_or_topic.replace("/", " ").replace("-", " ").split()
        if len(t) > 2
    }
    keywords = variants | endpoint_tokens
    relevant = []
    for c in classes:
        name_lower = c.class_name.lower()
        doc_lower = (c.docstring or "").lower()
        if any(kw in name_lower or kw in doc_lower for kw in keywords):
            relevant.append(c)
    return relevant[:5]


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def _git_remote_url(repo_path: Path) -> str:
    import subprocess
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except Exception:
        return ""
