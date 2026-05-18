from __future__ import annotations

import time
from pathlib import Path

from ripple.rib.enricher.belief_enricher import enrich_belief
from ripple.rib.enricher.disagreement_detector import detect_disagreements
from ripple.rib.enricher.field_profiler import profile_field
from ripple.rib.graph.schema import IngestionRequest, IngestionResult
from ripple.rib.graph.store import RippleStore
from ripple.rib.indexer.belief_extractor import extract_beliefs_from_usages
from ripple.rib.indexer.cloner import cleanup_clone, clone_repo, service_name_from_url
from ripple.rib.indexer.contract_parsers.openapi_parser import parse_openapi
from ripple.rib.indexer.git_analyzer import analyze_field_history
from ripple.rib.indexer.scip_loader import load_scip_index


def run_ingestion(request: IngestionRequest, store: RippleStore) -> IngestionResult:
    started = time.perf_counter()
    services_indexed: list[str] = []
    fields_extracted = 0
    usages_found = 0
    beliefs_extracted = 0
    disagreements_detected = 0
    llm_profiles_generated = 0

    producer_path = clone_repo(request.producer_repo_url)
    producer_service = service_name_from_url(request.producer_repo_url)
    services_indexed.append(producer_service)

    try:
        openapi_file = Path(producer_path) / request.openapi_path
        if openapi_file.exists():
            fields = parse_openapi(openapi_file, producer_service)
            for field in fields:
                store.upsert_field(field)
            fields_extracted += len(fields)

            for field in fields:
                history = analyze_field_history(
                    producer_path, field.name, field.fqn
                )
                for signal in history:
                    store.upsert_history_signal(signal)

            for field in fields:
                history = store.get_history_signals(field.fqn)
                profile = profile_field(field, history)
                store.upsert_semantic_profile(profile)
                llm_profiles_generated += 1

        field_fqns = [f.fqn for f in store.get_fields_for_service(producer_service)]
        scip_file = _find_scip_index(producer_path)
        if scip_file:
            symbols, _ = load_scip_index(scip_file, producer_service, field_fqns)
            for symbol in symbols:
                store.upsert_symbol(symbol)
    finally:
        cleanup_clone(producer_path)

    for consumer_url in request.consumer_repo_urls:
        consumer_path = clone_repo(consumer_url)
        consumer_service = service_name_from_url(consumer_url)
        services_indexed.append(consumer_service)
        try:
            field_fqns = [f.fqn for f in store.get_all_fields()]
            scip_file = _find_scip_index(consumer_path)
            usages = []
            if scip_file:
                _, usages = load_scip_index(scip_file, consumer_service, field_fqns)
                for usage in usages:
                    store.upsert_usage(usage)
                usages_found += len(usages)

            beliefs = extract_beliefs_from_usages(usages)
            for belief in beliefs:
                field = store.get_field(belief.field_fqn)
                if field is None:
                    continue
                enriched = enrich_belief(belief, field)
                store.upsert_consumer_belief(enriched)
                beliefs_extracted += 1

                profile = store.get_semantic_profile(belief.field_fqn)
                for disagreement in detect_disagreements(field, profile, enriched):
                    store.upsert_disagreement(disagreement)
                    disagreements_detected += 1
        finally:
            cleanup_clone(consumer_path)

    duration = time.perf_counter() - started
    return IngestionResult(
        services_indexed=services_indexed,
        fields_extracted=fields_extracted,
        usages_found=usages_found,
        beliefs_extracted=beliefs_extracted,
        disagreements_detected=disagreements_detected,
        llm_profiles_generated=llm_profiles_generated,
        duration_seconds=duration,
    )


def _find_scip_index(repo_path: Path) -> Path | None:
    candidates = [
        repo_path / "index.scip",
        repo_path / "index.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    for match in repo_path.rglob("index.scip"):
        return match
    return None
