from __future__ import annotations

from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.workflow import ParentClosePolicy

with workflow.unsafe.imports_passed_through():
    from ripple.rib.graph.schema import (
        IngestEcosystemRequest,
        IngestionResult,
        ServiceRole,
        ServiceSpec,
    )
    from ripple.workflows.ingest_service import IngestServiceWorkflow, _name_from_url

IO_RETRY = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=2))


def _role_values(service: ServiceSpec) -> set[str]:
    return {role.value for role in service.roles}


def _service_payload(service: ServiceSpec, roles: list[str]) -> dict:
    payload = service.model_dump(mode="json")
    payload["roles"] = roles
    return payload


@workflow.defn(name="IngestEcosystemWorkflow")
class IngestEcosystemWorkflow:
    def __init__(self) -> None:
        self._progress: dict[str, str | int] = {
            "services_total": 0,
            "services_done": 0,
            "status": "pending",
            "phase": "pending",
        }
        self._result: IngestionResult | None = None
        self._errors: list[str] = []

    @workflow.query
    def progress(self) -> dict[str, str | int]:
        return self._progress

    @workflow.query
    def result(self) -> IngestionResult | None:
        return self._result

    @workflow.run
    async def run(self, request: dict) -> dict:
        parsed = IngestEcosystemRequest.model_validate(request)
        workflow_run_id = workflow.info().run_id
        self._progress["services_total"] = len(parsed.services)
        self._progress["status"] = "running"

        producer_services = [
            s for s in parsed.services if ServiceRole.PRODUCER.value in _role_values(s)
        ]
        consumer_services = [
            s for s in parsed.services if ServiceRole.CONSUMER.value in _role_values(s)
        ]

        services_indexed: list[str] = []
        fields_extracted = 0
        usages_found = 0
        beliefs_extracted = 0
        disagreements_detected = 0
        llm_profiles_generated = 0

        async def _run_phase(
            phase_name: str,
            services: list[ServiceSpec],
            roles: list[str],
            suffix: str,
        ) -> None:
            nonlocal fields_extracted, usages_found, beliefs_extracted
            nonlocal disagreements_detected, llm_profiles_generated, services_indexed

            if not services:
                return
            self._progress["phase"] = phase_name
            handles = []
            for service in services:
                service_name = service.service_name or _name_from_url(service.repo_url)
                child_id = f"ingest-{parsed.tenant_id}-{service_name}-{suffix}-{workflow_run_id[:8]}"
                handle = await workflow.start_child_workflow(
                    IngestServiceWorkflow.run,
                    args=[_service_payload(service, roles), workflow_run_id],
                    id=child_id,
                    task_queue="rib",
                    parent_close_policy=ParentClosePolicy.TERMINATE,
                )
                handles.append((service_name, handle))

            for service_name, handle in handles:
                try:
                    child_result = await handle
                    if service_name not in services_indexed:
                        services_indexed.append(service_name)
                    counts = child_result.get("counts", {})
                    fields_extracted += counts.get("fields", 0)
                    usages_found += counts.get("usages", 0)
                    beliefs_extracted += counts.get("beliefs", 0)
                    disagreements_detected += counts.get("disagreements", 0)
                    llm_profiles_generated += counts.get("profiles", 0)
                except Exception as exc:
                    self._errors.append(f"{phase_name}/{service_name}: {exc}")
                self._progress["services_done"] = (
                    int(self._progress.get("services_done", 0)) + 1
                )

        await _run_phase(
            "producers",
            producer_services,
            [ServiceRole.PRODUCER.value],
            "p",
        )
        await _run_phase(
            "consumers",
            consumer_services,
            [ServiceRole.CONSUMER.value],
            "c",
        )

        self._result = IngestionResult(
            services_indexed=services_indexed,
            fields_extracted=fields_extracted,
            usages_found=usages_found,
            beliefs_extracted=beliefs_extracted,
            disagreements_detected=disagreements_detected,
            llm_profiles_generated=llm_profiles_generated,
            duration_seconds=0.0,
            workflow_id=workflow.info().workflow_id,
            errors=self._errors,
        )
        self._progress["status"] = "completed" if not self._errors else "completed_with_errors"
        self._progress["phase"] = "done"
        return self._result.model_dump(mode="json")
