from __future__ import annotations

import asyncio
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from ripple.activities.git_activities import cleanup_workspace_activity
    from ripple.activities.indexing.clone_shared import clone_to_shared_workspace_activity
    from ripple.activities.indexing.cross_repo_graph_builder import cross_repo_graph_builder_activity
    from ripple.activities.indexing.write_graph import write_graph_to_store_activity
    from ripple.rib.graph.schema import IngestEcosystemRequest, IngestionResult, ServiceSpec

import os

IO_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=2))
CPU_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=10))

_WORKSPACE_ROOT = os.environ.get("RIB_WORKSPACE_ROOT", "/tmp/ripple-workspaces")


@workflow.defn(name="EcosystemPipelineWorkflow")
class EcosystemPipelineWorkflow:
    """
    Cross-repo knowledge graph builder.

    Phase 1 — Clone all repos in PARALLEL into a shared workspace root.
              All service dirs become siblings: {run_id}/vets-service/, {run_id}/api-gateway/ ...

    Phase 2 — Build a combined code index (codebase-memory-mcp or codegraph) on the
              shared root. ONE index covers ALL repos — cross-repo symbol lookup works.

    Phase 3 — Claude Code headless with the MCP index wired in.
              Claude calls find_symbol / get_context / get_test_assertions to intelligently
              extract FieldNodes, ConsumerBeliefs, and Disagreements across ALL repos.

    Phase 4 — Write the knowledge graph to Postgres.
              Ripple can now answer "who uses field X?" instantly from DB at PR time.
    """

    def __init__(self) -> None:
        self._progress: dict = {
            "phase": "pending",
            "services_total": 0,
            "services_cloned": 0,
            "fields": 0,
            "beliefs": 0,
            "disagreements": 0,
        }

    @workflow.query
    def progress(self) -> dict:
        return self._progress

    @workflow.run
    async def run(self, request: dict) -> dict:
        parsed = IngestEcosystemRequest.model_validate(request)
        run_id = workflow.info().run_id
        shared_root = f"{_WORKSPACE_ROOT}/{run_id}"
        services = parsed.services

        self._progress["services_total"] = len(services)

        # ── Phase 1: Clone all repos in parallel into shared workspace ──────────
        self._progress["phase"] = "cloning"
        workflow.logger.info(
            "EcosystemPipelineWorkflow phase=cloning services=%d shared_root=%s",
            len(services), shared_root,
        )

        clone_tasks = [
            workflow.execute_activity(
                clone_to_shared_workspace_activity,
                args=[
                    svc.repo_url,
                    shared_root,
                    svc.service_name or _name_from_url(svc.repo_url),
                ],
                task_queue="rib-io",
                start_to_close_timeout=timedelta(minutes=15),
                retry_policy=IO_RETRY,
            )
            for svc in services
        ]
        clone_results = await asyncio.gather(*clone_tasks, return_exceptions=True)

        cloned = 0
        clone_errors: list[str] = []
        for svc, result in zip(services, clone_results):
            if isinstance(result, Exception):
                clone_errors.append(f"{svc.service_name}: {result}")
                workflow.logger.warning("clone failed service=%s err=%s", svc.service_name, result)
            else:
                cloned += 1
        self._progress["services_cloned"] = cloned

        if cloned == 0:
            return _empty_result(run_id, errors=clone_errors, reason="all clones failed")

        # ── Phase 2 → 3: Build knowledge graph (parse + grep + Claude API) ──────
        # No separate indexing phase needed — the graph builder uses OpenAPI parser
        # + grep-based field finder + a single Claude API call (~20-40s total).
        self._progress["phase"] = "graph_building"
        workflow.logger.info("EcosystemPipelineWorkflow phase=graph_building shared_root=%s", shared_root)

        services_payload = [s.model_dump(mode="json") for s in services]
        graph = await workflow.execute_activity(
            cross_repo_graph_builder_activity,
            args=[shared_root, {}, services_payload],
            task_queue="rib-cpu",
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=CPU_RETRY,
        )

        # ── Phase 4: Write graph to Postgres ─────────────────────────────────────
        self._progress["phase"] = "writing"
        workflow.logger.info("EcosystemPipelineWorkflow phase=writing")

        write_result = await workflow.execute_activity(
            write_graph_to_store_activity,
            args=[graph, services_payload],
            task_queue="rib-llm",
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=CPU_RETRY,
        )

        self._progress["fields"] = write_result.get("fields_written", 0)
        self._progress["beliefs"] = write_result.get("beliefs_written", 0)
        self._progress["disagreements"] = write_result.get("disagreements_written", 0)
        self._progress["phase"] = "done"

        # ── Cleanup shared workspace ──────────────────────────────────────────────
        await workflow.execute_activity(
            cleanup_workspace_activity,
            args=[shared_root],
            task_queue="rib-io",
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=IO_RETRY,
        )

        workflow.logger.info(
            "EcosystemPipelineWorkflow done fields=%d beliefs=%d disagreements=%d errors=%d",
            write_result.get("fields_written", 0),
            write_result.get("beliefs_written", 0),
            write_result.get("disagreements_written", 0),
            len(write_result.get("errors", [])),
        )

        return {
            "workflow_id": workflow.info().workflow_id,
            "services_indexed": [
                svc.service_name or _name_from_url(svc.repo_url)
                for svc, r in zip(services, clone_results)
                if not isinstance(r, Exception)
            ],
            "fields_extracted": write_result.get("fields_written", 0),
            "beliefs_extracted": write_result.get("beliefs_written", 0),
            "disagreements_detected": write_result.get("disagreements_written", 0),
            "errors": clone_errors + write_result.get("errors", []),
        }


def _name_from_url(repo_url: str) -> str:
    name = repo_url.rstrip("/").rsplit("/", 1)[-1]
    return name[:-4] if name.endswith(".git") else name


def _empty_result(workflow_id: str, errors: list[str], reason: str) -> dict:
    return {
        "workflow_id": workflow_id,
        "services_indexed": [],
        "fields_extracted": 0,
        "beliefs_extracted": 0,
        "disagreements_detected": 0,
        "errors": errors,
        "reason": reason,
    }
