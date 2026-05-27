from __future__ import annotations
import logging
from temporalio import activity
from ripple.rib.graph.factory import get_store

logger = logging.getLogger(__name__)

@activity.defn(name="mark_producer_merged_activity")
async def mark_producer_merged_activity(producer_service: str) -> int:
    store = get_store()
    count = store.mark_producer_merged(producer_service)
    logger.info("mark_producer_merged_activity producer=%s count=%d", producer_service, count)
    return count
