from __future__ import annotations

import json
import logging
import os

from temporalio import activity

logger = logging.getLogger(__name__)

_MODEL = os.environ.get("RIPPLE_MECHANICAL_FIX_MODEL", "claude-haiku-4-5-20251001")


@activity.defn(name="mechanical_fix")
async def mechanical_fix_activity(payload: dict) -> dict:
    """
    Tier 1 fix: single Haiku API call on the exact snippet from the graph.
    Latency: 3-8 seconds. Use when: graph gives exact file + line + snippet,
    change is deterministic (rename, type coercion, null-safety wrapper, new default).
    """
    field_change: dict = payload["field_change"]
    location: dict = payload["location"]
    snippet: str = payload["snippet"]

    field_name = field_change.get("field_name", "")
    change_type = field_change.get("change_type", "")
    old_desc = field_change.get("old_description", "")
    new_desc = field_change.get("new_description", "")

    logger.info(
        "mechanical_fix start field=%s change=%s file=%s line=%s",
        field_name, change_type, location.get("file"), location.get("line"),
    )

    prompt = (
        f"Fix this exact code snippet. Minimal change only.\n\n"
        f"Breaking change: {field_name} — {change_type}\n"
        f"Was: {old_desc}\n"
        f"Now: {new_desc}\n\n"
        f"Code at {location.get('file')}:{location.get('line')}:\n"
        f"{snippet}\n\n"
        f"Return ONLY the fixed code. No explanation. No markdown fences. Touch only what's broken."
    )

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        message = await client.messages.create(
            model=_MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        fixed_code = message.content[0].text if message.content else ""
        success = bool(fixed_code.strip())
    except Exception as exc:
        logger.error("mechanical_fix llm error field=%s err=%s", field_name, exc)
        return {"success": False, "fixed_code": "", "error": str(exc)}

    logger.info("mechanical_fix done field=%s success=%s", field_name, success)
    return {
        "success": success,
        "fixed_code": fixed_code.strip(),
        "file": location.get("file"),
        "line": location.get("line"),
    }
