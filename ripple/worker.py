from __future__ import annotations

import asyncio
import logging
import os

from temporalio.worker import Worker

from ripple.activities.fix_activities import (
    clone_and_branch_activity,
    comment_fix_prs_on_producer_activity,
    commit_push_fix_activity,
    create_fix_pr_activity,
    run_claude_code_fix_activity,
)
from ripple.activities.git_activities import cleanup_workspace_activity, clone_repo_activity, get_pr_diff_activity
from ripple.activities.index_activities import (
    ensure_scip_index_activity,
    index_consumer_activity,
    index_producer_activity,
)
from ripple.activities.pr_activities import (
    assess_consumer_impact_activity,
    parse_pr_diff_activity,
    post_github_review_activity,
    record_fix_pr_activity,
    upsert_pr_disagreements_activity,
)
from ripple.activities.indexing.clone_shared import clone_to_shared_workspace_activity
from ripple.activities.indexing.code_index_build import code_index_build_activity
from ripple.activities.indexing.cross_repo_graph_builder import cross_repo_graph_builder_activity
from ripple.activities.indexing.write_graph import write_graph_to_store_activity
from ripple.activities.fixing.mechanical_fix import mechanical_fix_activity
from ripple.activities.fixing.semantic_fix import semantic_fix_activity
from ripple.activities.post_merge_activities import mark_producer_merged_activity
from ripple.logging_config import configure_logging
from ripple.temporal_client import get_temporal_client
from ripple.workflows.analyze_pr import AnalyzePRWorkflow
from ripple.workflows.auto_fix_consumer import AutoFixConsumerWorkflow
from ripple.workflows.ecosystem_pipeline import EcosystemPipelineWorkflow
from ripple.workflows.ingest_ecosystem import IngestEcosystemWorkflow
from ripple.workflows.ingest_service import IngestServiceWorkflow
from ripple.workflows.post_merge import PostMergeWorkflow
from ripple.workflows.consolidated_pr_review import ConsolidatedPRReviewWorkflow
from ripple.workflows.learn_feedback import LearnFromFeedbackWorkflow
from ripple.activities.review_activities import (
    post_consolidated_review_activity,
    process_learn_command_activity,
    run_architectural_review_activity,
)

configure_logging()
logger = logging.getLogger(__name__)


async def main() -> None:
    if not os.environ.get("RIB_DATABASE_URL"):
        raise RuntimeError("RIB_DATABASE_URL must be set")

    client = await get_temporal_client()

    worker = Worker(
        client,
        task_queue="rib",
        workflows=[
            IngestEcosystemWorkflow,
            IngestServiceWorkflow,
            EcosystemPipelineWorkflow,
            AnalyzePRWorkflow,
            AutoFixConsumerWorkflow,
            PostMergeWorkflow,
            ConsolidatedPRReviewWorkflow,
            LearnFromFeedbackWorkflow,
        ],
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
            clone_to_shared_workspace_activity,
            cleanup_workspace_activity,
            get_pr_diff_activity,
            ensure_scip_index_activity,
            post_github_review_activity,
            # fix pipeline
            clone_and_branch_activity,
            commit_push_fix_activity,
            create_fix_pr_activity,
            comment_fix_prs_on_producer_activity,
            # PR interrupt flow
            upsert_pr_disagreements_activity,
            record_fix_pr_activity,
            # post-merge cleanup
            mark_producer_merged_activity,
            # PR review
            post_consolidated_review_activity,
        ],
    )

    llm_worker = Worker(
        client,
        task_queue="rib-llm",
        activities=[
            index_producer_activity,
            parse_pr_diff_activity,
            assess_consumer_impact_activity,
            write_graph_to_store_activity,
            run_architectural_review_activity,
            process_learn_command_activity,
        ],
    )

    cpu_worker = Worker(
        client,
        task_queue="rib-cpu",
        activities=[
            index_consumer_activity,
            run_claude_code_fix_activity,
            # new pipeline activities
            code_index_build_activity,
            cross_repo_graph_builder_activity,
            mechanical_fix_activity,
            semantic_fix_activity,
        ],
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
