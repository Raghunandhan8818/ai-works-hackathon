# PR Review Comment Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bloated PR review comment format with a lean two-surface design: inline comments carry per-consumer breakage detail, the top-level body carries only the summary + consumer PR links.

**Architecture:** Two pure functions in `ripple/workflows/analyze_pr.py` are rewritten — `_format_review_comment` (top-level body) and `_build_inline_comments` (inline per-field). No other files change. Both functions are pure (no I/O, no side effects) so they can be unit-tested directly.

**Tech Stack:** Python 3.11, pytest

---

### Task 1: Write failing tests for `_format_review_comment`

**Files:**
- Create: `tests/test_pr_review_format.py`

- [ ] **Step 1: Create the test file**

```python
# tests/test_pr_review_format.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ripple.workflows.analyze_pr import _format_review_comment, _build_inline_comments


# ── Fixtures ──────────────────────────────────────────────────────────────────

FIELD_CHANGES = [
    {"field_name": "walletBalance", "change_type": "ANNOTATION_CHANGE", "severity_hint": "CRITICAL",
     "old_description": "walletBalance (integer)", "new_description": "walletCredit (integer)",
     "file_path": "src/main/java/UserDTO.java", "line": 42, "field_fqn": "user-service::walletBalance"},
    {"field_name": "isActive", "change_type": "NULLABLE_CHANGED", "severity_hint": "HIGH",
     "old_description": "non-null boolean", "new_description": "nullable boolean",
     "file_path": "src/main/java/UserDTO.java", "line": 55, "field_fqn": "user-service::isActive"},
]

BREAKING_IMPACTS = [
    {"consumer_service": "order-service", "field_fqn": "user-service::walletBalance",
     "file_path": "src/main/java/OrderService.java", "line": 88,
     "explanation": "deserialization will fail — field no longer exists", "breaks": True},
    {"consumer_service": "quickbite", "field_fqn": "user-service::walletBalance",
     "file_path": "src/screens/Wallet.tsx", "line": 14,
     "explanation": "field access returns undefined", "breaks": True},
]

NON_BREAKING_IMPACTS = [
    {"consumer_service": "order-service", "field_fqn": "user-service::isActive",
     "file_path": "src/main/java/OrderService.java", "line": 22,
     "explanation": "stores field but does not branch on it", "breaks": False},
]

FIX_RESULTS = [
    {"consumer_service": "order-service", "pr_url": "https://github.com/subbikcha/order-service/pull/2"},
    {"consumer_service": "quickbite", "pr_url": "https://github.com/subbikcha/QuickBite/pull/1"},
]


# ── Tests: _format_review_comment ─────────────────────────────────────────────

def test_no_changes_returns_safe_to_merge():
    result = _format_review_comment("user-service", 6, [], [], None)
    assert "✅" in result
    assert "safe to merge" in result.lower()
    # must not contain tables or impact lists
    assert "|" not in result


def test_breaking_summary_line_contains_count_and_service():
    result = _format_review_comment("user-service", 6, FIELD_CHANGES, BREAKING_IMPACTS, None)
    assert "2 breaking" in result
    assert "user-service" in result
    assert "🔴" in result


def test_body_contains_no_impact_table():
    result = _format_review_comment("user-service", 6, FIELD_CHANGES, BREAKING_IMPACTS, FIX_RESULTS)
    # no markdown table rows for consumer impacts
    assert "order-service" not in result or "→" in result  # only allowed in PR link form
    lines_with_pipe = [l for l in result.splitlines() if "|" in l and "Consumer" in l]
    assert lines_with_pipe == [], "Impact table must not appear in body"


def test_fix_results_appear_as_links():
    result = _format_review_comment("user-service", 6, FIELD_CHANGES, BREAKING_IMPACTS, FIX_RESULTS)
    assert "https://github.com/subbikcha/order-service/pull/2" in result
    assert "https://github.com/subbikcha/QuickBite/pull/1" in result


def test_no_fix_results_omits_pr_section():
    result = _format_review_comment("user-service", 6, FIELD_CHANGES, BREAKING_IMPACTS, None)
    assert "pull/" not in result


def test_footer_always_present():
    result = _format_review_comment("user-service", 6, [], [], None)
    assert "Ripple" in result
    result2 = _format_review_comment("user-service", 6, FIELD_CHANGES, BREAKING_IMPACTS, FIX_RESULTS)
    assert "Ripple" in result2


# ── Tests: _build_inline_comments ─────────────────────────────────────────────

def test_inline_skips_fields_without_file_or_line():
    changes_no_location = [
        {"field_name": "walletBalance", "change_type": "ANNOTATION_CHANGE", "severity_hint": "CRITICAL",
         "old_description": "walletBalance", "new_description": "walletCredit",
         "file_path": "", "line": 0, "field_fqn": "user-service::walletBalance"},
    ]
    result = _build_inline_comments(changes_no_location, BREAKING_IMPACTS)
    assert result == []


def test_inline_has_one_entry_per_field_with_location():
    result = _build_inline_comments(FIELD_CHANGES, BREAKING_IMPACTS)
    assert len(result) == 2


def test_inline_body_line1_contains_severity_and_change_type():
    result = _build_inline_comments(FIELD_CHANGES, BREAKING_IMPACTS)
    body = result[0]["body"]
    first_line = body.splitlines()[0]
    assert "CRITICAL" in first_line
    assert "ANNOTATION_CHANGE" in first_line


def test_inline_body_line2_contains_old_and_new_description():
    result = _build_inline_comments(FIELD_CHANGES, BREAKING_IMPACTS)
    body = result[0]["body"]
    second_line = body.splitlines()[1]
    assert "walletBalance" in second_line
    assert "walletCredit" in second_line


def test_inline_breaks_section_lists_consumers():
    result = _build_inline_comments(FIELD_CHANGES, BREAKING_IMPACTS)
    body = result[0]["body"]
    assert "order-service" in body
    assert "quickbite" in body


def test_inline_no_suggested_fix():
    impacts_with_fix = BREAKING_IMPACTS + [
        {"consumer_service": "order-service", "field_fqn": "user-service::walletBalance",
         "file_path": "src/main/java/OrderService.java", "line": 88,
         "explanation": "breaks", "breaks": True,
         "suggested_fix": "Rename field in consumer DTO"},
    ]
    result = _build_inline_comments(FIELD_CHANGES, impacts_with_fix)
    body = result[0]["body"]
    assert "suggested_fix" not in body
    assert "Rename field in consumer DTO" not in body


def test_inline_no_breaking_consumers_shows_monitored():
    result = _build_inline_comments(FIELD_CHANGES, NON_BREAKING_IMPACTS)
    # walletBalance field has no breaking consumers in NON_BREAKING_IMPACTS
    wallet_body = result[0]["body"]
    assert "Monitored" in wallet_body or "No known consumers" in wallet_body


def test_inline_no_consumers_shows_no_known_consumers():
    result = _build_inline_comments(FIELD_CHANGES, [])
    body = result[0]["body"]
    assert "No known consumers" in body


def test_inline_explanation_capped_at_100_chars():
    long_impacts = [
        {"consumer_service": "order-service", "field_fqn": "user-service::walletBalance",
         "file_path": "src/main/java/OrderService.java", "line": 88,
         "explanation": "x" * 200, "breaks": True},
    ]
    result = _build_inline_comments(FIELD_CHANGES, long_impacts)
    body = result[0]["body"]
    # the explanation line should not exceed 100 chars after the dash
    for line in body.splitlines():
        if "— " in line:
            after_dash = line.split("— ", 1)[1]
            assert len(after_dash) <= 100, f"Explanation too long: {after_dash}"
```

- [ ] **Step 2: Run tests to verify they all fail**

```bash
cd /Users/subbikchak/Desktop/Hackathon/ai-works-hackathon
python -m pytest tests/test_pr_review_format.py -v 2>&1 | tail -30
```

Expected: most tests FAIL (current implementation doesn't match new design). Some may pass by coincidence — that's fine.

---

### Task 2: Rewrite `_format_review_comment`

**Files:**
- Modify: `ripple/workflows/analyze_pr.py:440-522`

- [ ] **Step 1: Replace `_format_review_comment` with the lean implementation**

Replace the entire function body (lines 440–522) with:

```python
def _format_review_comment(
    producer_service: str,
    pr_number: int,
    field_changes: list[dict],
    impacts: list[dict],
    fix_results: list[dict] | None = None,
) -> str:
    """Top-level PR review body: summary line + consumer PR links only."""
    if not field_changes:
        return (
            "## Ripple Contract Analysis\n\n"
            "✅ No contract changes detected. Safe to merge.\n\n"
            "*[Ripple — semantic contract firewall]*"
        )

    breaking = [i for i in impacts if i.get("breaks")]
    non_breaking = [i for i in impacts if not i.get("breaks")]
    summary_emoji = "🔴" if breaking else ("🟡" if non_breaking else "✅")

    lines: list[str] = [
        "## Ripple Contract Analysis\n",
        f"{summary_emoji} **{len(breaking)} breaking contract change(s)** in `{producer_service}`\n",
    ]

    successful_fixes = [r for r in (fix_results or []) if r.get("pr_url")]
    if successful_fixes:
        lines.append("**Auto-fix PRs raised:**")
        for r in successful_fixes:
            consumer = r.get("consumer_service", "?")
            pr_url = r.get("pr_url", "")
            lines.append(f"· `{consumer}` → {pr_url}")
        lines.append("")

    failed_fixes = [r for r in (fix_results or []) if not r.get("pr_url")]
    if failed_fixes:
        lines.append("**Could not auto-fix (manual review needed):**")
        for r in failed_fixes:
            lines.append(f"· `{r.get('consumer_service', '?')}`: {r.get('error', 'unknown error')}")
        lines.append("")

    lines.append("*[Ripple — semantic contract firewall]*")
    return "\n".join(lines)
```

- [ ] **Step 2: Run the `_format_review_comment` tests**

```bash
cd /Users/subbikchak/Desktop/Hackathon/ai-works-hackathon
python -m pytest tests/test_pr_review_format.py -v -k "format_review" 2>&1 | tail -20
```

Expected: all `test_*format*` and `test_no_changes*`, `test_breaking_summary*`, `test_body_contains*`, `test_fix_results*`, `test_no_fix*`, `test_footer*` tests PASS.

---

### Task 3: Rewrite `_build_inline_comments`

**Files:**
- Modify: `ripple/workflows/analyze_pr.py:369-434`

- [ ] **Step 1: Replace `_build_inline_comments` with the strict-template implementation**

Replace the entire function body (lines 369–434) with:

```python
def _build_inline_comments(field_changes: list[dict], impacts: list[dict]) -> list[dict]:
    """
    Build GitHub inline review comments — one per changed field that has a file/line.
    Fixed 3-part template: severity header, what changed, which consumers break.
    """
    inline: list[dict] = []

    for change in field_changes:
        file_path = change.get("file_path", "").strip()
        line = change.get("line", 0)
        if not file_path or not line:
            continue

        sev = change.get("severity_hint", "MEDIUM")
        emoji = _SEVERITY_EMOJI.get(sev, "🟡")
        change_type = change.get("change_type", "UNKNOWN")
        old_desc = (change.get("old_description", "") or "")[:80]
        new_desc = (change.get("new_description", "") or "")[:80]

        # Line 1: severity + change type
        body_lines = [f"{emoji} {sev} · {change_type}"]

        # Line 2: what changed
        if old_desc and new_desc:
            body_lines.append(f"{old_desc} → {new_desc}")
        elif new_desc:
            body_lines.append(new_desc)

        body_lines.append("")

        # Breaks section: only breaking consumers for this field
        field_fqn = change.get("field_fqn", "")
        field_impacts = [
            i for i in impacts
            if (not field_fqn or i.get("field_fqn", field_fqn) == field_fqn)
        ] if field_fqn else impacts

        breaking = [i for i in field_impacts if i.get("breaks")]
        non_breaking = [i for i in field_impacts if not i.get("breaks")]

        if breaking:
            body_lines.append("Breaks:")
            for i in breaking:
                consumer = i.get("consumer_service", "?")
                fname = i.get("file_path", "").split("/")[-1]
                lineno = i.get("line", "?")
                explanation = (i.get("explanation", "") or "")[:100]
                body_lines.append(f"· {consumer} ({fname}:{lineno}) — {explanation}")
        elif non_breaking:
            services = ", ".join(sorted({i.get("consumer_service", "?") for i in non_breaking}))
            body_lines.append(f"· Monitored: {services}")
        else:
            body_lines.append("· No known consumers in knowledge graph")

        inline.append({
            "path": file_path,
            "line": line,
            "side": "RIGHT",
            "body": "\n".join(body_lines),
        })

    return inline
```

- [ ] **Step 2: Run all tests**

```bash
cd /Users/subbikchak/Desktop/Hackathon/ai-works-hackathon
python -m pytest tests/test_pr_review_format.py -v 2>&1 | tail -30
```

Expected: ALL tests PASS.

- [ ] **Step 3: Commit**

```bash
cd /Users/subbikchak/Desktop/Hackathon/ai-works-hackathon
git add ripple/workflows/analyze_pr.py tests/test_pr_review_format.py
git commit -m "refactor: lean PR review comments — inline carries breakage detail, body carries PR links only"
```

---

## Self-Review

**Spec coverage:**
- ✅ Top-level body: summary line + PR links only → Task 2
- ✅ No tables or impact lists in body → tested in `test_body_contains_no_impact_table`
- ✅ Inline: severity + what changed + which consumers break → Task 3
- ✅ Explanation capped at 100 chars → tested in `test_inline_explanation_capped_at_100_chars`
- ✅ No `suggested_fix` in inline → tested in `test_inline_no_suggested_fix`
- ✅ Non-breaking → "Monitored" line → tested in `test_inline_no_breaking_consumers_shows_monitored`
- ✅ No consumers → "No known consumers" → tested in `test_inline_no_consumers_shows_no_known_consumers`
- ✅ `post_github_review_activity` untouched — no task needed

**Placeholder scan:** No TBDs, all code complete. ✅

**Type consistency:** `_format_review_comment` and `_build_inline_comments` signatures unchanged — callers in `analyze_pr.py:301-304` need no updates. ✅
