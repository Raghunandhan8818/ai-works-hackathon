"""
Temporal activities for AnalyzePRWorkflow.

Three activities run on separate queues:
  rib-llm  — parse_pr_diff_activity, assess_consumer_impact_activity
  rib-io   — post_github_review_activity
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional

import httpx
from temporalio import activity

from ripple.rib.enricher.llm_disagreement_detector import detect_llm_disagreements
from ripple.rib.graph.factory import get_store
from ripple.rib.graph.schema import ConsumerBelief, FieldNode

logger = logging.getLogger(__name__)

# ── Haiku client helper ────────────────────────────────────────────────────────

def _haiku(system: str, user: str, max_tokens: int = 1024) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return msg.content[0].text


# ── Activity 1: Parse PR diff → changed field contracts ───────────────────────

_DIFF_SYSTEM = """\
You are a semantic contract analyst for microservice APIs.

Given a git diff from a producer service, identify which API field contracts have
changed in a semantically meaningful way (not just code refactoring).

Focus on changes that could break consumers:
- Field semantics changed (unit, meaning, domain)
- Field type changed
- Field removed or renamed
- Enum values changed
- Nullability changed
- Value range / invariants changed

For each changed field, return a JSON array:
[
  {
    "field_name": "<the field's NEW name after the change>",
    "old_field_name": "<the field's OLD name BEFORE the change — same as field_name if not renamed>",
    "field_fqn": "<use the OLD field name in the FQN so it matches the knowledge graph — e.g. service::REST::POST /authenticate::response.200.jwtToken NOT accessToken>",
    "change_type": "SEMANTIC_CHANGE | TYPE_CHANGE | REMOVED | ADDED | UNIT_CHANGE | ENUM_CHANGE | NULLABLE_CHANGE",
    "old_description": "<what the field meant/was before, include the old name>",
    "new_description": "<what the field means/is now, include the new name>",
    "severity_hint": "CRITICAL | HIGH | MEDIUM | LOW",
    "file_path": "<relative path to the file containing this change>",
    "line": <line number in the NEW file where the key definition/change occurs>
  }
]

CRITICAL RULE for field_fqn and old_field_name:
- If jwtToken was renamed to accessToken → old_field_name="jwtToken", field_fqn uses "jwtToken"
- If fullName was renamed to displayName → old_field_name="fullName", field_fqn uses "fullName"
- The knowledge graph was indexed BEFORE this PR, so always use the PRE-CHANGE name.

Return [] if no semantic contract changes are found (pure refactoring, tests only, docs only).
Only include changes that affect what consumers receive or must handle.
"""


@activity.defn(name="parse_pr_diff_activity")
async def parse_pr_diff_activity(payload: dict) -> list[dict]:
    """
    Calls Haiku with the raw PR diff to extract semantically changed field contracts.
    Returns list of FieldChange dicts.
    """
    diff: str = payload["diff"]
    producer_service: str = payload["producer_service"]

    # Enrich prompt with known fields from the store for better FQN matching
    store = get_store()
    known_fields = store.get_fields_for_service(producer_service)
    field_summary = "\n".join(
        f"  - {f.name} (fqn={f.fqn}, type={f.declared_type}, endpoint={f.endpoint_or_topic})"
        for f in known_fields[:120]
    )

    user_prompt = (
        f"Producer service: {producer_service}\n\n"
        + (f"Known fields in RIB:\n{field_summary}\n\n" if field_summary else "")
        + f"PR DIFF (truncated to 8000 chars):\n```diff\n{diff[:8000]}\n```"
    )

    logger.info("parse_pr_diff_activity service=%s diff_len=%d", producer_service, len(diff))
    try:
        raw = _haiku(_DIFF_SYSTEM, user_prompt, max_tokens=4096)
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            logger.info("parse_pr_diff_activity no changes detected")
            return []
        changes = json.loads(m.group())
        logger.info("parse_pr_diff_activity changes=%d", len(changes))
        return [_normalise_field_change(c) for c in changes if isinstance(c, dict)]
    except Exception as e:
        logger.error("parse_pr_diff_activity failed: %s", e)
        return []


def _normalise_field_change(c: dict) -> dict:
    valid_change_types = {
        "SEMANTIC_CHANGE", "TYPE_CHANGE", "REMOVED", "ADDED",
        "UNIT_CHANGE", "ENUM_CHANGE", "NULLABLE_CHANGE",
    }
    valid_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    try:
        line = int(c.get("line", 0))
    except (TypeError, ValueError):
        line = 0
    field_name = str(c.get("field_name", "unknown"))[:200]
    # old_field_name is the pre-rename name — used to look up the field in the KB
    old_field_name = str(c.get("old_field_name", field_name))[:200]
    return {
        "field_name": field_name,
        "old_field_name": old_field_name,
        "field_fqn": str(c.get("field_fqn", c.get("field_name", "unknown")))[:500],
        "change_type": c.get("change_type", "SEMANTIC_CHANGE")
            if c.get("change_type") in valid_change_types else "SEMANTIC_CHANGE",
        "old_description": str(c.get("old_description", ""))[:500],
        "new_description": str(c.get("new_description", ""))[:500],
        "severity_hint": c.get("severity_hint", "MEDIUM")
            if c.get("severity_hint") in valid_severities else "MEDIUM",
        "file_path": str(c.get("file_path", ""))[:500],
        "line": line,
    }


# ── Activity 2: Assess consumer impact for one changed field ──────────────────

_IMPACT_SYSTEM = """\
You are a microservice contract impact analyst.

A producer field has changed. You have:
1. The specific change (old vs new meaning)
2. The consumer's code evidence (how they use this field)
3. The consumer's inferred belief about the field

Determine: Does this specific change BREAK this consumer?

Return a JSON array of impacts (one per consumer location that breaks):
[
  {
    "consumer_service": "<service name>",
    "file_path": "<full file path>",
    "line": <line number>,
    "breaks": true | false,
    "severity": "CRITICAL | HIGH | MEDIUM | LOW",
    "explanation": "<one sentence: exactly why this usage breaks>",
    "suggested_fix": "<concrete code change the consumer team should make>",
    "evidence": ["<usage snippet that proves this breaks>"]
  }
]

Return [] if the consumer is unaffected.
Be specific — cite the actual code that would produce wrong results.
Only flag breaks where you have CLEAR evidence in the usage code.
"""


@activity.defn(name="assess_consumer_impact_activity")
async def assess_consumer_impact_activity(payload: dict) -> list[dict]:
    """
    For a single FieldChange, queries the knowledge graph for all consumers
    and assesses impact using LLM disagreement detection with the specific
    old→new change context. Returns list of ConsumerImpact dicts.
    """
    field_change: dict = payload["field_change"]
    producer_service: str = payload["producer_service"]

    store = get_store()

    # Find the canonical field from the store — four fallback strategies for renamed fields
    field_fqn: str = field_change["field_fqn"]
    field: Optional[FieldNode] = store.get_field(field_fqn)

    if field is None:
        all_producer_fields = store.get_fields_for_service(producer_service)

        # Strategy 1: exact new field name match
        for f in all_producer_fields:
            if f.name.lower() == field_change["field_name"].lower():
                field, field_fqn = f, f.fqn
                break

    if field is None:
        # Strategy 2: old field name match (rename case — KB has pre-change name)
        old_name = field_change.get("old_field_name", "")
        if old_name and old_name.lower() != field_change["field_name"].lower():
            for f in all_producer_fields:
                if f.name.lower() == old_name.lower():
                    field, field_fqn = f, f.fqn
                    logger.info(
                        "assess_consumer_impact_activity matched by old_field_name=%s fqn=%s",
                        old_name, f.fqn,
                    )
                    break

    if field is None:
        # Strategy 3: endpoint + old name match (handles FQN endpoint mismatch)
        fqn_parts = field_change["field_fqn"].split("::")
        if len(fqn_parts) >= 3:
            endpoint = fqn_parts[2]
            old_name = field_change.get("old_field_name", field_change["field_name"])
            for f in all_producer_fields:
                if f.endpoint_or_topic == endpoint and f.name.lower() == old_name.lower():
                    field, field_fqn = f, f.fqn
                    logger.info(
                        "assess_consumer_impact_activity matched by endpoint+old_name endpoint=%s name=%s fqn=%s",
                        endpoint, old_name, f.fqn,
                    )
                    break

    if field is None:
        # Strategy 4: endpoint-only match when only one field at that endpoint changed
        fqn_parts = field_change["field_fqn"].split("::")
        if len(fqn_parts) >= 3:
            endpoint = fqn_parts[2]
            candidates = [f for f in all_producer_fields if f.endpoint_or_topic == endpoint]
            if len(candidates) == 1:
                field, field_fqn = candidates[0], candidates[0].fqn
                logger.info(
                    "assess_consumer_impact_activity matched sole field at endpoint=%s fqn=%s",
                    endpoint, field_fqn,
                )

    if field is None:
        logger.warning(
            "assess_consumer_impact_activity field not found fqn=%s name=%s old_name=%s",
            field_change["field_fqn"], field_change["field_name"],
            field_change.get("old_field_name", ""),
        )
        return []

    # Get blast radius — all consumers of this field
    try:
        blast = store.get_blast_radius(field_fqn)
    except ValueError:
        return []

    if not blast.consumers:
        logger.info("assess_consumer_impact_activity no consumers for field=%s", field_fqn)
        return []

    business_context = store.get_business_context(field_fqn)

    all_impacts: list[dict] = []

    for consumer_entry in blast.consumers:
        consumer_service = consumer_entry.consumer_service
        usages = consumer_entry.usages
        belief: Optional[ConsumerBelief] = consumer_entry.belief

        if not usages:
            continue

        # Build a change-aware prompt section
        change_context = (
            f"FIELD CHANGE IN THIS PR:\n"
            f"  Field: {field.name} ({field.declared_type})\n"
            f"  Change type: {field_change['change_type']}\n"
            f"  Before: {field_change['old_description']}\n"
            f"  After:  {field_change['new_description']}\n"
            f"  Severity hint: {field_change['severity_hint']}"
        )

        usage_lines = []
        for u in usages[:8]:
            line = f"  {u.file_path}:{u.line}  {u.expression[:120]}"
            if u.local_var_name:
                line += f"  [var={u.local_var_name}]"
            if u.operations:
                line += f"  [ops={', '.join(u.operations)}]"
            usage_lines.append(line)

        belief_section = ""
        if belief:
            belief_section = (
                f"\nCONSUMER BELIEF:\n"
                f"  assumed_unit={belief.assumed_unit or 'unknown'}\n"
                f"  assumed_type={belief.assumed_type or 'unknown'}\n"
                f"  assumed_nullable={belief.assumed_nullable}\n"
                f"  inferred_constraints={'; '.join(belief.inferred_constraints) or 'none'}"
            )

        bc_section = ""
        if business_context:
            bc_section = (
                f"\nPRODUCER INTENT (ground truth):\n"
                f"  unit={business_context.unit or 'unspecified'}\n"
                f"  domain={business_context.domain}\n"
                f"  {business_context.producer_intent[:400]}"
            )

        user_prompt = (
            f"{change_context}\n\n"
            f"Consumer service: {consumer_service}\n"
            f"Consumer usages:\n" + "\n".join(usage_lines)
            + belief_section + bc_section
        )

        logger.info(
            "assess_consumer_impact_activity field=%s consumer=%s usages=%d",
            field_fqn, consumer_service, len(usages),
        )

        try:
            raw = _haiku(_IMPACT_SYSTEM, user_prompt, max_tokens=2048)
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if not m:
                continue
            impacts = json.loads(m.group())
            consumer_repo_url = consumer_entry.repo_url
            if not consumer_repo_url:
                # Fallback: scan services table (covers consumers not yet upserted as producers)
                for svc in store.get_all_services():
                    if svc.name == consumer_service and svc.repo_url:
                        consumer_repo_url = svc.repo_url
                        break
            for impact in impacts:
                if not isinstance(impact, dict):
                    continue
                all_impacts.append(_normalise_impact(impact, consumer_service, usages, consumer_repo_url))
        except Exception as e:
            logger.error(
                "assess_consumer_impact_activity LLM failed field=%s consumer=%s: %s",
                field_fqn, consumer_service, e,
            )

    logger.info(
        "assess_consumer_impact_activity field=%s total_impacts=%d",
        field_fqn, len(all_impacts),
    )
    return all_impacts


def _normalise_impact(
    impact: dict, default_service: str, usages: list, consumer_repo_url: str = ""
) -> dict:
    valid_severities = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    file_path = str(impact.get("file_path", ""))
    line = int(impact.get("line", 0))

    # If no file path given, use first usage as fallback
    if not file_path and usages:
        file_path = usages[0].file_path
        line = usages[0].line

    return {
        "consumer_service": str(impact.get("consumer_service", default_service))[:200],
        "consumer_repo_url": consumer_repo_url,
        "file_path": file_path[:500],
        "line": line,
        "breaks": bool(impact.get("breaks", False)),
        "severity": impact.get("severity", "MEDIUM")
            if impact.get("severity") in valid_severities else "MEDIUM",
        "explanation": str(impact.get("explanation", ""))[:500],
        "suggested_fix": str(impact.get("suggested_fix", ""))[:1000],
        "evidence": [str(e)[:300] for e in impact.get("evidence", [])[:5]],
    }


# ── Activity 3: Post GitHub review comment ────────────────────────────────────

@activity.defn(name="post_github_review_activity")
async def post_github_review_activity(payload: dict) -> dict:
    """
    Posts a PR review comment to GitHub.
    Uses the GitHub REST API via httpx.
    Returns {"url": "<comment_url>", "success": true/false}.
    """
    repo_url: str = payload["repo_url"]
    pr_number: int = payload["pr_number"]
    head_sha: str = payload["head_sha"]
    comment: str = payload["comment"]
    github_token: str = payload.get("github_token") or os.environ.get("GITHUB_TOKEN", "")

    # Parse owner/repo from URL (supports https://github.com/owner/repo or owner/repo)
    owner_repo = _parse_owner_repo(repo_url)
    if not owner_repo:
        logger.error("post_github_review_activity bad repo_url=%s", repo_url)
        return {"url": "", "success": False, "error": f"Cannot parse repo URL: {repo_url}"}

    if not github_token:
        logger.error("post_github_review_activity no github_token")
        return {"url": "", "success": False, "error": "No GitHub token"}

    api_url = f"https://api.github.com/repos/{owner_repo}/pulls/{pr_number}/reviews"
    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    body = {
        "commit_id": head_sha,
        "body": comment,
        "event": "COMMENT",
    }

    inline_comments: list = payload.get("inline_comments", [])

    request_body = {
        "commit_id": head_sha,
        "body": comment,
        "event": "COMMENT",
    }
    if inline_comments:
        request_body["comments"] = inline_comments

    logger.info(
        "post_github_review_activity repo=%s pr=%s sha=%s inline_comments=%d",
        owner_repo, pr_number, head_sha[:8], len(inline_comments),
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(api_url, headers=headers, json=request_body)

        # GitHub returns 422 when a comment line isn't in the diff — fall back to body-only
        if resp.status_code == 422 and inline_comments:
            logger.warning(
                "post_github_review_activity 422 with inline comments, retrying body-only repo=%s pr=%s: %s",
                owner_repo, pr_number, resp.text[:200],
            )
            request_body_fallback = {
                "commit_id": head_sha,
                "body": comment,
                "event": "COMMENT",
            }
            resp = await client.post(api_url, headers=headers, json=request_body_fallback)

    if resp.status_code not in (200, 201):
        logger.error(
            "post_github_review_activity HTTP %d repo=%s pr=%s body=%s",
            resp.status_code, owner_repo, pr_number, resp.text[:200],
        )
        return {
            "url": "",
            "success": False,
            "error": f"GitHub API returned {resp.status_code}: {resp.text[:200]}",
        }

    result = resp.json()
    review_url = result.get("html_url", "")
    logger.info("post_github_review_activity posted url=%s", review_url)
    return {"url": review_url, "success": True}


def _parse_owner_repo(repo_url: str) -> Optional[str]:
    """Extract 'owner/repo' from a GitHub URL or plain 'owner/repo' string."""
    # Strip .git suffix
    url = repo_url.rstrip("/").removesuffix(".git")
    # https://github.com/owner/repo
    m = re.search(r"github\.com[/:]([^/]+/[^/]+)$", url)
    if m:
        return m.group(1)
    # Plain owner/repo
    if re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", url):
        return url
    return None
