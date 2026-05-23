"""
Multi-strategy field finder.

For each API field, finds usages in consumer repos with rich context:
  - enclosing class and method (tree-sitter AST)
  - local variable name assigned from the field (semantic signal)
  - surrounding code context (±15 lines)
  - arithmetic/operations performed on the value

Strategy layers (cheapest first):
  1. Generate all name variants (camelCase, snake_case, UPPER_CASE, quoted)
  2. grep -rn across source files — finds 90%+ of real usages
  3. tree-sitter — enriches each hit with class/method scope
  4. Regex patterns — extracts local var names and operations
"""
from __future__ import annotations

import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ripple.rib.graph.schema import FieldUsage

logger = logging.getLogger(__name__)

_SOURCE_EXTENSIONS = {".py", ".java", ".ts", ".tsx", ".js", ".jsx", ".go", ".kt", ".rb", ".cs"}
_SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "target", "build",
    "dist", "__pycache__", ".gradle", "vendor", "bower_components",
    ".idea", ".vscode", "coverage", ".mypy_cache", ".pytest_cache",
}

# Operations that reveal what the consumer assumes about a field's unit/type
_OPERATION_PATTERNS = [
    (r"/\s*100(?![\d.])", "divide_by_100"),
    (r"\*\s*100(?![\d.])", "multiply_by_100"),
    (r"/\s*1000(?![\d.])", "divide_by_1000"),
    (r"\.toFixed\s*\(\s*2\s*\)", "to_fixed_2_decimals"),
    (r"Math\.round\s*\(", "math_round"),
    (r"Math\.floor\s*\(", "math_floor"),
    (r"parseInt\s*\(", "parse_int"),
    (r"parseFloat\s*\(", "parse_float"),
    (r"int\s*\(", "cast_int"),
    (r"float\s*\(", "cast_float"),
    (r"str\s*\(", "cast_str"),
    (r"\.toUpperCase\s*\(\)", "to_upper_case"),
    (r"\.toLowerCase\s*\(\)", "to_lower_case"),
    (r"new\s+Date\s*\(", "construct_date"),
    (r"datetime\.", "datetime_operation"),
    (r"Decimal\s*\(", "construct_decimal"),
    (r"\?\.", "safe_navigation"),
    (r"!==?\s*null", "null_check"),
    (r"!==?\s*undefined", "undefined_check"),
    (r"==\s*null", "null_equality"),
    (r"is\s+None", "none_check"),
    (r"is\s+not\s+None", "not_none_check"),
]

# Patterns to extract local variable name assigned from a field access
_ASSIGN_PATTERNS = [
    # Python: local_var = obj.field  or  local_var = data["field"]
    r'(\w+)\s*=\s*\w+(?:\.\w+)*\.\b{name}\b',
    r'(\w+)\s*=\s*\w+\[[\'"]{name}[\'"]\]',
    # JS/TS: const localVar = obj.field  or  let localVar = obj.field
    r'(?:const|let|var)\s+(\w+)\s*=\s*\w+(?:\.\w+)*\.\b{name}\b',
    r'(?:const|let|var)\s+(\w+)\s*=\s*\w+\[[\'"]{name}[\'"]\]',
    # Java: Type localVar = obj.getField()  or  obj.field
    r'\w+\s+(\w+)\s*=\s*\w+(?:\.\w+)*\.get{Name}\s*\(',
    r'\w+\s+(\w+)\s*=\s*\w+(?:\.\w+)*\.\b{name}\b',
    # Destructuring: { fieldName: localName } or { fieldName }
    r'\{\s*\b{name}\b\s*:\s*(\w+)',
    r'(\w+)\s*}\s*=.*\b{name}\b',
]

try:
    import tree_sitter_python as _tspython
    import tree_sitter_java as _tsjava
    import tree_sitter_javascript as _tsjs
    from tree_sitter import Language, Parser as TSParser

    _LANGUAGES: dict[str, Language] = {
        ".py": Language(_tspython.language()),
        ".java": Language(_tsjava.language()),
        ".js": Language(_tsjs.language()),
        ".jsx": Language(_tsjs.language()),
        ".ts": Language(_tsjs.language()),
        ".tsx": Language(_tsjs.language()),
    }
    _TS_AVAILABLE = True
    logger.info("tree-sitter available — AST scope enrichment enabled")
except Exception:
    _LANGUAGES = {}
    _TS_AVAILABLE = False
    logger.warning("tree-sitter not available — falling back to regex scope detection")


@dataclass
class _GrepHit:
    rel_path: str
    line: int
    expression: str


def field_name_variants(field_name: str) -> list[str]:
    """All naming convention variants for a field name."""
    variants: set[str] = {field_name}

    # camelCase → snake_case
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", field_name).lower()
    variants.add(snake)

    # snake_case → camelCase
    if "_" in field_name:
        parts = field_name.split("_")
        camel = parts[0].lower() + "".join(p.capitalize() for p in parts[1:])
        variants.add(camel)

    # PascalCase
    pascal = field_name[0].upper() + field_name[1:] if field_name else field_name
    variants.add(pascal)

    # UPPER_SNAKE_CASE
    variants.add(snake.upper())

    # Java getter style: getFieldName
    camel_name = next(
        (v for v in variants if v and v[0].islower() and "_" not in v),
        field_name,
    )
    variants.add("get" + camel_name[0].upper() + camel_name[1:])

    # Remove very short variants that would cause too many false positives
    return [v for v in variants if len(v) >= 3]


def find_field_usages(
    repo_path: Path,
    field_name: str,
    field_fqn: str,
    consumer_service: str,
    context_lines: int = 15,
) -> list[FieldUsage]:
    """
    Find all usages of an API field in a consumer repo with rich context.
    Returns FieldUsage objects enriched with class/method scope and operations.
    """
    variants = field_name_variants(field_name)
    logger.debug("field_finder field=%s variants=%s", field_name, variants)

    hits = _grep_for_variants(repo_path, variants)
    logger.info("field_finder field=%s hits=%d", field_name, len(hits))

    usages: list[FieldUsage] = []
    seen: set[tuple[str, int]] = set()

    for hit in hits:
        key = (hit.rel_path, hit.line)
        if key in seen:
            continue
        seen.add(key)

        abs_path = repo_path / hit.rel_path
        if not abs_path.exists():
            continue

        source_lines = _read_lines(abs_path)
        context = _extract_context(source_lines, hit.line, context_lines)
        context_block = "\n".join(context)

        # Tree-sitter scope (class + method)
        scope = _get_scope(abs_path, source_lines, hit.line)

        # Local variable name assigned from this field
        local_var = _extract_local_var(hit.expression, context_block, field_name)

        # Operations performed on this value
        ops = _extract_operations(context_block)

        usages.append(
            FieldUsage(
                field_fqn=field_fqn,
                consumer_service=consumer_service,
                file_path=hit.rel_path,
                line=hit.line,
                expression=hit.expression[:500],
                surrounding_context=context_block[:3000],
                containing_function=scope.method or "",
                containing_class=scope.cls or "",
                local_var_name=local_var or "",
                operations=ops,
            )
        )

    return usages


# ── Grep ──────────────────────────────────────────────────────────────────────

def _grep_for_variants(repo_path: Path, variants: list[str]) -> list[_GrepHit]:
    pattern = "|".join(re.escape(v) for v in variants)
    include_args = [arg for ext in _SOURCE_EXTENSIONS for arg in ("--include", f"*{ext}")]
    exclude_args = [arg for d in _SKIP_DIRS for arg in ("--exclude-dir", d)]

    try:
        result = subprocess.run(
            ["grep", "-rn", "-E", pattern, *include_args, *exclude_args, str(repo_path)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        logger.warning("grep failed for repo=%s", repo_path)
        return []

    hits: list[_GrepHit] = []
    for line in result.stdout.splitlines():
        m = re.match(r"^(.+?):(\d+):(.*)$", line)
        if not m:
            continue
        abs_file = Path(m.group(1))
        try:
            rel = str(abs_file.relative_to(repo_path))
        except ValueError:
            continue
        # Skip binary-looking hits and skip dirs
        if any(skip in abs_file.parts for skip in _SKIP_DIRS):
            continue
        hits.append(_GrepHit(rel, int(m.group(2)), m.group(3).strip()))

    return hits


# ── Context extraction ────────────────────────────────────────────────────────

def _read_lines(path: Path) -> list[str]:
    try:
        return path.read_text(errors="replace").splitlines()
    except Exception:
        return []


def _extract_context(lines: list[str], hit_line: int, radius: int) -> list[str]:
    """Return ±radius lines around hit_line (1-indexed), with line numbers."""
    start = max(0, hit_line - radius - 1)
    end = min(len(lines), hit_line + radius)
    result = []
    for i, line in enumerate(lines[start:end], start=start + 1):
        prefix = ">>>" if i == hit_line else "   "
        result.append(f"{prefix} {i:4d}: {line}")
    return result


# ── Scope detection (class + method) ─────────────────────────────────────────

@dataclass
class _Scope:
    cls: Optional[str]
    method: Optional[str]


def _get_scope(path: Path, lines: list[str], hit_line: int) -> _Scope:
    if _TS_AVAILABLE:
        lang = _LANGUAGES.get(path.suffix)
        if lang:
            return _ts_scope(path, lang, hit_line)
    return _regex_scope(lines, hit_line)


def _ts_scope(path: Path, lang: "Language", target_line: int) -> _Scope:
    """Use tree-sitter to find enclosing class and method for a line."""
    try:
        source = path.read_bytes()
        parser = TSParser(lang)
        tree = parser.parse(source)
        cls, method = _find_scope_at_line(tree.root_node, target_line - 1)
        return _Scope(cls=cls, method=method)
    except Exception as e:
        logger.debug("tree-sitter scope failed path=%s err=%s", path, e)
        return _Scope(cls=None, method=None)


_CLASS_TYPES = {
    "class_definition",       # Python
    "class_declaration",      # Java, TS/JS
    "class",                  # JS shorthand
}
_METHOD_TYPES = {
    "function_definition",    # Python
    "method_declaration",     # Java
    "method_definition",      # TS/JS class method
    "function_declaration",   # JS/TS top-level
    "arrow_function",         # JS/TS arrow
    "constructor_declaration",# Java
}


def _find_scope_at_line(
    node: "Node",  # type: ignore[name-defined]
    target_line: int,
    cur_cls: Optional[str] = None,
    cur_method: Optional[str] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Recursively walk the AST to find the innermost class/method at target_line."""
    if node.start_point[0] > target_line or node.end_point[0] < target_line:
        return cur_cls, cur_method

    if node.type in _CLASS_TYPES:
        name_node = node.child_by_field_name("name")
        if name_node:
            cur_cls = name_node.text.decode(errors="replace")
        cur_method = None  # reset method when entering a new class

    elif node.type in _METHOD_TYPES:
        name_node = node.child_by_field_name("name")
        if name_node:
            cur_method = name_node.text.decode(errors="replace")

    for child in node.children:
        cur_cls, cur_method = _find_scope_at_line(child, target_line, cur_cls, cur_method)

    return cur_cls, cur_method


def _regex_scope(lines: list[str], hit_line: int) -> _Scope:
    """Fallback: scan backwards for class/def/function keywords."""
    cls = None
    method = None
    for i in range(hit_line - 2, max(-1, hit_line - 80), -1):
        line = lines[i].strip() if i < len(lines) else ""
        if not cls:
            m = re.match(r"(?:public\s+(?:class|interface|enum)|class)\s+(\w+)", line)
            if m:
                cls = m.group(1)
        if not method:
            m = re.match(
                r"(?:(?:public|private|protected|static|async|def)\s+)*"
                r"(?:[\w<>\[\]]+\s+)?(\w+)\s*\(",
                line,
            )
            if m and m.group(1) not in {"if", "for", "while", "switch", "catch"}:
                method = m.group(1)
        if cls and method:
            break
    return _Scope(cls=cls, method=method)


# ── Local variable extraction ─────────────────────────────────────────────────

def _extract_local_var(expression: str, context: str, field_name: str) -> Optional[str]:
    """Extract the local variable name a consumer assigns this field to."""
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", field_name).lower()
    camel = field_name
    pascal = field_name[0].upper() + field_name[1:] if field_name else field_name
    _skip = {field_name.lower(), snake, "self", "this", "data", "response", "result", "obj", "item", "value"}

    for name_variant in (field_name, snake, camel, pascal):
        esc = re.escape(name_variant)
        pascal_variant = name_variant[0].upper() + name_variant[1:] if name_variant else name_variant
        # Build patterns directly with pre-escaped variant to avoid .format() issues
        raw_patterns = [
            rf"(\w+)\s*=\s*\w+(?:\.\w+)*\.{esc}\b",
            rf"(\w+)\s*=\s*\w+\[['\"]{{esc}}['\"]\]".replace("{esc}", esc),
            rf"(?:const|let|var)\s+(\w+)\s*=\s*\w+(?:\.\w+)*\.{esc}\b",
            rf"\w+\s+(\w+)\s*=\s*\w+(?:\.\w+)*\.get{re.escape(pascal_variant)}\s*\(",
            rf"\w+\s+(\w+)\s*=\s*\w+(?:\.\w+)*\.{esc}\b",
            rf"\{{\s*{esc}\s*:\s*(\w+)",
        ]
        for pattern in raw_patterns:
            for text in (expression, context):
                try:
                    m = re.search(pattern, text)
                except re.error:
                    continue
                if m:
                    candidate = m.group(1)
                    if candidate.lower() not in _skip:
                        return candidate
    return None


# ── Operation extraction ──────────────────────────────────────────────────────

def _extract_operations(context: str) -> list[str]:
    """Extract arithmetic and type operations performed on the field value."""
    ops: list[str] = []
    for pattern, label in _OPERATION_PATTERNS:
        if re.search(pattern, context):
            ops.append(label)
    return ops
