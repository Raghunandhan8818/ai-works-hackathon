from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ripple.rib.graph.schema import ConsumerBelief, FieldUsage, SymbolNode
from ripple.rib.indexer.field_finder import is_test_file as _is_test_file
from ripple.rib.indexer.scip_cli import export_scip_json, find_scip_cli
from ripple.rib.indexer.symbol_linker import build_field_index, link_symbol_to_field

logger = logging.getLogger(__name__)

_TS_NULLABLE_MARKERS = {"null", "undefined", "null |", "| null", "| undefined", "undefined |"}
_TS_TYPE_MAP = {
    "number": "number", "string": "string", "boolean": "boolean",
    "bigint": "bigint", "any": "any", "unknown": "unknown",
    "null": "null", "undefined": "undefined",
}



def _read_source_context(repo_path: Path, relative_path: str, line: int, context: int = 2) -> str:
    """Return `context` lines before and after `line` (1-indexed) from the source file."""
    try:
        full_path = repo_path / relative_path
        if not full_path.exists():
            return ""
        lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(0, line - 1 - context)
        end = min(len(lines), line + context)
        return "\n".join(lines[start:end])
    except Exception:
        return ""


def load_scip_index(
    scip_path: str | Path,
    service_name: str,
    field_fqns: list[str] | None = None,
    repo_path: Path | None = None,
) -> tuple[list[SymbolNode], list[FieldUsage]]:
    path = Path(scip_path)
    if not path.exists():
        logger.warning("scip load missing file=%s service=%s", scip_path, service_name)
        return [], []

    payload = _read_scip_json(path)
    if not payload:
        logger.warning(
            "scip load empty payload service=%s path=%s scip_cli=%s",
            service_name,
            path,
            find_scip_cli(),
        )
        return [], []

    logger.info(
        "scip load service=%s path=%s field_fqns=%s",
        service_name,
        path,
        len(field_fqns or []),
    )
    documents = payload.get("documents") or []
    symbols: list[SymbolNode] = []
    usages: list[FieldUsage] = []

    # Build the leaf-name index once for all documents.
    field_index = build_field_index(field_fqns or [])

    for document in documents:
        relative_path = document.get("relativePath") or ""

        # ── Pass 1: collect SymbolNodes (all occurrences) ──────────────────
        for occurrence in document.get("occurrences") or []:
            symbol_id = occurrence.get("symbol") or ""
            if not symbol_id:
                continue
            roles = occurrence.get("symbolRoles") or 0
            line = _line_from_range(occurrence.get("range") or [])
            display_name = _display_name(symbol_id)
            kind = _symbol_kind(roles)
            symbols.append(
                SymbolNode(
                    scip_id=symbol_id,
                    display_name=display_name,
                    kind=kind,
                    service_name=service_name,
                    file_path=relative_path,
                    line=line,
                )
            )

        # ── Pass 2: link occurrences → FieldUsage via symbol_linker ────────
        for occurrence in document.get("occurrences") or []:
            symbol_id = occurrence.get("symbol") or ""
            if not symbol_id:
                continue

            matched_fqn = link_symbol_to_field(symbol_id, field_index, context_hint=relative_path)
            if not matched_fqn:
                continue

            line = _line_from_range(occurrence.get("range") or [])
            # expression: the leaf identifier the consumer uses in its own code
            expression = _display_name(symbol_id)
            # surrounding_context: full SCIP symbol for downstream belief heuristics
            surrounding_context = symbol_id

            is_test = _is_test_file(relative_path)
            src_ctx = (
                _read_source_context(repo_path, relative_path, line)
                if repo_path is not None else ""
            )
            usages.append(
                FieldUsage(
                    field_fqn=matched_fqn,
                    consumer_service=service_name,
                    file_path=relative_path,
                    line=line,
                    expression=expression,
                    surrounding_context=surrounding_context,
                    scip_symbol_id=symbol_id,
                    is_test=is_test,
                    source_context=src_ctx,
                )
            )

    logger.info(
        "scip load done service=%s symbols=%s usages=%s",
        service_name,
        len(symbols),
        len(usages),
    )
    return symbols, usages


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _read_scip_json(path: Path) -> dict[str, Any]:
    if path.suffix == ".json":
        return json.loads(path.read_text())

    json_path = path.parent / "index.json"
    if json_path.exists():
        return json.loads(json_path.read_text())

    exported = export_scip_json(path)
    if exported:
        return json.loads(exported.read_text())

    return {}


def _line_from_range(range_values: list[int]) -> int:
    if len(range_values) >= 1:
        return int(range_values[0]) + 1
    return 0


def _display_name(symbol_id: str) -> str:
    """Return the human-readable leaf part of a SCIP symbol ID."""
    return symbol_id.split(" ").pop() if " " in symbol_id else symbol_id


def _symbol_kind(roles: int) -> str:
    if roles & 1:
        return "definition"
    if roles & 2:
        return "reference"
    return "occurrence"


def extract_ts_interface_beliefs(
    scip_path: str | Path,
    consumer_service: str,
    field_fqns: list[str],
) -> list[ConsumerBelief]:
    """
    Parse a scip-typescript index and extract ConsumerBelief signals from
    TypeScript interface/type definitions that reference producer field names.
    """
    path = Path(scip_path)
    payload = _read_scip_json(path)
    if not payload:
        return []

    field_index = build_field_index(field_fqns)

    sig_docs: dict[str, str] = {}
    for sym in payload.get("symbols") or []:
        sid = sym.get("symbol") or ""
        docs = sym.get("documentation") or []
        if sid and docs:
            sig_docs[sid] = "\n".join(str(d) for d in docs)

    now = datetime.now(timezone.utc)
    beliefs: list[ConsumerBelief] = []
    seen: set[str] = set()

    for document in payload.get("documents") or []:
        rel_path = document.get("relativePath") or document.get("relative_path") or ""
        if not rel_path.endswith((".ts", ".tsx")):
            continue

        for occurrence in document.get("occurrences") or []:
            roles = occurrence.get("symbolRoles") or occurrence.get("symbol_roles") or 0
            if not (roles & 1):
                continue
            symbol_id = occurrence.get("symbol") or ""
            if not symbol_id:
                continue
            matched_fqn = link_symbol_to_field(symbol_id, field_index)
            if not matched_fqn:
                continue
            dedup_key = f"{matched_fqn}::{rel_path}"
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            sig_doc = sig_docs.get(symbol_id, "")
            assumed_type, assumed_nullable = _parse_ts_signature(sig_doc)

            beliefs.append(ConsumerBelief(
                consumer_service=consumer_service,
                field_fqn=matched_fqn,
                assumed_type=assumed_type,
                assumed_nullable=assumed_nullable,
                assumed_unit=None,
                assumed_format=_infer_format_from_type(assumed_type, sig_doc),
                inferred_constraints=[],
                usage_expressions=[sig_doc[:120]] if sig_doc else [],
                confidence=0.85,
                extracted_at=now,
                source_file_hash="scip-ts",
            ))

    logger.info(
        "extract_ts_interface_beliefs service=%s beliefs=%d", consumer_service, len(beliefs)
    )
    return beliefs


def _parse_ts_signature(sig_doc: str) -> tuple[str | None, bool | None]:
    if not sig_doc:
        return None, None
    import re
    sig = re.sub(r"^\(property\)\s+\S+:\s*", "", sig_doc.strip())
    sig = re.sub(r"^\(method\)\s+\S+\(.*?\):\s*", "", sig)
    nullable = any(marker in sig for marker in _TS_NULLABLE_MARKERS)
    parts = [p.strip() for p in sig.split("|")]
    core_parts = [p for p in parts if p not in ("null", "undefined", "")]
    core_type = " | ".join(core_parts) if core_parts else sig.strip()
    assumed_type = _TS_TYPE_MAP.get(core_type.lower(), core_type[:80] if core_type else None)
    return assumed_type or None, nullable if nullable is not None else None


def _infer_format_from_type(assumed_type: str | None, sig_doc: str) -> str | None:
    if not assumed_type:
        return None
    t = assumed_type.lower()
    doc = sig_doc.lower()
    if t == "string":
        if any(kw in doc for kw in ("date", "iso", "timestamp", "datetime")):
            return "iso8601"
        if any(kw in doc for kw in ("uuid", "id", "guid")):
            return "uuid"
        if "url" in doc or "uri" in doc:
            return "url"
        if "email" in doc:
            return "email"
    return None
