"""
Test evidence extractor.

Tests are the most reliable source of business rules — they encode
what the developer INTENDED, written as executable assertions.

Example: assertEquals(100, invoice.getAmount()) in a test named
testInvoiceAmountInPence proves the unit is pence beyond any doubt.

Extracts TestEvidence: (field_fqn, test_file, test_method, assertion_code)
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from ripple.rib.graph.schema import FieldNode, TestEvidence
from ripple.rib.indexer.field_finder import field_name_variants

logger = logging.getLogger(__name__)

# File patterns that indicate test files
_TEST_FILENAME_PATTERNS = [
    r"test_.*\.py$",
    r".*_test\.py$",
    r".*Test\.java$",
    r".*Tests\.java$",
    r".*Spec\.java$",
    r".*\.test\.(ts|js|tsx|jsx)$",
    r".*\.spec\.(ts|js|tsx|jsx)$",
    r".*_spec\.rb$",
    r".*_test\.go$",
]
_TEST_PATTERNS_COMPILED = [re.compile(p) for p in _TEST_FILENAME_PATTERNS]

_SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "target",
    "build", "dist", "__pycache__", ".gradle", "vendor",
}

# Assertion keywords that signal business-rule encoding
_ASSERTION_KEYWORDS = [
    r"assert\w*\s*\(",
    r"assertEquals\s*\(",
    r"assertEqual\s*\(",
    r"assertThat\s*\(",
    r"expect\s*\(",
    r"should\.",
    r"\.to(?:Equal|Be|Match|Contain|Have)\s*\(",
    r"verify\s*\(",
    r"check\s*\(",
]
_ASSERTION_RE = re.compile("|".join(_ASSERTION_KEYWORDS))

# Patterns that identify the enclosing test method
_TEST_METHOD_PATTERNS = [
    re.compile(r"def\s+(test\w*)\s*\("),            # Python
    re.compile(r"(?:public\s+void|@Test)\s+(\w+)\s*\("),   # Java
    re.compile(r"(?:it|test|describe)\s*\(\s*['\"]([^'\"]+)['\"]"),  # Jest/Mocha
    re.compile(r"fun\s+(test\w+)\s*\("),             # Kotlin
    re.compile(r"func\s+(Test\w+)\s*\("),            # Go
]

_CONTEXT_LINES = 10


def extract_test_evidences(
    repo_path: Path,
    fields: list[FieldNode],
    service_name: str,
) -> list[TestEvidence]:
    """
    Find test files in the repo and extract assertions related to each field.
    Returns TestEvidence objects with the assertion code as proof of business rules.
    """
    test_files = _find_test_files(repo_path)
    if not test_files:
        logger.info("test_extractor no test files found service=%s", service_name)
        return []

    logger.info("test_extractor found %d test files service=%s", len(test_files), service_name)

    evidences: list[TestEvidence] = []
    for field in fields:
        variants = field_name_variants(field.name)
        for test_file in test_files:
            hits = _search_in_file(repo_path, test_file, variants)
            for hit in hits:
                evidences.append(
                    TestEvidence(
                        field_fqn=field.fqn,
                        service_name=service_name,
                        test_file=str(test_file.relative_to(repo_path)),
                        test_method=hit.method_name,
                        assertion_code=hit.assertion_code,
                    )
                )

    logger.info("test_extractor done service=%s evidences=%d", service_name, len(evidences))
    return evidences


# ── Test file discovery ───────────────────────────────────────────────────────

def _find_test_files(repo_path: Path) -> list[Path]:
    results: list[Path] = []
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        if any(skip in path.parts for skip in _SKIP_DIRS):
            continue
        name = path.name
        if any(p.search(name) for p in _TEST_PATTERNS_COMPILED):
            results.append(path)
        # Also include files inside test/tests directories
        elif any(part in {"test", "tests", "__tests__", "spec", "specs"} for part in path.parts):
            if path.suffix in {".py", ".java", ".ts", ".js", ".jsx", ".tsx", ".kt", ".go", ".rb"}:
                results.append(path)
    return list(set(results))


# ── Hit dataclass ─────────────────────────────────────────────────────────────

@dataclass
class _TestHit:
    method_name: str
    assertion_code: str


# ── File search ───────────────────────────────────────────────────────────────

def _search_in_file(
    repo_path: Path,
    test_file: Path,
    variants: list[str],
) -> list[_TestHit]:
    try:
        source = test_file.read_text(errors="replace")
    except Exception:
        return []

    lines = source.splitlines()
    pattern = re.compile(r"\b(" + "|".join(re.escape(v) for v in variants) + r")\b")
    hits: list[_TestHit] = []
    seen: set[tuple[str, int]] = set()

    for i, line in enumerate(lines):
        if not pattern.search(line):
            continue

        # Get surrounding context block
        start = max(0, i - _CONTEXT_LINES)
        end = min(len(lines), i + _CONTEXT_LINES + 1)
        context_lines = lines[start:end]
        context = "\n".join(context_lines)

        # Only include if there's an assertion nearby
        if not _ASSERTION_RE.search(context):
            continue

        # Find enclosing test method
        method_name = _find_enclosing_test_method(lines, i)
        if not method_name:
            continue

        key = (method_name, i)
        if key in seen:
            continue
        seen.add(key)

        # Extract the most relevant assertion lines
        assertion_code = _extract_assertion_block(context_lines, i - start)
        hits.append(_TestHit(method_name=method_name, assertion_code=assertion_code))

    return hits


def _find_enclosing_test_method(lines: list[str], hit_line: int) -> str | None:
    """Scan backwards to find the test method that contains the hit line."""
    for i in range(hit_line, max(-1, hit_line - 100), -1):
        if i >= len(lines):
            continue
        line = lines[i]
        for pattern in _TEST_METHOD_PATTERNS:
            m = pattern.search(line)
            if m:
                return m.group(1)
    return None


def _extract_assertion_block(context_lines: list[str], center: int) -> str:
    """Extract the most relevant lines — the assertion + field reference."""
    relevant: list[str] = []
    for i, line in enumerate(context_lines):
        stripped = line.strip()
        if _ASSERTION_RE.search(stripped) or i == center:
            # Include a small window around each assertion
            start = max(0, i - 2)
            end = min(len(context_lines), i + 3)
            relevant.extend(context_lines[start:end])

    # Deduplicate while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for line in relevant:
        if line not in seen:
            seen.add(line)
            deduped.append(line)

    return "\n".join(deduped)[:2000]
