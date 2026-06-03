# PR Review Comment Redesign

**Date:** 2026-05-31
**Status:** Approved
**Scope:** `ripple/workflows/analyze_pr.py` — two functions only

## Problem

The current PR review generates bloated comments: the top-level body and inline comments both carry the same information (consumer impacts, file:line references, suggested fixes). For 3 breaking changes across 4 services this produces ~35 entries of duplicated detail. Reviewers get overwhelmed; the signal is buried.

## Design

### Principle

Clean separation of concerns:
- **Inline comments** = what broke and why (per-field, per-consumer)
- **Top-level body** = navigation (summary + links to consumer auto-fix PRs)
- **Consumer PRs** = how to fix it

### Top-level review body (`_format_review_comment`)

Single responsibility: navigation. No tables, no impact lists, no fix suggestions.

**Format:**
```
🔴 Ripple: 3 breaking contract change(s) in user-service

Auto-fix PRs raised:
· order-service → PR #2
· recommendation-service → PR #1
· quickbite → PR #1

*[Ripple — semantic contract firewall]*
```

**Rules:**
- Summary line: emoji (🔴/🟡/✅) + count + service name
- Auto-fix PR links if raised, one per consumer service
- No changes → single "✅ No contract changes detected. Safe to merge." line
- Footer link always present

### Inline comments (`_build_inline_comments`)

Fixed 3-part template, strictly enforced. One comment per changed field that has a file+line in the diff.

**Format:**
```
🔴 CRITICAL · ANNOTATION_CHANGE
walletBalance → renamed walletCredit on wire

Breaks:
· order-service (Order.java:26) — deserialization will fail
· quickbite (api.ts:14) — field access returns undefined
```

**Rules:**
- **Line 1:** `{severity_emoji} {SEVERITY} · {CHANGE_TYPE}`
- **Line 2:** one-line description of what changed, max 80 chars. Format: `old → new` when applicable
- **Breaks section:** only breaking consumers. One bullet: `· {service} ({file}:{line}) — {reason}` where reason is capped at 100 chars
- If only non-breaking consumers exist: `· Monitored: order-service, quickbite` (no detail)
- If no consumers at all: `· No known consumers in knowledge graph`
- `suggested_fix` is ignored — fixes live in consumer auto-fix PRs only

## Files Changed

| File | Function | Change |
|------|----------|--------|
| `ripple/workflows/analyze_pr.py` | `_format_review_comment` | Stripped to summary + PR links only |
| `ripple/workflows/analyze_pr.py` | `_build_inline_comments` | Rewritten to strict 3-part template |

`ripple/activities/pr_activities.py` — no changes needed.

## What Is Not Changing

- The PR analysis logic (disagreement detection, blast radius, auto-fix)
- The GitHub API call (`post_github_review_activity`)
- The data passed into these functions — only the rendering changes
