from __future__ import annotations

import logging
from pathlib import Path

from temporalio import activity

logger = logging.getLogger(__name__)

from ripple.rib.graph.factory import get_store
from ripple.rib.service_indexer import index_consumer, index_producer, prepare_scip


@activity.defn(name="ensure_scip_index")
async def ensure_scip_index_activity(workspace: str, service_name: str) -> dict:
    logger.info("activity ensure_scip_index service=%s workspace=%s", service_name, workspace)
    store = get_store()
    result = prepare_scip(Path(workspace), service_name, store)
    logger.info("activity ensure_scip_index done service=%s result=%s", service_name, result)
    return result


@activity.defn(name="index_producer")
async def index_producer_activity(
    workspace: str,
    service_name: str,
    openapi_path: str,
) -> dict[str, int]:
    logger.info(
        "activity index_producer service=%s workspace=%s openapi=%s",
        service_name,
        workspace,
        openapi_path,
    )
    store = get_store()
    counts = index_producer(Path(workspace), service_name, openapi_path, store)
    logger.info("activity index_producer done service=%s counts=%s", service_name, counts)
    return counts


@activity.defn(name="index_consumer")
async def index_consumer_activity(workspace: str, service_name: str) -> dict[str, int]:
    logger.info("activity index_consumer service=%s workspace=%s", service_name, workspace)
    store = get_store()
    counts = index_consumer(Path(workspace), service_name, store)
    logger.info("activity index_consumer done service=%s counts=%s", service_name, counts)
    return counts
