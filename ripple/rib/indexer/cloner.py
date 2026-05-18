from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path


def clone_repo(repo_url: str, target_dir: str | Path | None = None) -> Path:
    destination = Path(target_dir) if target_dir else Path(tempfile.mkdtemp(prefix="ripple_"))
    destination.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to clone {repo_url}: {result.stderr.strip()}")
    return destination


def service_name_from_url(repo_url: str) -> str:
    name = repo_url.rstrip("/").rsplit("/", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return re.sub(r"[^a-zA-Z0-9_-]", "-", name)


def cleanup_clone(path: str | Path) -> None:
    shutil.rmtree(path, ignore_errors=True)
