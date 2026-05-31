from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
from enum import Enum
from pathlib import Path

from ripple.rib.graph.store import RippleStore
from ripple.rib.indexer.scip_cli import export_scip_json

logger = logging.getLogger(__name__)

SCIP_INDEX_NAME = "index.scip"
SCIP_FINGERPRINT_NAME = "index.scip.fingerprint"
DB_FINGERPRINT_KEY = "__scip_source_fingerprint__"

SKIP_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "target",
    "build",
    "dist",
    ".gradle",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "vendor",
}

SOURCE_EXTENSIONS = {
    "java": {".java", ".kt", ".kts"},
    "typescript": {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"},
    "python": {".py", ".pyi"},
}


class RepoLanguage(str, Enum):
    JAVA = "java"
    TYPESCRIPT = "typescript"
    PYTHON = "python"
    UNKNOWN = "unknown"


def detect_language(repo_path: Path) -> RepoLanguage:
    if (repo_path / "pom.xml").exists() or (repo_path / "build.gradle").exists():
        return RepoLanguage.JAVA
    if (repo_path / "build.gradle.kts").exists():
        return RepoLanguage.JAVA
    if (repo_path / "package.json").exists():
        return RepoLanguage.TYPESCRIPT
    if (repo_path / "pyproject.toml").exists() or (repo_path / "setup.py").exists():
        return RepoLanguage.PYTHON
    if (repo_path / "requirements.txt").exists():
        return RepoLanguage.PYTHON
    py_count = sum(1 for _ in repo_path.rglob("*.py") if _is_under_repo(repo_path, _))
    java_count = sum(1 for _ in repo_path.rglob("*.java") if _is_under_repo(repo_path, _))
    ts_count = sum(
        1
        for pattern in ("*.ts", "*.tsx")
        for _ in repo_path.rglob(pattern)
        if _is_under_repo(repo_path, _)
    )
    counts = {
        RepoLanguage.PYTHON: py_count,
        RepoLanguage.JAVA: java_count,
        RepoLanguage.TYPESCRIPT: ts_count,
    }
    best = max(counts, key=counts.get)
    if counts[best] > 0:
        return best
    return RepoLanguage.UNKNOWN


def compute_source_fingerprint(repo_path: Path, language: RepoLanguage) -> str:
    extensions = SOURCE_EXTENSIONS.get(language.value, set())
    if not extensions:
        extensions = set().union(*SOURCE_EXTENSIONS.values())
    entries: list[str] = []
    for path in sorted(repo_path.rglob("*")):
        if not path.is_file():
            continue
        if not _is_under_repo(repo_path, path):
            continue
        if path.suffix not in extensions:
            continue
        rel = path.relative_to(repo_path).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        entries.append(f"{rel}:{digest}")
    payload = "\n".join(entries)
    return hashlib.sha256(payload.encode()).hexdigest()


def ensure_scip_index(
    repo_path: Path,
    service_name: str,
    store: RippleStore,
) -> dict[str, str | bool]:
    language = detect_language(repo_path)
    fingerprint = compute_source_fingerprint(repo_path, language)
    index_path = repo_path / SCIP_INDEX_NAME
    sidecar_path = repo_path / SCIP_FINGERPRINT_NAME

    logger.info(
        "scip ensure start service=%s language=%s repo=%s fingerprint=%s",
        service_name,
        language.value,
        repo_path,
        fingerprint[:12],
    )

    stored_fp = store.get_file_content_hash(DB_FINGERPRINT_KEY, service_name)
    if index_path.exists() and _fingerprint_matches(fingerprint, sidecar_path, stored_fp):
        export_scip_json(index_path)
        logger.info(
            "scip reuse committed index service=%s path=%s",
            service_name,
            index_path,
        )
        store.upsert_indexed_file(service_name, DB_FINGERPRINT_KEY, fingerprint)
        store.upsert_indexed_file(
            service_name, SCIP_INDEX_NAME, _file_hash(index_path)
        )
        return {
            "scip_path": str(index_path),
            "reused_committed": True,
            "generated": False,
            "language": language.value,
            "fingerprint": fingerprint,
        }

    generated = generate_scip_index(repo_path, language)
    if not generated and not index_path.exists():
        logger.warning(
            "scip index failed service=%s language=%s scip-java=%s scip-python=%s",
            service_name,
            language.value,
            shutil.which("scip-java"),
            shutil.which("scip-python"),
        )
        return {
            "scip_path": "",
            "reused_committed": False,
            "generated": False,
            "language": language.value,
            "fingerprint": fingerprint,
            "error": "scip_index_failed",
        }

    if not index_path.exists():
        found = _find_any_scip(repo_path)
        if found is None:
            logger.warning(
                "scip missing after generate service=%s generated=%s",
                service_name,
                generated,
            )
            return {
                "scip_path": "",
                "reused_committed": False,
                "generated": generated,
                "language": language.value,
                "fingerprint": fingerprint,
                "error": "index_scip_missing_after_generate",
            }
        index_path = found

    sidecar_path.write_text(fingerprint)
    store.upsert_indexed_file(service_name, DB_FINGERPRINT_KEY, fingerprint)
    store.upsert_indexed_file(service_name, SCIP_INDEX_NAME, _file_hash(index_path))

    json_path = export_scip_json(index_path)
    if json_path is None:
        logger.warning(
            "scip index exists but index.json not created service=%s install scip CLI",
            service_name,
        )

    logger.info(
        "scip ready service=%s path=%s json=%s generated=%s size_bytes=%s",
        service_name,
        index_path,
        json_path,
        generated,
        index_path.stat().st_size if index_path.exists() else 0,
    )
    return {
        "scip_path": str(index_path),
        "reused_committed": False,
        "generated": generated,
        "language": language.value,
        "fingerprint": fingerprint,
    }


def generate_scip_index(repo_path: Path, language: RepoLanguage) -> bool:
    logger.info("scip generate start language=%s repo=%s", language.value, repo_path)
    if language == RepoLanguage.JAVA:
        return _generate_java(repo_path)
    if language == RepoLanguage.TYPESCRIPT:
        return _generate_typescript(repo_path)
    if language == RepoLanguage.PYTHON:
        return _generate_python(repo_path)
    return False


def _fingerprint_matches(
    fingerprint: str,
    sidecar_path: Path,
    stored_fp: str | None,
) -> bool:
    if sidecar_path.exists() and sidecar_path.read_text().strip() == fingerprint:
        return True
    if stored_fp and stored_fp == fingerprint:
        return True
    return False


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _find_any_scip(repo_path: Path) -> Path | None:
    candidate = repo_path / SCIP_INDEX_NAME
    if candidate.exists():
        return candidate
    for match in repo_path.rglob(SCIP_INDEX_NAME):
        if _is_under_repo(repo_path, match):
            return match
    return None


def _is_under_repo(repo_path: Path, path: Path) -> bool:
    try:
        rel = path.relative_to(repo_path)
    except ValueError:
        return False
    return not any(part in SKIP_DIRS for part in rel.parts)


def _java_home_for_scip() -> str | None:
    """Return a JDK 21+ home directory, preferring Corretto/Temurin installations."""
    # Check system java_home helper (macOS)
    try:
        result = subprocess.run(
            ["/usr/libexec/java_home", "-v", "21"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except (FileNotFoundError, OSError):
        pass

    # Well-known install locations (macOS / Linux)
    candidates = [
        "/Users/raghunandhanaj/Library/Java/JavaVirtualMachines/corretto-21.0.3/Contents/Home",
        "/Library/Java/JavaVirtualMachines/corretto-21/Contents/Home",
        "/usr/lib/jvm/java-21-openjdk-amd64",
        "/usr/lib/jvm/java-21",
    ]
    for path in candidates:
        if Path(path).exists():
            return path

    return None


def _run(
    cmd: list[str],
    cwd: Path,
    timeout_seconds: int = 1800,
    extra_env: dict[str, str] | None = None,
) -> bool:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    logger.info("scip subprocess cwd=%s cmd=%s", cwd, " ".join(cmd))
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("scip subprocess timed out after %ds cmd=%s", timeout_seconds, " ".join(cmd))
        return False
    except Exception as exc:
        logger.warning("scip subprocess error cmd=%s err=%s", " ".join(cmd), exc)
        return False
    if result.returncode != 0:
        stderr_tail = (result.stderr or "")[-2000:]
        stdout_tail = (result.stdout or "")[-1000:]
        logger.warning(
            "scip subprocess failed code=%s stderr_tail=%s stdout_tail=%s",
            result.returncode,
            stderr_tail,
            stdout_tail,
        )
    else:
        logger.info("scip subprocess ok code=0")
    return result.returncode == 0


def _generate_java(repo_path: Path) -> bool:
    java_home = _java_home_for_scip()
    if java_home:
        logger.info("scip java using JAVA_HOME=%s", java_home)
    if _maybe_maven_compile(repo_path, java_home=java_home):
        logger.info("scip java maven compile finished repo=%s", repo_path)
    java_env = {"JAVA_HOME": java_home} if java_home else {}
    if java_home:
        # Prepend JDK bin to PATH so scip-java picks up the right javac
        existing_path = os.environ.get("PATH", "")
        java_env["PATH"] = f"{java_home}/bin:{existing_path}"

    if shutil.which("scip-java"):
        if _run(["scip-java", "index", "--targetroot", "."], repo_path, extra_env=java_env):
            return (repo_path / SCIP_INDEX_NAME).exists()
    coursier = shutil.which("cs") or shutil.which("coursier")
    if coursier:
        if _run(
            [
                coursier,
                "launch",
                "com.sourcegraph:scip-java_2.13:0.11.0",
                "--",
                "index",
                "--targetroot",
                ".",
            ],
            repo_path,
            extra_env=java_env,
        ):
            return (repo_path / SCIP_INDEX_NAME).exists()
    logger.warning("scip java no indexer on PATH repo=%s", repo_path)
    return False


def _maybe_maven_compile(repo_path: Path, java_home: str | None = None) -> bool:
    mvnw = repo_path / "mvnw"
    if not mvnw.exists():
        return False
    java_env = {"JAVA_HOME": java_home} if java_home else {}
    return _run(
        [str(mvnw), "-q", "compile", "-DskipTests"],
        repo_path,
        timeout_seconds=900,
        extra_env=java_env,
    )


def _generate_python(repo_path: Path) -> bool:
    candidates = [
        ["scip-python", "index", "."],
        ["python", "-m", "scip_python", "index", "."],
        ["python3", "-m", "scip_python", "index", "."],
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]) or cmd[0].startswith("python"):
            if _run(cmd, repo_path):
                if (repo_path / SCIP_INDEX_NAME).exists():
                    return True
    return False


def _npm_install(repo_path: Path) -> None:
    """Install node_modules so scip-typescript can resolve imports and tsconfig extends."""
    pkg_json = repo_path / "package.json"
    if not pkg_json.exists():
        return

    # Prefer yarn if yarn.lock exists, otherwise npm
    if (repo_path / "yarn.lock").exists() and shutil.which("yarn"):
        _run(
            ["yarn", "install", "--frozen-lockfile", "--ignore-scripts", "--non-interactive"],
            repo_path,
            timeout_seconds=300,
        )
        return

    npm = shutil.which("npm")
    if npm:
        _run(
            [npm, "install", "--prefer-offline", "--ignore-scripts", "--legacy-peer-deps"],
            repo_path,
            timeout_seconds=300,
        )


def _patch_expo_tsconfig(repo_path: Path) -> Path | None:
    """
    Expo projects extend 'expo/tsconfig.base' which lives in node_modules.
    If that base file is still missing after npm install (e.g. install was skipped
    because it's too slow), write a minimal fallback tsconfig that scip-typescript
    can parse without crashing.  Returns the patched path or None if not needed.
    """
    tsconfig = repo_path / "tsconfig.json"
    if not tsconfig.exists():
        return None

    import json
    try:
        cfg = json.loads(tsconfig.read_text())
    except Exception:
        return None

    extends = cfg.get("extends", "")
    if "expo" not in str(extends):
        return None

    base_path = repo_path / "node_modules" / "expo" / "tsconfig.base.json"
    if base_path.exists():
        return None  # npm install worked — no patch needed

    # Write a scip-friendly override next to the real tsconfig
    override_path = repo_path / "tsconfig.scip.json"
    patched = dict(cfg)
    patched.pop("extends", None)
    patched.setdefault("compilerOptions", {}).update({
        "allowJs": True,
        "noEmit": True,
        "skipLibCheck": True,
        "moduleResolution": "node",
        "esModuleInterop": True,
        "jsx": "react-native",
    })
    override_path.write_text(json.dumps(patched, indent=2))
    logger.info("scip expo tsconfig patch written path=%s", override_path)
    return override_path


def _generate_typescript(repo_path: Path) -> bool:
    # Install node_modules so scip-typescript can resolve tsconfig extends and imports
    _npm_install(repo_path)

    # Patch Expo tsconfig if node_modules/expo still missing after install
    tsconfig_override = _patch_expo_tsconfig(repo_path)
    extra_flags: list[str] = []
    if tsconfig_override:
        extra_flags = ["--tsconfig", str(tsconfig_override)]

    if shutil.which("scip-typescript"):
        if _run(["scip-typescript", "index", *extra_flags], repo_path):
            if (repo_path / SCIP_INDEX_NAME).exists():
                return True
    if shutil.which("npx"):
        if _run(["npx", "--yes", "@sourcegraph/scip-typescript", "index", *extra_flags], repo_path):
            if (repo_path / SCIP_INDEX_NAME).exists():
                return True
    return False
