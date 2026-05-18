from pathlib import Path

from ripple.rib.indexer.scip_runner import (
    SCIP_FINGERPRINT_NAME,
    compute_source_fingerprint,
    detect_language,
)
from ripple.rib.indexer.scip_runner import RepoLanguage


def test_detect_language_python(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "main.py").write_text("print(1)\n")
    assert detect_language(tmp_path) == RepoLanguage.PYTHON


def test_fingerprint_stable(tmp_path: Path) -> None:
    src = tmp_path / "app.py"
    src.write_text("x = 1\n")
    fp1 = compute_source_fingerprint(tmp_path, RepoLanguage.PYTHON)
    fp2 = compute_source_fingerprint(tmp_path, RepoLanguage.PYTHON)
    assert fp1 == fp2
    src.write_text("x = 2\n")
    fp3 = compute_source_fingerprint(tmp_path, RepoLanguage.PYTHON)
    assert fp3 != fp1


def test_sidecar_name() -> None:
    assert SCIP_FINGERPRINT_NAME == "index.scip.fingerprint"
