from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from ripple.rib.graph.schema import FieldUsage, SymbolNode
from ripple.rib.indexer.scip_cli import export_scip_json, find_scip_cli
from ripple.rib.indexer.symbol_linker import build_field_index, link_symbol_to_field

logger = logging.getLogger(__name__)


def load_scip_index(
    scip_path: str | Path,
    service_name: str,
    field_fqns: list[str] | None = None,
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

            matched_fqn = link_symbol_to_field(symbol_id, field_index)
            if not matched_fqn:
                continue

            line = _line_from_range(occurrence.get("range") or [])
            # expression: the leaf identifier the consumer uses in its own code
            expression = _display_name(symbol_id)
            # surrounding_context: full SCIP symbol for downstream belief heuristics
            surrounding_context = symbol_id

            usages.append(
                FieldUsage(
                    field_fqn=matched_fqn,
                    consumer_service=service_name,
                    file_path=relative_path,
                    line=line,
                    expression=expression,
                    surrounding_context=surrounding_context,
                    scip_symbol_id=symbol_id,
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
