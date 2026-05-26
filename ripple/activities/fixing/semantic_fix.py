from __future__ import annotations

import logging
import os

from temporalio import activity

logger = logging.getLogger(__name__)

_MODEL = os.environ.get("RIPPLE_SEMANTIC_FIX_MODEL", "claude-sonnet-4-6")


@activity.defn(name="semantic_fix")
async def semantic_fix_activity(payload: dict) -> dict:
    """
    Tier 2 fix: single Sonnet API call with the human's interrupt decision as a hard constraint.
    Latency: 15-30 seconds. Use when: semantic change requires human judgment and they have answered.
    """
    field_change: dict = payload["field_change"]
    location: dict = payload["location"]
    snippet: str = payload["snippet"]
    human_decision: str = payload["human_decision"]

    field_name = field_change.get("field_name", "")
    change_type = field_change.get("change_type", "")
    old_desc = field_change.get("old_description", "")
    new_desc = field_change.get("new_description", "")

    logger.info(
        "semantic_fix start field=%s change=%s decision=%s",
        field_name, change_type, human_decision[:60],
    )

    prompt = (
        f"Fix this code. The human has decided: {human_decision}\n\n"
        f"Breaking change: {field_name} — {change_type}\n"
        f"Was: {old_desc}\n"
        f"Now: {new_desc}\n\n"
        f"Code at {location.get('file')}:{location.get('line')}:\n"
        f"{snippet}\n\n"
        f"Apply exactly the decision above. Minimal change only. "
        f"Return ONLY the fixed code. No markdown fences."
    )

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        message = await client.messages.create(
            model=_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        fixed_code = message.content[0].text if message.content else ""
        success = bool(fixed_code.strip())
    except Exception as exc:
        logger.error("semantic_fix llm error field=%s err=%s", field_name, exc)
        return {"success": False, "fixed_code": "", "error": str(exc)}

    logger.info("semantic_fix done field=%s success=%s", field_name, success)
    return {
        "success": success,
        "fixed_code": fixed_code.strip(),
        "file": location.get("file"),
        "line": location.get("line"),
        "human_decision": human_decision,
    }
