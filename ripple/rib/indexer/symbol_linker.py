"""
Symbol → Field linker.

Bridges SCIP symbol IDs (code-structure space) to OpenAPI field FQNs (API-contract space).

The core mismatch:
  SCIP:    scip-java maven . . com/example/OrderService#getRewardPoints().
  OpenAPI: user-service::REST::GET /users/{id}::response.200.rewardPoints

Strategy (layered, cheapest first):
  1. Leaf-name match — extract the identifier from both sides, normalize
     (strip get/set/is, fold camelCase + snake_case to lowercase), compare.
     Free, deterministic, O(n).
  2. LLM disambiguation (TODO) — for cases where multiple fields share
     the same leaf name across different endpoints.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Identifiers too common to produce a reliable match.
_SKIP_IDENTIFIERS: frozenset[str] = frozenset(
    {
        "id",
        "name",
        "type",
        "value",
        "data",
        "result",
        "response",
        "request",
        "object",
        "class",
        "equals",
        "hashcode",
        "tostring",
        "init",
        "new",
        "super",
        "this",
        "null",
        "void",
        "error",
        "message",
        "status",
        "code",
        "list",
        "map",
        "set",
        "get",
        "put",
        "add",
        "remove",
        "size",
        "length",
        "index",
        "key",
        "item",
        "items",
        "body",
        "header",
        "path",
        "query",
    }
)


# ─── Identifier normalisation ────────────────────────────────────────────────


def _strip_accessor_prefix(name: str) -> str:
    """Strip Java-style getter/setter/boolean-accessor prefixes.

    getRewardPoints → rewardPoints
    setRewardPoints → rewardPoints
    isActive        → active
    hasPermission   → permission
    """
    for prefix in ("get", "set", "is", "has"):
        plen = len(prefix)
        if len(name) > plen and name[:plen].lower() == prefix:
            rest = name[plen:]
            if rest and rest[0].isupper():
                return rest[0].lower() + rest[1:]
    return name


def normalize_identifier(name: str) -> str:
    """Collapse an identifier to a canonical, comparable form.

    - Strips get/set/is/has accessor prefixes
    - Removes underscores and hyphens (snake_case, kebab-case)
    - Lower-cases everything
    - Does NOT split on camelCase boundaries — equality check is sufficient
      because both sides use the same field name.

    Examples:
      rewardPoints    → rewardpoints
      reward_points   → rewardpoints
      getRewardPoints → rewardpoints
      RewardPoints    → rewardpoints
    """
    name = _strip_accessor_prefix(name)
    return re.sub(r"[_\-]", "", name).lower()


# ─── SCIP symbol leaf extraction ─────────────────────────────────────────────


def extract_symbol_leaf(symbol_id: str) -> str:
    """Return the leaf identifier from a SCIP symbol ID.

    SCIP grammar (simplified):
      <scheme> <manager> <pkg-name> <pkg-version> <descriptors…>
    Descriptor separators: '/' (namespace), '#' (type member), '.' (nested).

    Examples (Java):
      'scip-java maven . . com/example/Foo#rewardPoints.'      → 'rewardPoints'
      'scip-java maven . . com/example/Foo#getRewardPoints().' → 'getRewardPoints'
      'scip-java maven . . com/example/Foo#setAmount().'       → 'setAmount'

    Examples (Python):
      'scip-python . `order_service`/UserResponse#reward_points.' → 'reward_points'

    Examples (TypeScript):
      'scip-typescript npm pkg 1.0.0 src/api/UserResponse#rewardPoints.' → 'rewardPoints'
    """
    if not symbol_id:
        return ""

    # The descriptor block is everything after the 4-token preamble
    # (scheme manager pkg-name pkg-version). Fall back to last token.
    parts = symbol_id.strip().split(" ")
    descriptor = parts[-1] if parts else symbol_id

    # Strip the SCIP terminator dot(s)
    descriptor = descriptor.rstrip(".")

    # Walk to the deepest member: prefer '#' (class member), then '/'
    if "#" in descriptor:
        descriptor = descriptor.rsplit("#", 1)[-1]
    elif "/" in descriptor:
        descriptor = descriptor.rsplit("/", 1)[-1]

    # Strip method argument signature: 'getName(Ljava/lang/String;)' → 'getName'
    paren_idx = descriptor.find("(")
    if paren_idx > 0:
        descriptor = descriptor[:paren_idx]

    # Strip remaining empty parens: 'getName()' → 'getName'
    descriptor = descriptor.rstrip("()")

    # Backtick-quoted Python identifiers: '`reward_points`' → 'reward_points'
    descriptor = descriptor.strip("`")

    return descriptor


# ─── Field FQN leaf extraction ────────────────────────────────────────────────


def _field_leaf_name(fqn: str) -> str:
    """Extract the leaf field name from an OpenAPI FQN.

    'user-service::REST::GET /users/{id}::response.200.rewardPoints' → 'rewardPoints'
    'user-service::REST::POST /orders::request.amount'               → 'amount'
    """
    # FQN structure: service::transport::endpoint::field_path
    field_path = fqn.rsplit("::", 1)[-1] if "::" in fqn else fqn
    # field_path: 'response.200.rewardPoints' → take the last segment
    return field_path.rsplit(".", 1)[-1] if "." in field_path else field_path


# ─── Public API ───────────────────────────────────────────────────────────────


def build_field_index(field_fqns: list[str]) -> dict[str, list[str]]:
    """Build a normalised-leaf-name → [fqn, …] lookup index.

    If multiple fields share the same leaf name (e.g. 'amount' appears on
    several endpoints), they all appear in the list.  The linker returns the
    first match; LLM disambiguation handles the rest later.
    """
    index: dict[str, list[str]] = {}
    for fqn in field_fqns:
        leaf = _field_leaf_name(fqn)
        norm = normalize_identifier(leaf)
        if norm and norm not in _SKIP_IDENTIFIERS and len(norm) >= 2:
            index.setdefault(norm, []).append(fqn)
    logger.debug("symbol_linker field_index built entries=%d", len(index))
    return index


def link_symbol_to_field(
    symbol_id: str,
    field_index: dict[str, list[str]],
) -> Optional[str]:
    """Return the best-matching field FQN for a SCIP symbol ID, or None.

    Phase 1 — leaf-name match (implemented):
      Extract the leaf identifier from the SCIP symbol, normalise it, look
      up in the field index.  Returns None for generic identifiers or when
      no field matches.

    Phase 2 — LLM disambiguation (TODO):
      When multiple fields share the same normalised leaf name, use the
      symbol's containing class / file path as additional context for an LLM
      to pick the right endpoint.
    """
    leaf = extract_symbol_leaf(symbol_id)
    if not leaf or len(leaf) < 2:
        return None

    norm = normalize_identifier(leaf)
    if not norm or norm in _SKIP_IDENTIFIERS or len(norm) < 2:
        return None

    candidates = field_index.get(norm)
    if not candidates:
        return None

    if len(candidates) == 1:
        logger.debug(
            "symbol_linker match symbol_leaf=%s → fqn=%s",
            leaf,
            candidates[0],
        )
        return candidates[0]

    # Multiple candidates: same leaf name on different endpoints.
    # Phase-2 (LLM) hook goes here.  For now return first — they are all
    # plausible usages of fields that share a name.
    logger.debug(
        "symbol_linker ambiguous symbol_leaf=%s candidates=%d → using first",
        leaf,
        len(candidates),
    )
    return candidates[0]
