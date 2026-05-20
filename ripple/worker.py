from __future__ import annotations

import asyncio
import logging
import os

from temporalio.worker import Worker

from ripple.activities.git_activities import cleanup_workspace_activity, clone_repo_activity, get_pr_diff_activity
from ripple.activities.index_activities import (
    ensure_scip_index_activity,
    index_consumer_activity,
    index_producer_activity,
)
from ripple.logging_config import configure_logging
from ripple.temporal_client import get_temporal_client
from ripple.workflows.analyze_pr import AnalyzePRWorkflow
from ripple.workflows.ingest_ecosystem import IngestEcosystemWorkflow
from ripple.workflows.ingest_service import IngestServiceWorkflow

configure_logging()
logger = logging.getLogger(__name__)


async def main() -> None:
    if not os.environ.get("RIB_DATABASE_URL"):
        raise RuntimeError("RIB_DATABASE_URL must be set")

    client = await get_temporal_client()

    worker = Worker(
        client,
        task_queue="rib",
        workflows=[IngestEcosystemWorkflow, IngestServiceWorkflow, AnalyzePRWorkflow],
        activities=[
            clone_repo_activity,
            cleanup_workspace_activity,
            get_pr_diff_activity,
            ensure_scip_index_activity,
            index_producer_activity,
            index_consumer_activity,
        ],
    )

    io_worker = Worker(
        client,
        task_queue="rib-io",
        activities=[
            clone_repo_activity,
            cleanup_workspace_activity,
            get_pr_diff_activity,
            ensure_scip_index_activity,
        ],
    )

    llm_worker = Worker(
        client,
        task_queue="rib-llm",
        activities=[index_producer_activity],
    )

    cpu_worker = Worker(
        client,
        task_queue="rib-cpu",
        activities=[index_consumer_activity],
    )

    logger.info("RIB Temporal workers started (queues: rib, rib-io, rib-llm, rib-cpu)")
    await asyncio.gather(
        worker.run(),
        io_worker.run(),
        llm_worker.run(),
        cpu_worker.run(),
    )


if __name__ == "__main__":
    asyncio.run(main())
