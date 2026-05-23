"""
AST-based code indexer using tree-sitter.

Indexes all classes and methods in a repo, extracting:
  - Class names, superclasses, docstrings, line ranges
  - Method names, signatures, docstrings, enclosing class

This builds the structural knowledge graph of the codebase.
Producer docstrings are the richest source of producer intent.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from ripple.rib.graph.schema import CodeClass, CodeMethod

logger = logging.getLogger(__name__)

_SOURCE_EXTENSIONS = {".py", ".java", ".ts", ".tsx", ".js", ".jsx", ".kt", ".go"}
_SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "target", "build",
    "dist", "__pycache__", ".gradle", "vendor", "bower_components",
    "coverage", ".mypy_cache", ".pytest_cache",
}

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
except Exception:
    _LANGUAGES = {}
    _TS_AVAILABLE = False
    logger.warning("tree-sitter not available — code_indexer using regex fallback")


def index_repo(
    repo_path: Path,
    service_name: str,
) -> tuple[list[CodeClass], list[CodeMethod]]:
    """Index all classes and methods in a repo. Returns (classes, methods)."""
    all_classes: list[CodeClass] = []
    all_methods: list[CodeMethod] = []

    for file_path in _iter_source_files(repo_path):
        rel = str(file_path.relative_to(repo_path))
        lang_key = file_path.suffix
        try:
            classes, methods = _index_file(file_path, rel, service_name, lang_key)
            all_classes.extend(classes)
            all_methods.extend(methods)
        except Exception as e:
            logger.debug("code_indexer skip file=%s err=%s", rel, e)

    logger.info(
        "code_indexer done service=%s classes=%d methods=%d",
        service_name, len(all_classes), len(all_methods),
    )
    return all_classes, all_methods


def _iter_source_files(repo_path: Path):
    for path in repo_path.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix not in _SOURCE_EXTENSIONS:
            continue
        if any(skip in path.parts for skip in _SKIP_DIRS):
            continue
        yield path


def _index_file(
    file_path: Path,
    rel_path: str,
    service_name: str,
    lang_key: str,
) -> tuple[list[CodeClass], list[CodeMethod]]:
    source = file_path.read_text(errors="replace")

    if _TS_AVAILABLE and lang_key in _LANGUAGES:
        return _ts_index(source, rel_path, service_name, lang_key)

    return _regex_index(source, rel_path, service_name, lang_key)


# ── Tree-sitter indexer ───────────────────────────────────────────────────────

def _ts_index(
    source: str,
    rel_path: str,
    service_name: str,
    lang_key: str,
) -> tuple[list[CodeClass], list[CodeMethod]]:
    lang = _LANGUAGES[lang_key]
    parser = TSParser(lang)
    tree = parser.parse(source.encode())
    language_name = _lang_label(lang_key)

    classes: list[CodeClass] = []
    methods: list[CodeMethod] = []
    source_bytes = source.encode()

    # Walk the entire tree; track class context for methods
    _walk_node(
        tree.root_node, source_bytes, rel_path, service_name,
        language_name, classes, methods, current_class=None,
    )
    return classes, methods


def _walk_node(
    node,
    source: bytes,
    rel_path: str,
    service_name: str,
    language: str,
    classes: list[CodeClass],
    methods: list[CodeMethod],
    current_class: str | None,
) -> None:
    ntype = node.type

    if ntype in ("class_definition", "class_declaration", "class"):
        name_node = node.child_by_field_name("name")
        if name_node:
            cls_name = _text(name_node, source)
            docstring = _extract_ts_docstring(node, source, language)
            superclasses = _extract_superclasses(node, source, language)
            classes.append(CodeClass(
                service_name=service_name,
                file_path=rel_path,
                class_name=cls_name,
                docstring=docstring,
                superclasses=superclasses,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                language=language,
            ))
            # Recurse into class body with updated class context
            for child in node.children:
                _walk_node(child, source, rel_path, service_name, language, classes, methods, cls_name)
            return

    if ntype in (
        "function_definition", "method_declaration", "method_definition",
        "function_declaration", "constructor_declaration",
    ):
        name_node = node.child_by_field_name("name")
        if name_node:
            method_name = _text(name_node, source)
            sig = _build_signature(node, source, language)
            docstring = _extract_ts_docstring(node, source, language)
            methods.append(CodeMethod(
                service_name=service_name,
                file_path=rel_path,
                class_name=current_class,
                method_name=method_name,
                signature=sig,
                docstring=docstring,
                line=node.start_point[0] + 1,
                language=language,
            ))

    for child in node.children:
        _walk_node(child, source, rel_path, service_name, language, classes, methods, current_class)


def _text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode(errors="replace").strip()


def _extract_ts_docstring(node, source: bytes, language: str) -> str | None:
    """Extract docstring from class/method node depending on language."""
    if language == "python":
        # First statement in body is a string expression
        body = node.child_by_field_name("body")
        if body and body.children:
            for child in body.children:
                if child.type == "expression_statement":
                    for sub in child.children:
                        if sub.type == "string":
                            raw = _text(sub, source)
                            return _clean_docstring(raw)
                break
        return None

    # Java / TypeScript: look for block_comment (/** ... */) immediately preceding
    prev = node.prev_sibling
    while prev and prev.type in ("comment", "\n", "block_comment"):
        if prev.type == "block_comment":
            raw = _text(prev, source)
            if raw.startswith("/**"):
                return _clean_javadoc(raw)
        prev = prev.prev_sibling
    return None


def _extract_superclasses(node, source: bytes, language: str) -> list[str]:
    supers: list[str] = []
    for child in node.children:
        # Python: argument_list inside class definition
        if child.type == "argument_list":
            for arg in child.children:
                if arg.type == "identifier":
                    supers.append(_text(arg, source))
        # Java: superclass / super_interfaces
        if child.type in ("superclass", "super_interfaces"):
            for sub in child.children:
                if sub.type in ("type_identifier", "identifier"):
                    supers.append(_text(sub, source))
        # TS/JS: class_heritage
        if child.type == "class_heritage":
            for sub in child.children:
                if sub.type in ("identifier", "type_identifier"):
                    supers.append(_text(sub, source))
    return supers


def _build_signature(node, source: bytes, language: str) -> str:
    """Return a one-line signature for the method, skipping annotations."""
    lines = _text(node, source).split("\n")
    # Skip leading annotation lines (@Override, @GetMapping, etc.)
    sig_line = ""
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("@") or not stripped:
            continue
        sig_line = stripped
        break
    # Truncate at opening brace or colon (body start)
    for stop in ("{", ":"):
        idx = sig_line.find(stop)
        if idx > 0:
            sig_line = sig_line[:idx].strip()
            break
    return sig_line[:300]


# ── Regex fallback indexer ────────────────────────────────────────────────────

_PY_CLASS_RE = re.compile(r"^class\s+(\w+)(?:\(([^)]*)\))?:", re.MULTILINE)
_PY_DEF_RE = re.compile(r"^(\s*)def\s+(\w+)\s*\(", re.MULTILINE)
_JAVA_CLASS_RE = re.compile(r"\bclass\s+(\w+)(?:\s+extends\s+(\w+))?(?:\s+implements\s+([\w,\s]+))?", re.MULTILINE)
_JAVA_METHOD_RE = re.compile(
    r"(?:public|private|protected|static|final|abstract|synchronized|\s)+[\w<>\[\]]+\s+(\w+)\s*\([^)]*\)", re.MULTILINE
)
_JS_CLASS_RE = re.compile(r"\bclass\s+(\w+)(?:\s+extends\s+(\w+))?", re.MULTILINE)
_JS_FUNC_RE = re.compile(r"(?:function\s+(\w+)|(\w+)\s*(?:=\s*(?:async\s+)?function|\(.*\)\s*=>))", re.MULTILINE)


def _regex_index(
    source: str,
    rel_path: str,
    service_name: str,
    lang_key: str,
) -> tuple[list[CodeClass], list[CodeMethod]]:
    language = _lang_label(lang_key)
    classes: list[CodeClass] = []
    methods: list[CodeMethod] = []
    lines = source.splitlines()

    if lang_key == ".py":
        for m in _PY_CLASS_RE.finditer(source):
            line_no = source[:m.start()].count("\n") + 1
            supers = [s.strip() for s in (m.group(2) or "").split(",") if s.strip()]
            docstring = _py_docstring_after(lines, line_no)
            classes.append(CodeClass(
                service_name=service_name, file_path=rel_path,
                class_name=m.group(1), docstring=docstring,
                superclasses=supers, line_start=line_no, language=language,
            ))
        for m in _PY_DEF_RE.finditer(source):
            line_no = source[:m.start()].count("\n") + 1
            docstring = _py_docstring_after(lines, line_no)
            methods.append(CodeMethod(
                service_name=service_name, file_path=rel_path,
                method_name=m.group(2), signature=lines[line_no - 1].strip()[:200],
                docstring=docstring, line=line_no, language=language,
            ))

    elif lang_key == ".java":
        for m in _JAVA_CLASS_RE.finditer(source):
            line_no = source[:m.start()].count("\n") + 1
            supers = [s.strip() for s in (m.group(2) or "").split(",") if s.strip()]
            classes.append(CodeClass(
                service_name=service_name, file_path=rel_path,
                class_name=m.group(1), superclasses=supers,
                line_start=line_no, language=language,
            ))
        for m in _JAVA_METHOD_RE.finditer(source):
            if m.group(1) in {"if", "for", "while", "switch", "catch", "return"}:
                continue
            line_no = source[:m.start()].count("\n") + 1
            docstring = _javadoc_before(lines, line_no)
            methods.append(CodeMethod(
                service_name=service_name, file_path=rel_path,
                method_name=m.group(1), signature=lines[line_no - 1].strip()[:200],
                docstring=docstring, line=line_no, language=language,
            ))

    else:
        for m in _JS_CLASS_RE.finditer(source):
            line_no = source[:m.start()].count("\n") + 1
            supers = [m.group(2)] if m.group(2) else []
            classes.append(CodeClass(
                service_name=service_name, file_path=rel_path,
                class_name=m.group(1), superclasses=supers,
                line_start=line_no, language=language,
            ))
        for m in _JS_FUNC_RE.finditer(source):
            name = m.group(1) or m.group(2)
            if not name or name in {"if", "for", "while", "return"}:
                continue
            line_no = source[:m.start()].count("\n") + 1
            methods.append(CodeMethod(
                service_name=service_name, file_path=rel_path,
                method_name=name, signature=lines[line_no - 1].strip()[:200],
                line=line_no, language=language,
            ))

    return classes, methods


# ── Docstring helpers ─────────────────────────────────────────────────────────

def _py_docstring_after(lines: list[str], class_line: int) -> str | None:
    """Extract Python docstring from the line following a class/def header."""
    for i in range(class_line, min(class_line + 5, len(lines))):
        stripped = lines[i].strip()
        if stripped.startswith('"""') or stripped.startswith("'''"):
            doc_lines = [stripped]
            quote = stripped[:3]
            if not stripped.endswith(quote) or len(stripped) == 3:
                for j in range(i + 1, min(i + 30, len(lines))):
                    doc_lines.append(lines[j])
                    if lines[j].strip().endswith(quote):
                        break
            return _clean_docstring("\n".join(doc_lines))
    return None


def _javadoc_before(lines: list[str], method_line: int) -> str | None:
    """Extract Javadoc comment preceding a method."""
    # Scan backwards skipping blank lines and annotations (@Override etc.)
    i = method_line - 2
    while i >= 0 and method_line - i <= 10:
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("@"):
            i -= 1
            continue
        if stripped.endswith("*/"):
            # Found end of a block comment — collect backwards to /**
            doc_lines = [stripped]
            i -= 1
            while i >= 0 and method_line - i <= 40:
                s = lines[i].strip()
                doc_lines.insert(0, s)
                if s.startswith("/**") or s.startswith("/*"):
                    return _clean_javadoc("\n".join(doc_lines))
                i -= 1
        break
    return None


def _clean_docstring(raw: str) -> str:
    raw = raw.strip().strip('"""').strip("'''").strip()
    return re.sub(r"\n\s+", "\n", raw).strip()[:1000]


def _clean_javadoc(raw: str) -> str:
    raw = re.sub(r"/\*\*|\*/", "", raw)
    raw = re.sub(r"^\s*\*\s?", "", raw, flags=re.MULTILINE)
    return raw.strip()[:1000]


def _lang_label(ext: str) -> str:
    return {
        ".py": "python", ".java": "java",
        ".ts": "typescript", ".tsx": "typescript",
        ".js": "javascript", ".jsx": "javascript",
        ".kt": "kotlin", ".go": "go",
    }.get(ext, ext.lstrip("."))
