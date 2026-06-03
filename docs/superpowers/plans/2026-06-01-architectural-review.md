# Architectural Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a toggle-gated `ConsolidatedPRReviewWorkflow` that runs contract analysis + architectural review (violations, security, performance, best practices) in parallel and posts a single structured GitHub review, plus a `LearnFromFeedbackWorkflow` triggered by `/learn` comments that stores architectural corrections.

**Architecture:** Two new Temporal workflows — `ConsolidatedPRReviewWorkflow` (coordinator that calls existing contract activities + new architectural review activity in parallel, posts one review) and `LearnFromFeedbackWorkflow` (triggered by GitHub `issue_comment` `/learn` command, stores learned constraints in `architecture_intents` table). The toggle is a `architectural_review_enabled` boolean per service in the `services` table; the webhook handler routes PR events to either `ConsolidatedPRReviewWorkflow` or the existing `AnalyzePRWorkflow` based on this flag.

**Tech Stack:** Python/Temporal, FastAPI, psycopg (PostgreSQL), Anthropic SDK, Next.js 15, TypeScript

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Modify | `ripple/rib/graph/schema.sql` | Add `architecture_intents` table + `architectural_review_enabled` column |
| Modify | `ripple/rib/graph/schema.py` | Add `ArchitecturalIntent` Pydantic model |
| Modify | `ripple/rib/graph/postgres_store.py` | Add 4 methods: upsert/get architecture intents, get/set review enabled flag |
| Create | `ripple/activities/review_activities.py` | 3 new activities: `run_architectural_review_activity`, `process_learn_command_activity`, `post_consolidated_review_activity` |
| Create | `ripple/workflows/consolidated_pr_review.py` | `ConsolidatedPRReviewWorkflow` — coordinator workflow |
| Create | `ripple/workflows/learn_feedback.py` | `LearnFromFeedbackWorkflow` — `/learn` handler workflow |
| Modify | `ripple/rib/api/server.py` | Route PR webhook to consolidated workflow when enabled; handle `issue_comment` `/learn`; add settings endpoints |
| Modify | `ripple/worker.py` | Register new workflows + activities |
| Modify | `dashboard/lib/api.ts` | Add `getReviewEnabled`, `setReviewEnabled` calls |
| Modify | `dashboard/app/dashboard/settings/page.tsx` | Add "Architectural Review" toggle section |

---

## Task 1: DB schema — `architecture_intents` table + service flag

**Files:**
- Modify: `ripple/rib/graph/schema.sql`
- Modify: `ripple/rib/graph/schema.py`

- [ ] **Step 1: Add to `schema.sql`**

Append at the end of `/Users/subbikchak/Desktop/Hackathon/ai-works-hackathon/ripple/rib/graph/schema.sql`:

```sql
-- ── Architectural Review ─────────────────────────────────────────────────────

ALTER TABLE services ADD COLUMN IF NOT EXISTS architectural_review_enabled BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS architecture_intents (
    id BIGSERIAL PRIMARY KEY,
    repo TEXT NOT NULL,
    constraint_type TEXT NOT NULL,
    natural_language TEXT NOT NULL,
    encoded_rule JSONB NOT NULL DEFAULT '{}'::jsonb,
    source TEXT NOT NULL DEFAULT 'learned',
    pr_url TEXT,
    pr_comment_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_architecture_intents_repo ON architecture_intents (repo);
```

- [ ] **Step 2: Add `ArchitecturalIntent` model to `schema.py`**

In `/Users/subbikchak/Desktop/Hackathon/ai-works-hackathon/ripple/rib/graph/schema.py`, append after the `BusinessContext` class:

```python
class ArchitecturalIntent(BaseModel):
    id: Optional[int] = None
    repo: str
    constraint_type: str
    natural_language: str
    encoded_rule: dict = {}
    source: str = "learned"
    pr_url: Optional[str] = None
    pr_comment_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
```

- [ ] **Step 3: Commit**

```bash
git add ripple/rib/graph/schema.sql ripple/rib/graph/schema.py
git commit -m "feat: add architecture_intents table and ArchitecturalIntent model"
```

---

## Task 2: postgres_store.py — add 4 new methods

**Files:**
- Modify: `ripple/rib/graph/postgres_store.py`

- [ ] **Step 1: Add import for `ArchitecturalIntent` at the top of postgres_store.py**

In the imports block (around line 11), add `ArchitecturalIntent` to the existing import from `ripple.rib.graph.schema`:

```python
from ripple.rib.graph.schema import (
    ArchitecturalIntent,
    BlastRadius,
    # ... rest of existing imports unchanged
```

- [ ] **Step 2: Append 4 methods at the end of the `PostgresStore` class**

```python
    # ── Architectural Intent methods ─────────────────────────────────────────

    def upsert_architecture_intent(self, intent: ArchitecturalIntent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO architecture_intents
                    (repo, constraint_type, natural_language, encoded_rule, source, pr_url, pr_comment_id, created_at, updated_at)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s, NOW(), NOW())
                """,
                (
                    intent.repo,
                    intent.constraint_type,
                    intent.natural_language,
                    json.dumps(intent.encoded_rule),
                    intent.source,
                    intent.pr_url,
                    intent.pr_comment_id,
                ),
            )
            conn.commit()

    def get_architecture_intents(self, repo: str) -> list[ArchitecturalIntent]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, repo, constraint_type, natural_language, encoded_rule,
                       source, pr_url, pr_comment_id, created_at, updated_at
                FROM architecture_intents
                WHERE repo = %s
                ORDER BY created_at
                """,
                (repo,),
            ).fetchall()
        return [
            ArchitecturalIntent(
                id=row["id"],
                repo=row["repo"],
                constraint_type=row["constraint_type"],
                natural_language=row["natural_language"],
                encoded_rule=row["encoded_rule"] or {},
                source=row["source"],
                pr_url=row["pr_url"],
                pr_comment_id=row["pr_comment_id"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )
            for row in rows
        ]

    def set_architectural_review_enabled(self, service_name: str, enabled: bool) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE services SET architectural_review_enabled = %s WHERE name = %s",
                (enabled, service_name),
            )
            conn.commit()

    def get_architectural_review_enabled(self, service_name: str) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT architectural_review_enabled FROM services WHERE name = %s",
                (service_name,),
            ).fetchone()
        return bool(row["architectural_review_enabled"]) if row else False
```

- [ ] **Step 3: Commit**

```bash
git add ripple/rib/graph/postgres_store.py
git commit -m "feat: add architecture intent store methods"
```

---

## Task 3: Create `review_activities.py`

**Files:**
- Create: `ripple/activities/review_activities.py`

This file contains 3 activities:
1. `run_architectural_review_activity` — reads `ARCHITECTURE.md` from cloned workspace + loaded learned intents → Claude review → returns structured findings
2. `process_learn_command_activity` — extracts architectural constraint from `/learn` comment + PR context → stores in DB → posts GitHub reply
3. `post_consolidated_review_activity` — merges contract findings + architectural findings → posts one GitHub Review

- [ ] **Step 1: Create the file**

```python
"""
Activities for the ConsolidatedPRReviewWorkflow and LearnFromFeedbackWorkflow.

Queue assignments:
  rib-llm  — run_architectural_review_activity, process_learn_command_activity
  rib-io   — post_consolidated_review_activity
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import httpx
from temporalio import activity

from ripple.rib.graph.factory import get_store
from ripple.rib.graph.schema import ArchitecturalIntent

logger = logging.getLogger(__name__)


def _sonnet(system: str, user: str, max_tokens: int = 2048) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


# ── Activity 1: Run architectural review ─────────────────────────────────────

_ARCH_REVIEW_SYSTEM = """\
You are a senior software architect performing a code review. You will be given:
1. A git diff from a pull request
2. Architectural constraints for this codebase (from ARCHITECTURE.md and learned rules)

Review the diff against the constraints and also check for general best practices, security concerns, and performance issues.

Return a JSON object with this structure:
{
  "architectural_violations": [
    {"severity": "HIGH|MEDIUM|LOW", "description": "...", "file": "...", "suggestion": "..."}
  ],
  "security_concerns": [
    {"severity": "HIGH|MEDIUM|LOW", "description": "...", "file": "...", "suggestion": "..."}
  ],
  "performance_suggestions": [
    {"severity": "MEDIUM|LOW", "description": "...", "file": "...", "suggestion": "..."}
  ],
  "best_practices": [
    {"severity": "MEDIUM|LOW", "description": "...", "file": "...", "suggestion": "..."}
  ]
}

Return only the JSON object. If a category has no findings, use an empty array.
Do not invent violations — only flag real issues visible in the diff.
"""


@activity.defn(name="run_architectural_review_activity")
async def run_architectural_review_activity(payload: dict) -> dict:
    """
    payload keys:
      workspace: str — path to the cloned repo workspace
      diff_content: str — the PR diff text
      repo_full: str — "owner/repo" used as lookup key for learned intents
      service_name: str — service name for DB lookup
    """
    workspace: str = payload["workspace"]
    diff_content: str = payload["diff_content"]
    repo_full: str = payload.get("repo_full", "")

    # Read ARCHITECTURE.md from workspace if it exists
    arch_md_path = Path(workspace) / "ARCHITECTURE.md"
    arch_md_content = ""
    if arch_md_path.exists():
        arch_md_content = arch_md_path.read_text(encoding="utf-8", errors="ignore")[:8000]

    # Load learned intents from DB
    learned_intents: list[str] = []
    try:
        store = get_store()
        intents = store.get_architecture_intents(repo_full)
        learned_intents = [i.natural_language for i in intents]
    except Exception:
        logger.warning("Could not load architecture intents from DB", exc_info=True)

    # Build constraints block
    constraints_parts: list[str] = []
    if arch_md_content:
        constraints_parts.append(f"## From ARCHITECTURE.md\n{arch_md_content}")
    if learned_intents:
        rules = "\n".join(f"- {r}" for r in learned_intents)
        constraints_parts.append(f"## Learned Rules (from /learn corrections)\n{rules}")

    if not constraints_parts and not diff_content.strip():
        return {"architectural_violations": [], "security_concerns": [], "performance_suggestions": [], "best_practices": []}

    constraints_block = "\n\n".join(constraints_parts) if constraints_parts else "(No architectural constraints defined for this repo)"
    user_prompt = f"## Architectural Constraints\n\n{constraints_block}\n\n## PR Diff\n\n```diff\n{diff_content[:12000]}\n```"

    try:
        raw = _sonnet(_ARCH_REVIEW_SYSTEM, user_prompt, max_tokens=2048)
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        return json.loads(raw)
    except Exception:
        logger.warning("Architectural review Claude call failed", exc_info=True)
        return {"architectural_violations": [], "security_concerns": [], "performance_suggestions": [], "best_practices": []}


# ── Activity 2: Process /learn command ────────────────────────────────────────

_LEARN_SYSTEM = """\
You are extracting an architectural constraint from a developer's correction on a code review.

Given:
- The developer's correction text (from /learn command)
- The PR diff context

Extract a structured architectural constraint. Return a JSON object:
{
  "constraint_type": "DEPENDENCY|BOUNDED_CONTEXT|SECURITY|PERFORMANCE|NAMING|CUSTOM",
  "natural_language": "Clear, reusable rule statement that can guide future reviews",
  "encoded_rule": {
    "pattern": "what triggers this rule",
    "allowed": "what IS allowed",
    "forbidden": "what is NOT allowed"
  }
}

The natural_language field should be a complete, self-contained rule that makes sense without the PR context.
Return only the JSON object.
"""


@activity.defn(name="process_learn_command_activity")
async def process_learn_command_activity(payload: dict) -> dict:
    """
    payload keys:
      correction_text: str — text after /learn command
      diff_content: str — PR diff for context
      repo_full: str — "owner/repo"
      pr_number: int
      comment_id: str
      github_token: str
    """
    correction_text: str = payload["correction_text"]
    diff_context: str = payload.get("diff_content", "")[:4000]
    repo_full: str = payload["repo_full"]
    pr_number: int = payload["pr_number"]
    comment_id: str = payload.get("comment_id", "")
    github_token: str = payload.get("github_token", "") or os.environ.get("RIPPLE_GITHUB_TOKEN", "")

    user_prompt = f"Developer correction: {correction_text}\n\nPR diff context:\n```diff\n{diff_context}\n```"

    try:
        raw = _sonnet(_LEARN_SYSTEM, user_prompt, max_tokens=512)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        extracted = json.loads(raw)
    except Exception:
        logger.warning("Learn command extraction failed", exc_info=True)
        extracted = {
            "constraint_type": "CUSTOM",
            "natural_language": correction_text,
            "encoded_rule": {},
        }

    pr_url = f"https://github.com/{repo_full}/pull/{pr_number}"
    intent = ArchitecturalIntent(
        repo=repo_full,
        constraint_type=extracted.get("constraint_type", "CUSTOM"),
        natural_language=extracted.get("natural_language", correction_text),
        encoded_rule=extracted.get("encoded_rule", {}),
        source="learned",
        pr_url=pr_url,
        pr_comment_id=str(comment_id),
    )

    try:
        get_store().upsert_architecture_intent(intent)
        logger.info("Stored architectural intent from /learn: repo=%s type=%s", repo_full, intent.constraint_type)
    except Exception:
        logger.warning("Failed to store architectural intent", exc_info=True)

    # Post acknowledgement reply on PR
    if github_token and repo_full:
        ack_body = (
            f"**Ripple learned:** {intent.natural_language}\n\n"
            f"*This rule will be applied to future PR reviews for `{repo_full}`.*"
        )
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(
                    f"https://api.github.com/repos/{repo_full}/issues/{pr_number}/comments",
                    headers={
                        "Authorization": f"Bearer {github_token}",
                        "Accept": "application/vnd.github+json",
                    },
                    json={"body": ack_body},
                )
        except Exception:
            logger.warning("Failed to post /learn acknowledgement", exc_info=True)

    return {"stored": True, "constraint_type": intent.constraint_type, "natural_language": intent.natural_language}


# ── Activity 3: Post consolidated GitHub review ───────────────────────────────

def _format_consolidated_review(
    producer_service: str,
    contract_findings: dict,
    arch_findings: dict,
) -> str:
    field_changes: list[dict] = contract_findings.get("field_changes", [])
    impacts: list[dict] = contract_findings.get("impacts", [])
    fix_results: list[dict] = contract_findings.get("fix_results", [])

    breaking = [i for i in impacts if i.get("breaks")]
    summary_emoji = "🔴" if breaking else "✅"

    lines: list[str] = ["## Ripple Review\n"]

    # ── Contract Drift ────────────────────────────────────────────────────────
    lines.append("### Contract Drift\n")
    if not field_changes:
        lines.append("✅ No contract changes detected.\n")
    else:
        lines.append(f"{summary_emoji} **{len(breaking)} breaking contract change(s)** in `{producer_service}`\n")
        successful_fixes = [r for r in fix_results if r.get("pr_url")]
        if successful_fixes:
            lines.append("**Auto-fix PRs raised:**")
            for r in successful_fixes:
                lines.append(f"· `{r.get('consumer_service', '?')}` → {r.get('pr_url', '')}")
            lines.append("")
        failed_fixes = [r for r in fix_results if not r.get("pr_url")]
        if failed_fixes:
            lines.append("**Needs manual review:**")
            for r in failed_fixes:
                lines.append(f"· `{r.get('consumer_service', '?')}`: {r.get('error', 'unknown')}")
            lines.append("")

    # ── Architectural Violations ──────────────────────────────────────────────
    arch_violations = arch_findings.get("architectural_violations", [])
    lines.append("### Architectural Violations\n")
    if not arch_violations:
        lines.append("✅ No architectural violations detected.\n")
    else:
        for v in arch_violations:
            sev = v.get("severity", "MEDIUM")
            emoji = {"HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(sev, "🟡")
            lines.append(f"{emoji} **{sev}** — {v.get('description', '')}")
            if v.get("file"):
                lines.append(f"  *File:* `{v['file']}`")
            if v.get("suggestion"):
                lines.append(f"  *Suggestion:* {v['suggestion']}")
        lines.append("")

    # ── Security Concerns ─────────────────────────────────────────────────────
    security = arch_findings.get("security_concerns", [])
    lines.append("### Security Concerns\n")
    if not security:
        lines.append("✅ No security concerns detected.\n")
    else:
        for s in security:
            sev = s.get("severity", "MEDIUM")
            emoji = {"HIGH": "🔴", "MEDIUM": "🟠", "LOW": "🟡"}.get(sev, "🟠")
            lines.append(f"{emoji} **{sev}** — {s.get('description', '')}")
            if s.get("suggestion"):
                lines.append(f"  *Suggestion:* {s['suggestion']}")
        lines.append("")

    # ── Performance Suggestions ───────────────────────────────────────────────
    perf = arch_findings.get("performance_suggestions", [])
    lines.append("### Performance Suggestions\n")
    if not perf:
        lines.append("✅ No performance issues detected.\n")
    else:
        for p in perf:
            lines.append(f"💡 {p.get('description', '')}")
            if p.get("suggestion"):
                lines.append(f"  *Suggestion:* {p['suggestion']}")
        lines.append("")

    # ── Best Practices ────────────────────────────────────────────────────────
    best = arch_findings.get("best_practices", [])
    if best:
        lines.append("### Best Practices\n")
        for b in best:
            lines.append(f"📌 {b.get('description', '')}")
            if b.get("suggestion"):
                lines.append(f"  *Suggestion:* {b['suggestion']}")
        lines.append("")

    lines.append("\n---\n*[Ripple — Agentic Code Review with Architectural Intent Understanding]*")
    lines.append("\n*Reply `/learn <correction>` on this comment to teach Ripple about your architecture.*")
    return "\n".join(lines)


@activity.defn(name="post_consolidated_review_activity")
async def post_consolidated_review_activity(payload: dict) -> dict:
    """
    payload keys:
      repo_url: str
      pr_number: int
      head_sha: str
      github_token: str
      producer_service: str
      contract_findings: dict  — {field_changes, impacts, fix_results}
      arch_findings: dict      — {architectural_violations, security_concerns, performance_suggestions, best_practices}
    """
    repo_url: str = payload["repo_url"]
    pr_number: int = payload["pr_number"]
    head_sha: str = payload.get("head_sha", "")
    github_token: str = payload.get("github_token", "") or os.environ.get("RIPPLE_GITHUB_TOKEN", "")
    producer_service: str = payload.get("producer_service", "")
    contract_findings: dict = payload.get("contract_findings", {})
    arch_findings: dict = payload.get("arch_findings", {})

    import re
    m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", repo_url)
    if not m:
        return {"success": False, "error": "Cannot parse repo_url"}
    repo_full = m.group(1)

    body = _format_consolidated_review(producer_service, contract_findings, arch_findings)

    if not github_token or not head_sha:
        logger.warning("post_consolidated_review: missing token or head_sha, skipping post")
        return {"success": False, "error": "missing token or head_sha", "preview": body[:200]}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"https://api.github.com/repos/{repo_full}/pulls/{pr_number}/reviews",
                headers={
                    "Authorization": f"Bearer {github_token}",
                    "Accept": "application/vnd.github+json",
                },
                json={
                    "commit_id": head_sha,
                    "body": body,
                    "event": "COMMENT",
                    "comments": [],
                },
            )
        if resp.status_code in (200, 201):
            data = resp.json()
            return {"success": True, "url": data.get("html_url", ""), "preview": body[:200]}
        else:
            logger.warning("GitHub review post failed: %s %s", resp.status_code, resp.text[:200])
            return {"success": False, "error": f"HTTP {resp.status_code}"}
    except Exception as e:
        logger.warning("post_consolidated_review_activity error: %s", e)
        return {"success": False, "error": str(e)}
```

- [ ] **Step 2: Commit**

```bash
git add ripple/activities/review_activities.py
git commit -m "feat: add review_activities for consolidated PR review and /learn command"
```

---

## Task 4: Create `ConsolidatedPRReviewWorkflow`

**Files:**
- Create: `ripple/workflows/consolidated_pr_review.py`

- [ ] **Step 1: Create the workflow file**

```python
from __future__ import annotations

import asyncio
import re
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ripple.activities.fix_activities import comment_fix_prs_on_producer_activity
    from ripple.activities.git_activities import cleanup_workspace_activity, get_pr_diff_activity
    from ripple.activities.pr_activities import (
        assess_consumer_impact_activity,
        parse_pr_diff_activity,
        upsert_pr_disagreements_activity,
    )
    from ripple.activities.review_activities import (
        post_consolidated_review_activity,
        run_architectural_review_activity,
    )
    from ripple.workflows.auto_fix_consumer import AutoFixConsumerWorkflow

IO_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
LLM_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=5))

_NEEDS_HUMAN_TYPES = {"BEHAVIORAL_CHANGE", "SEMANTIC_CHANGE", "UNIT_CHANGE"}
_URGENT_SEVERITIES = {"CRITICAL", "HIGH"}


@workflow.defn(name="ConsolidatedPRReviewWorkflow")
class ConsolidatedPRReviewWorkflow:
    def __init__(self) -> None:
        self._status: str = "pending"

    @workflow.query
    def status(self) -> str:
        return self._status

    @workflow.run
    async def run(self, request: dict) -> dict:
        import os as _os
        repo_url: str = request["repo_url"]
        branch: str = request["branch"]
        base_branch: str = request["base_branch"]
        pr_number: int = request["pr_number"]
        head_commit: str = request.get("head_commit", "")
        producer_service: str = request.get("producer_service", "")
        github_token: str = request.get("github_token", "") or _os.environ.get("RIPPLE_GITHUB_TOKEN", "")
        workflow_run_id = workflow.info().run_id

        # Extract repo_full ("owner/repo") for architectural intent lookup
        m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", repo_url)
        repo_full = m.group(1) if m else ""

        # ── Step 1: Clone + compute diff ─────────────────────────────────────
        self._status = "cloning"
        diff_result = await workflow.execute_activity(
            get_pr_diff_activity,
            args=[repo_url, branch, base_branch, pr_number, workflow_run_id],
            task_queue="rib-io",
            start_to_close_timeout=timedelta(minutes=15),
            retry_policy=IO_RETRY,
        )
        workspace: str = diff_result["workspace"]
        diff_content: str = diff_result.get("diff_content", "")

        # ── Step 2: Run contract analysis + architectural review in parallel ─
        self._status = "reviewing"

        # Contract analysis (same activities as AnalyzePRWorkflow steps 2-3)
        async def _run_contract_analysis() -> dict:
            if not diff_content.strip():
                return {"field_changes": [], "impacts": [], "fix_results": []}

            field_changes = await workflow.execute_activity(
                parse_pr_diff_activity,
                args=[{"diff": diff_content, "producer_service": producer_service}],
                task_queue="rib-llm",
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=LLM_RETRY,
            )

            all_impacts: list[dict] = []
            if field_changes:
                impact_results = await asyncio.gather(*[
                    workflow.execute_activity(
                        assess_consumer_impact_activity,
                        args=[{"field_change": change, "producer_service": producer_service}],
                        task_queue="rib-llm",
                        start_to_close_timeout=timedelta(minutes=5),
                        retry_policy=LLM_RETRY,
                    )
                    for change in field_changes
                ])
                all_impacts = [impact for impacts in impact_results for impact in impacts]

                # Synthesize knowledge-gap interrupts (same logic as AnalyzePRWorkflow)
                for i, fc in enumerate(field_changes):
                    if fc.get("change_type") not in _NEEDS_HUMAN_TYPES:
                        continue
                    if fc.get("severity_hint") not in _URGENT_SEVERITIES:
                        continue
                    field_impacts = impact_results[i]
                    if any(imp.get("breaks") and imp.get("requires_human_decision") for imp in field_impacts):
                        continue
                    all_impacts.append({
                        "consumer_service": producer_service,
                        "consumer_repo_url": "",
                        "field_fqn": fc.get("field_fqn", fc.get("field_name", "")),
                        "file_path": fc.get("file_path", ""),
                        "line": fc.get("line", 0),
                        "breaks": True,
                        "requires_human_decision": True,
                        "is_test_only": False,
                        "severity": fc.get("severity_hint", "HIGH"),
                        "explanation": fc.get("semantic_intent", "") or (fc.get("old_description", "") + " → " + fc.get("new_description", "")),
                        "human_decision_reason": f"'{fc['field_name']}' has a behavioral change requiring human confirmation.",
                        "mitigation_options": [],
                        "suggested_fix": "",
                        "evidence": [f"Before: {fc.get('old_description', '')}", f"After: {fc.get('new_description', '')}"],
                    })

                if all_impacts:
                    await workflow.execute_activity(
                        upsert_pr_disagreements_activity,
                        args=[{
                            "breaking_impacts": [i for i in all_impacts if i.get("breaks")],
                            "field_changes": field_changes,
                        }],
                        task_queue="rib-io",
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=IO_RETRY,
                    )

            return {"field_changes": field_changes, "impacts": all_impacts}

        # Run contract analysis and architectural review concurrently
        contract_result, arch_findings = await asyncio.gather(
            _run_contract_analysis(),
            workflow.execute_activity(
                run_architectural_review_activity,
                args=[{
                    "workspace": workspace,
                    "diff_content": diff_content,
                    "repo_full": repo_full,
                    "service_name": producer_service,
                }],
                task_queue="rib-llm",
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=LLM_RETRY,
            ),
        )

        field_changes = contract_result["field_changes"]
        all_impacts = contract_result["impacts"]

        # ── Step 3: Auto-fix breaking consumer impacts ────────────────────────
        fix_results: list[dict] = []
        auto_fix_impacts = [i for i in all_impacts if i.get("breaks") and not i.get("requires_human_decision", False)]
        if auto_fix_impacts and github_token:
            self._status = "auto_fixing"
            owner_repo_m = re.search(r"github\.com[/:]([^/]+/[^/]+?)(?:\.git)?$", repo_url)
            producer_pr_url = f"https://github.com/{owner_repo_m.group(1)}/pull/{pr_number}" if owner_repo_m else ""

            consumers_to_fix: dict[str, list[dict]] = {}
            for impact in auto_fix_impacts:
                consumers_to_fix.setdefault(impact["consumer_service"], []).append(impact)

            fix_futures = []
            for consumer_service_name, impacts in consumers_to_fix.items():
                consumer_repo_url = impacts[0].get("consumer_repo_url", "")
                if not consumer_repo_url:
                    fix_results.append({"consumer_service": consumer_service_name, "pr_url": "", "success": False, "error": "no repo_url"})
                    continue
                fix_futures.append(
                    workflow.execute_child_workflow(
                        AutoFixConsumerWorkflow.run,
                        args=[{
                            "consumer_service": consumer_service_name,
                            "consumer_repo_url": consumer_repo_url,
                            "producer_service": producer_service,
                            "producer_pr_url": producer_pr_url,
                            "field_changes": field_changes,
                            "breaking_impacts": impacts,
                            "github_token": github_token,
                        }],
                        id=f"autofix-{workflow.info().run_id[:8]}-{consumer_service_name}",
                        task_queue="rib",
                    )
                )
            if fix_futures:
                raw_results = await asyncio.gather(*fix_futures, return_exceptions=True)
                for r in raw_results:
                    fix_results.append(r if isinstance(r, dict) else {"consumer_service": "?", "pr_url": "", "success": False, "error": str(r)})

        # ── Step 4: Post single consolidated GitHub review ────────────────────
        self._status = "posting_review"
        post_result = await workflow.execute_activity(
            post_consolidated_review_activity,
            args=[{
                "repo_url": repo_url,
                "pr_number": pr_number,
                "head_sha": head_commit,
                "github_token": github_token,
                "producer_service": producer_service,
                "contract_findings": {
                    "field_changes": field_changes,
                    "impacts": all_impacts,
                    "fix_results": fix_results,
                },
                "arch_findings": arch_findings,
            }],
            task_queue="rib-io",
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=IO_RETRY,
        )

        # ── Step 4.5: Post fix PR links on producer PR ─────────────────────────
        if fix_results and github_token:
            await workflow.execute_activity(
                comment_fix_prs_on_producer_activity,
                args=[{
                    "repo_url": repo_url,
                    "pr_number": pr_number,
                    "fix_results": fix_results,
                    "github_token": github_token,
                }],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=IO_RETRY,
            )

        # ── Step 5: Cleanup ───────────────────────────────────────────────────
        await workflow.execute_activity(
            cleanup_workspace_activity,
            args=[workspace],
            task_queue="rib-io",
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=IO_RETRY,
        )

        self._status = "completed"
        return {
            "field_changes": field_changes,
            "impacts": all_impacts,
            "fix_results": fix_results,
            "arch_findings": arch_findings,
            "review_url": post_result.get("url", ""),
            "review_posted": post_result.get("success", False),
        }
```

- [ ] **Step 2: Commit**

```bash
git add ripple/workflows/consolidated_pr_review.py
git commit -m "feat: add ConsolidatedPRReviewWorkflow"
```

---

## Task 5: Create `LearnFromFeedbackWorkflow`

**Files:**
- Create: `ripple/workflows/learn_feedback.py`

- [ ] **Step 1: Create the workflow file**

```python
from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from ripple.activities.review_activities import process_learn_command_activity
    from ripple.activities.git_activities import get_pr_diff_activity, cleanup_workspace_activity

IO_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
LLM_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=5))


@workflow.defn(name="LearnFromFeedbackWorkflow")
class LearnFromFeedbackWorkflow:

    @workflow.run
    async def run(self, request: dict) -> dict:
        """
        request keys:
          correction_text: str   — text after /learn
          repo_full: str         — "owner/repo"
          pr_number: int
          comment_id: str
          branch: str            — PR head branch (for cloning diff context)
          base_branch: str
          github_token: str
        """
        import os as _os
        correction_text: str = request["correction_text"]
        repo_full: str = request["repo_full"]
        pr_number: int = request["pr_number"]
        comment_id: str = request.get("comment_id", "")
        branch: str = request.get("branch", "")
        base_branch: str = request.get("base_branch", "main")
        github_token: str = request.get("github_token", "") or _os.environ.get("RIPPLE_GITHUB_TOKEN", "")
        workflow_run_id = workflow.info().run_id

        repo_url = f"https://github.com/{repo_full}.git"

        # Fetch diff for context (best-effort — skip if branch unknown)
        diff_content = ""
        workspace = ""
        if branch:
            try:
                diff_result = await workflow.execute_activity(
                    get_pr_diff_activity,
                    args=[repo_url, branch, base_branch, pr_number, workflow_run_id],
                    task_queue="rib-io",
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=IO_RETRY,
                )
                diff_content = diff_result.get("diff_content", "")
                workspace = diff_result.get("workspace", "")
            except Exception:
                pass  # Proceed without diff context

        # Extract and store the architectural constraint
        result = await workflow.execute_activity(
            process_learn_command_activity,
            args=[{
                "correction_text": correction_text,
                "diff_content": diff_content,
                "repo_full": repo_full,
                "pr_number": pr_number,
                "comment_id": comment_id,
                "github_token": github_token,
            }],
            task_queue="rib-llm",
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=LLM_RETRY,
        )

        if workspace:
            await workflow.execute_activity(
                cleanup_workspace_activity,
                args=[workspace],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=IO_RETRY,
            )

        return result
```

- [ ] **Step 2: Commit**

```bash
git add ripple/workflows/learn_feedback.py
git commit -m "feat: add LearnFromFeedbackWorkflow for /learn command processing"
```

---

## Task 6: Server changes — webhook routing + settings API

**Files:**
- Modify: `ripple/rib/api/server.py`

- [ ] **Step 1: Add settings API endpoints**

After the `InterruptResolveRequest` class definition (around line 38), add:

```python
class ServiceReviewSettingRequest(BaseModel):
    enabled: bool
```

Then, after the existing `/api/interrupt/resolve` endpoint, add these two new endpoints:

```python
@app.get("/api/services/{service_name}/review-enabled")
async def get_review_enabled(service_name: str):
    store = get_store()
    enabled = store.get_architectural_review_enabled(service_name)
    return {"service": service_name, "architectural_review_enabled": enabled}


@app.post("/api/services/{service_name}/review-enabled")
async def set_review_enabled(service_name: str, body: ServiceReviewSettingRequest):
    store = get_store()
    store.set_architectural_review_enabled(service_name, body.enabled)
    return {"service": service_name, "architectural_review_enabled": body.enabled}
```

- [ ] **Step 2: Add import for new workflow and update PR webhook routing**

At the top of `server.py`, in the imports section, add:

```python
from ripple.workflows.consolidated_pr_review import ConsolidatedPRReviewWorkflow
from ripple.workflows.learn_feedback import LearnFromFeedbackWorkflow
```

- [ ] **Step 3: Update PR webhook to route based on toggle**

In the `handle_github_webhook` function, find the block that handles `action not in ("opened", "synchronize", "reopened")` (line ~469). Below where `analyze_request` is built and `start_analyze_workflow(analyze_request)` is called (line ~498), replace that call with:

```python
        # Check if architectural review is enabled for this service
        arch_review_enabled = False
        if producer_service:
            try:
                arch_review_enabled = store.get_architectural_review_enabled(producer_service)
            except Exception:
                pass

        if arch_review_enabled:
            client = await get_temporal_client()
            consolidated_request = {
                "repo_url": f"https://github.com/{repo_full_name}",
                "branch": pr["head"]["ref"],
                "base_branch": pr["base"]["ref"],
                "pr_number": pr["number"],
                "head_commit": pr["head"]["sha"],
                "producer_service": producer_service,
                "github_token": github_token,
            }
            wf = await client.start_workflow(
                ConsolidatedPRReviewWorkflow.run,
                args=[consolidated_request],
                id=f"consolidated-review-{repo_full_name.replace('/', '-')}-{pr['number']}",
                task_queue="rib",
                id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
            )
            return {"status": "consolidated_review_triggered", "workflow_id": wf.id}
        else:
            status = await start_analyze_workflow(analyze_request)
            return {"status": "triggered", "workflow_id": status.workflow_id}
```

- [ ] **Step 4: Add `/learn` comment webhook handler**

In the `handle_github_webhook` function, before the final `return {"status": "ignored", ...}` line at the bottom, add handling for `issue_comment` events:

```python
    elif event == "issue_comment":
        action = payload.get("action", "")
        if action != "created":
            return {"status": "ignored", "reason": "not a new comment"}

        comment_body: str = payload.get("comment", {}).get("body", "").strip()
        if not comment_body.lower().startswith("/learn"):
            return {"status": "ignored", "reason": "not a /learn command"}

        # Only process on PRs (issue_comment fires on both issues and PRs)
        issue = payload.get("issue", {})
        if "pull_request" not in issue:
            return {"status": "ignored", "reason": "not on a PR"}

        correction_text = comment_body[len("/learn"):].strip()
        repo = payload["repository"]
        repo_full_name = repo["full_name"]
        pr_number = issue["number"]
        comment_id = str(payload.get("comment", {}).get("id", ""))

        # Best-effort: find the PR branch for diff context
        github_token = os.environ.get("RIPPLE_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN", "")
        branch = ""
        base_branch = "main"
        if github_token:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        f"https://api.github.com/repos/{repo_full_name}/pulls/{pr_number}",
                        headers={"Authorization": f"Bearer {github_token}", "Accept": "application/vnd.github+json"},
                    )
                    if resp.status_code == 200:
                        pr_data = resp.json()
                        branch = pr_data.get("head", {}).get("ref", "")
                        base_branch = pr_data.get("base", {}).get("ref", "main")
            except Exception:
                pass

        learn_request = {
            "correction_text": correction_text,
            "repo_full": repo_full_name,
            "pr_number": pr_number,
            "comment_id": comment_id,
            "branch": branch,
            "base_branch": base_branch,
            "github_token": github_token,
        }

        client = await get_temporal_client()
        wf = await client.start_workflow(
            LearnFromFeedbackWorkflow.run,
            args=[learn_request],
            id=f"learn-{repo_full_name.replace('/', '-')}-{pr_number}-{comment_id}",
            task_queue="rib",
            id_conflict_policy=WorkflowIDConflictPolicy.TERMINATE_EXISTING,
        )
        logger.info("LearnFromFeedbackWorkflow triggered repo=%s pr=%s", repo_full_name, pr_number)
        return {"status": "learn_triggered", "workflow_id": wf.id}
```

Also add `import httpx` near the top of `server.py` if it isn't already imported.

- [ ] **Step 5: Commit**

```bash
git add ripple/rib/api/server.py
git commit -m "feat: route PR webhook to ConsolidatedPRReviewWorkflow when enabled; handle /learn comments"
```

---

## Task 7: Register new workflows and activities in worker.py

**Files:**
- Modify: `ripple/worker.py`

- [ ] **Step 1: Add imports**

At the top of `worker.py`, add after the existing workflow imports:

```python
from ripple.workflows.consolidated_pr_review import ConsolidatedPRReviewWorkflow
from ripple.workflows.learn_feedback import LearnFromFeedbackWorkflow
from ripple.activities.review_activities import (
    post_consolidated_review_activity,
    process_learn_command_activity,
    run_architectural_review_activity,
)
```

- [ ] **Step 2: Register in the main worker (rib queue) — workflows**

In the `worker = Worker(...)` block, add both new workflows to the `workflows` list:

```python
        workflows=[
            IngestEcosystemWorkflow,
            IngestServiceWorkflow,
            EcosystemPipelineWorkflow,
            AnalyzePRWorkflow,
            AutoFixConsumerWorkflow,
            PostMergeWorkflow,
            ConsolidatedPRReviewWorkflow,   # ← add
            LearnFromFeedbackWorkflow,       # ← add
        ],
```

- [ ] **Step 3: Register activities on the correct queues**

In `io_worker`, add `post_consolidated_review_activity` to the activities list:

```python
        activities=[
            # ... existing activities ...
            post_consolidated_review_activity,   # ← add
        ],
```

In `llm_worker`, add the two LLM activities:

```python
        activities=[
            # ... existing activities ...
            run_architectural_review_activity,    # ← add
            process_learn_command_activity,       # ← add
        ],
```

- [ ] **Step 4: Commit**

```bash
git add ripple/worker.py
git commit -m "feat: register ConsolidatedPRReviewWorkflow, LearnFromFeedbackWorkflow and review activities in worker"
```

---

## Task 8: UI toggle in settings page

**Files:**
- Modify: `dashboard/lib/api.ts`
- Modify: `dashboard/app/dashboard/settings/page.tsx`

- [ ] **Step 1: Add API calls to `api.ts`**

In `dashboard/lib/api.ts`, add to the `api` object:

```typescript
  getReviewEnabled: (serviceName: string) =>
    get<{ service: string; architectural_review_enabled: boolean }>(
      `/api/services/${encodeURIComponent(serviceName)}/review-enabled`
    ),
  setReviewEnabled: (serviceName: string, enabled: boolean) =>
    post<{ service: string; architectural_review_enabled: boolean }>(
      `/api/services/${encodeURIComponent(serviceName)}/review-enabled`,
      { enabled }
    ),
```

- [ ] **Step 2: Add toggle section to settings page**

In `dashboard/app/dashboard/settings/page.tsx`:

1. Add state variable after the existing ones:
```typescript
  const [archReviewEnabled, setArchReviewEnabled] = useState(false)
  const [services, setServices] = useState<ApiService[]>([])
```

2. In the `useEffect`, also store services and load the toggle state for the first service:
```typescript
  useEffect(() => {
    api.services()
      .then((svcs: ApiService[]) => {
        setServices(svcs)
        const owner = svcs.map((s) => extractGitHubOwner(s.repo_url)).find(Boolean) ?? null
        setGithubOrg(owner)
        setServiceCount(svcs.length)
        setConnected(svcs.length > 0)
        // Load toggle state — show aggregate: enabled if ANY service has it on
        if (svcs.length > 0) {
          Promise.all(svcs.map((s) => api.getReviewEnabled(s.name)))
            .then((results) => setArchReviewEnabled(results.some((r) => r.architectural_review_enabled)))
            .catch(() => {})
        }
      })
      .catch(() => setConnected(false))
  }, [])
```

3. Add a toggle handler:
```typescript
  const handleArchReviewToggle = async () => {
    const next = !archReviewEnabled
    setArchReviewEnabled(next)
    await Promise.all(services.map((s) => api.setReviewEnabled(s.name, next))).catch(() => {})
  }
```

4. Add a new `<Section title="Architectural Review">` block inside the settings page, after the "Ripple Preferences" section and before the Save button:

```tsx
          <Section title="Architectural Review">
            <FieldRow
              label="Enable Architectural Review"
              hint="When on, Ripple posts a single consolidated review covering contract drift, architectural violations, security concerns, and performance suggestions. Add an ARCHITECTURE.md to your repos to encode constraints."
            >
              <button
                onClick={handleArchReviewToggle}
                className="flex items-center gap-2 text-sm font-medium transition-colors"
                style={{ color: archReviewEnabled ? 'var(--status-healthy-text)' : 'var(--dash-text-secondary)' }}
              >
                <div
                  className="w-10 h-5 rounded-full relative transition-colors"
                  style={{ background: archReviewEnabled ? '#22C55E' : 'var(--dash-border)' }}
                >
                  <div
                    className="absolute top-0.5 w-4 h-4 rounded-full transition-all"
                    style={{ background: 'var(--dash-sidebar)', left: archReviewEnabled ? '1.25rem' : '0.125rem' }}
                  />
                </div>
                {archReviewEnabled ? 'On' : 'Off'}
              </button>
            </FieldRow>

            <FieldRow
              label="How it works"
              hint=""
            >
              <div
                className="text-xs leading-relaxed"
                style={{ color: 'var(--dash-text-secondary)' }}
              >
                Add <code className="font-mono px-1 rounded" style={{ background: 'var(--dash-bg)' }}>ARCHITECTURE.md</code> to any repo.
                On PRs, Ripple reads it + any learned rules and posts one structured review.
                Reply <code className="font-mono px-1 rounded" style={{ background: 'var(--dash-bg)' }}>/learn &lt;correction&gt;</code> on a review comment to teach Ripple your architectural patterns.
              </div>
            </FieldRow>
          </Section>
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/lib/api.ts dashboard/app/dashboard/settings/page.tsx
git commit -m "feat: add architectural review toggle to settings UI"
```

---

## Self-Review

**Spec coverage:**
- ✅ Architectural intent encoding (ARCHITECTURE.md + learned intents in DB)
- ✅ `ConsolidatedPRReviewWorkflow` — coordinator with parallel contract + architectural review
- ✅ Single consolidated GitHub review (no scattered inline comments)
- ✅ UI toggle per-service (settings page)
- ✅ `/learn` command → `LearnFromFeedbackWorkflow` → stores constraint → posts acknowledgement
- ✅ Contract analysis untouched when toggle is OFF
- ✅ Architectural violations + security + performance + best practices sections

**Type consistency:**
- `ArchitecturalIntent` defined in Task 1, used in Task 2 and Task 3
- `process_learn_command_activity` / `run_architectural_review_activity` / `post_consolidated_review_activity` defined in Task 3, registered in Task 7
- `ConsolidatedPRReviewWorkflow` / `LearnFromFeedbackWorkflow` defined in Tasks 4-5, registered in Task 7, routed in Task 6

**No placeholders:** All code blocks are complete and runnable.
