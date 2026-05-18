from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

from ripple.rib.enricher.belief_enricher import enrich_belief
from ripple.rib.enricher.disagreement_detector import detect_disagreements
from ripple.rib.enricher.field_profiler import profile_field
from ripple.rib.graph.schema import FieldNode
from ripple.rib.graph.store import RippleStore
from ripple.rib.indexer.belief_extractor import extract_beliefs_from_usages
from ripple.rib.indexer.contract_parsers.openapi_parser import parse_openapi
from ripple.rib.indexer.git_analyzer import analyze_field_history
from ripple.rib.indexer.scip_cli import resolve_readable_index
from ripple.rib.indexer.scip_loader import load_scip_index
from ripple.rib.indexer.scip_runner import ensure_scip_index


def find_scip_index(repo_path: Path) -> Path | None:
    return resolve_readable_index(repo_path)


def prepare_scip(
    repo_path: Path, service_name: str, store: RippleStore
) -> dict[str, str | bool]:
    result = ensure_scip_index(repo_path, service_name, store)
    logger.info("prepare_scip service=%s result=%s", service_name, result)
    return result


def index_producer(
    repo_path: Path,
    service_name: str,
    openapi_path: str,
    store: RippleStore,
) -> dict[str, int]:
    counts = {"fields": 0, "history_signals": 0, "profiles": 0, "symbols": 0}
    spec_file = repo_path / openapi_path
    logger.info(
        "index_producer start service=%s openapi=%s repo=%s",
        service_name,
        spec_file,
        repo_path,
    )
    if not spec_file.exists():
        logger.warning("index_producer openapi missing service=%s path=%s", service_name, spec_file)
        return counts

    fields = parse_openapi(spec_file, service_name)
    for field in fields:
        store.upsert_field(field)
    counts["fields"] = len(fields)

    for field in fields:
        for signal in analyze_field_history(repo_path, field.name, field.fqn):
            store.upsert_history_signal(signal)
            counts["history_signals"] += 1

    for field in fields:
        history = store.get_history_signals(field.fqn)
        profile = profile_field(field, history)
        store.upsert_semantic_profile(profile)
        counts["profiles"] += 1

    field_fqns = [f.fqn for f in fields]
    scip_file = find_scip_index(repo_path)
    if scip_file:
        symbols, _ = load_scip_index(scip_file, service_name, field_fqns)
        for symbol in symbols:
            store.upsert_symbol(symbol)
        counts["symbols"] = len(symbols)

    logger.info("index_producer done service=%s counts=%s", service_name, counts)
    return counts


def index_consumer(repo_path: Path, service_name: str, store: RippleStore) -> dict[str, int]:
    counts = {"usages": 0, "beliefs": 0, "disagreements": 0}
    field_fqns = [f.fqn for f in store.get_all_fields()]
    logger.info(
        "index_consumer start service=%s repo=%s known_fields=%s",
        service_name,
        repo_path,
        len(field_fqns),
    )
    scip_file = find_scip_index(repo_path)
    usages = []
    if scip_file:
        logger.info("index_consumer scip file=%s", scip_file)
        _, usages = load_scip_index(scip_file, service_name, field_fqns)
        for usage in usages:
            store.upsert_usage(usage)
        counts["usages"] = len(usages)
    else:
        logger.warning("index_consumer no scip index service=%s repo=%s", service_name, repo_path)

    beliefs = extract_beliefs_from_usages(usages)
    for belief in beliefs:
        field = store.get_field(belief.field_fqn)
        if field is None:
            continue
        enriched = enrich_belief(belief, field)
        store.upsert_consumer_belief(enriched)
        counts["beliefs"] += 1
        profile = store.get_semantic_profile(belief.field_fqn)
        for disagreement in detect_disagreements(field, profile, enriched):
            store.upsert_disagreement(disagreement)
            counts["disagreements"] += 1

    logger.info("index_consumer done service=%s counts=%s", service_name, counts)
    return counts
