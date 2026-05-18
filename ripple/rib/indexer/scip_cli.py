from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

SCIP_INDEX_NAME = "index.scip"
SCIP_JSON_NAME = "index.json"


def _is_sourcegraph_scip_cli(bin_path: str) -> bool:
    path = Path(bin_path)
    if not path.is_file():
        return False
    try:
        header = path.read_bytes()[:128]
        if header.startswith(b"#!") and b"python" in header.lower():
            logger.debug("scip skip python shim path=%s", bin_path)
            return False
    except OSError:
        return False
    try:
        result = subprocess.run(
            [str(path), "print", "--help"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False
    combined = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode == 0 and "print" in combined


def find_scip_cli() -> str | None:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(path: str | Path | None) -> None:
        if not path:
            return
        resolved = str(Path(path).resolve())
        if resolved in seen:
            return
        seen.add(resolved)
        candidates.append(resolved)

    project_bin = Path(__file__).resolve().parents[3] / ".bin" / "scip"
    if project_bin.exists():
        add(project_bin)

    for extra in (
        project_bin,
        Path.home() / "go" / "bin" / "scip",
        Path("/opt/homebrew/bin/scip"),
        Path("/usr/local/bin/scip"),
    ):
        if extra.exists():
            add(extra)

    path_env = os.environ.get("PATH", "")
    for directory in path_env.split(os.pathsep):
        add(Path(directory) / "scip")

    for candidate in candidates:
        if _is_sourcegraph_scip_cli(candidate):
            logger.info("scip CLI resolved path=%s", candidate)
            return candidate

    logger.warning(
        "sourcegraph scip CLI not found (venv may have wrong pip package named scip); "
        "run: pip uninstall scip && ./scripts/install-scip-cli.sh"
    )
    return None


def export_scip_json(index_scip: Path) -> Path | None:
    if not index_scip.exists():
        return None
    json_path = index_scip.parent / SCIP_JSON_NAME
    if json_path.exists() and json_path.stat().st_mtime >= index_scip.stat().st_mtime:
        logger.info("scip json already present path=%s", json_path)
        return json_path

    scip_bin = find_scip_cli()
    if not scip_bin:
        logger.warning(
            "scip CLI not found; install with: ./scripts/install-scip-cli.sh — cannot read %s",
            index_scip,
        )
        return None

    logger.info("scip export json bin=%s index=%s", scip_bin, index_scip)
    result = subprocess.run(
        [scip_bin, "print", "--json", str(index_scip)],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ.copy(),
    )
    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-2000:]
        logger.warning(
            "scip print failed code=%s stderr_tail=%s",
            result.returncode,
            stderr_tail,
        )
        return None

    if not result.stdout.strip():
        logger.warning("scip print returned empty stdout for %s", index_scip)
        return None

    json_path.write_text(result.stdout)
    logger.info("scip json written path=%s bytes=%s", json_path, json_path.stat().st_size)
    return json_path


def resolve_readable_index(repo_path: Path) -> Path | None:
    json_path = repo_path / SCIP_JSON_NAME
    if json_path.exists():
        return json_path
    scip_path = repo_path / SCIP_INDEX_NAME
    if scip_path.exists():
        exported = export_scip_json(scip_path)
        if exported:
            return exported
        return scip_path
    for match in repo_path.rglob(SCIP_INDEX_NAME):
        exported = export_scip_json(match)
        if exported:
            return exported
        return match
    return None
