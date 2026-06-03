from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import psycopg
from psycopg.rows import dict_row

from ripple.rib.graph.schema import (
    ArchitecturalIntent,
    BlastRadius,
    BlastRadiusEntry,
    BusinessContext,
    CodeClass,
    CodeMethod,
    Constraint,
    ConsumerBelief,
    Disagreement,
    DisagreementKind,
    DisagreementSource,
    DriftEvent,
    FieldNode,
    FieldUsage,
    HistorySignal,
    SemanticProfile,
    ServiceRecord,
    Severity,
    SymbolNode,
    TestEvidence,
    TransportKind,
)

SCHEMA_VERSION = 1
_SCHEMA_PATH = Path(__file__).with_name("schema.sql")


class PostgresStore:
    def __init__(self, database_url: str) -> None:
        self._database_url = database_url
        self._initialize_schema()

    def _connect(self) -> psycopg.Connection[Any]:
        return psycopg.connect(self._database_url, row_factory=dict_row)

    def close(self) -> None:
        pass

    def _initialize_schema(self) -> None:
        ddl = _SCHEMA_PATH.read_text()
        with self._connect() as conn:
            conn.execute(ddl)
            row = conn.execute(
                "SELECT version FROM schema_version LIMIT 1"
            ).fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO schema_version (version) VALUES (%s)",
                    (SCHEMA_VERSION,),
                )
            conn.commit()

    def upsert_field(self, field: FieldNode) -> None:
        constraints_json = json.dumps([c.model_dump() for c in field.constraints])
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO fields (
                    fqn, name, producer_service, transport, endpoint_or_topic,
                    field_path, declared_type, nullable, deprecated,
                    schema_source_path, constraints_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (fqn) DO UPDATE SET
                    name = EXCLUDED.name,
                    producer_service = EXCLUDED.producer_service,
                    transport = EXCLUDED.transport,
                    endpoint_or_topic = EXCLUDED.endpoint_or_topic,
                    field_path = EXCLUDED.field_path,
                    declared_type = EXCLUDED.declared_type,
                    nullable = EXCLUDED.nullable,
                    deprecated = EXCLUDED.deprecated,
                    schema_source_path = EXCLUDED.schema_source_path,
                    constraints_json = EXCLUDED.constraints_json
                """,
                (
                    field.fqn,
                    field.name,
                    field.producer_service,
                    field.transport.value,
                    field.endpoint_or_topic,
                    field.field_path,
                    field.declared_type,
                    field.nullable,
                    field.deprecated,
                    field.schema_source_path,
                    constraints_json,
                ),
            )
            conn.commit()

    def upsert_symbol(self, symbol: SymbolNode) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO symbols (
                    scip_id, display_name, kind, service_name,
                    file_path, line, containing_function, visibility
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (scip_id) DO UPDATE SET
                    display_name = EXCLUDED.display_name,
                    kind = EXCLUDED.kind,
                    service_name = EXCLUDED.service_name,
                    file_path = EXCLUDED.file_path,
                    line = EXCLUDED.line,
                    containing_function = EXCLUDED.containing_function,
                    visibility = EXCLUDED.visibility
                """,
                (
                    symbol.scip_id,
                    symbol.display_name,
                    symbol.kind,
                    symbol.service_name,
                    symbol.file_path,
                    symbol.line,
                    symbol.containing_function,
                    symbol.visibility,
                ),
            )
            conn.commit()

    def upsert_usage(self, usage: FieldUsage) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO field_usages (
                    field_fqn, consumer_service, file_path, line,
                    expression, surrounding_context, containing_function,
                    containing_class, local_var_name, operations_json, scip_symbol_id,
                    is_test, source_context
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                ON CONFLICT (field_fqn, consumer_service, file_path, line) DO UPDATE SET
                    expression = EXCLUDED.expression,
                    surrounding_context = EXCLUDED.surrounding_context,
                    containing_function = EXCLUDED.containing_function,
                    containing_class = EXCLUDED.containing_class,
                    local_var_name = EXCLUDED.local_var_name,
                    operations_json = EXCLUDED.operations_json,
                    scip_symbol_id = EXCLUDED.scip_symbol_id,
                    is_test = EXCLUDED.is_test,
                    source_context = EXCLUDED.source_context
                """,
                (
                    usage.field_fqn,
                    usage.consumer_service,
                    usage.file_path,
                    usage.line,
                    usage.expression,
                    usage.surrounding_context,
                    usage.containing_function,
                    usage.containing_class,
                    usage.local_var_name,
                    json.dumps(usage.operations),
                    usage.scip_symbol_id,
                    usage.is_test,
                    usage.source_context,
                ),
            )
            conn.commit()

    def clear_usages_for_service(self, consumer_service: str) -> int:
        """Delete all field_usages for a consumer service. Call before re-indexing to remove stale entries."""
        with self._connect() as conn:
            result = conn.execute(
                "DELETE FROM field_usages WHERE consumer_service = %s",
                (consumer_service,),
            )
            conn.commit()
            return result.rowcount or 0

    def upsert_history_signal(self, signal: HistorySignal) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO history_signals (
                    field_fqn, commit_hash, commit_message, author,
                    committed_at, risk_keywords_json
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
                """,
                (
                    signal.field_fqn,
                    signal.commit_hash,
                    signal.commit_message,
                    signal.author,
                    signal.committed_at,
                    json.dumps(signal.risk_keywords),
                ),
            )
            conn.commit()

    def upsert_semantic_profile(self, profile: SemanticProfile) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO semantic_profiles (
                    field_fqn, unit, domain, invariants_json, risk_flags_json,
                    confidence, evidence_json, generated_at, source_commit_hash
                ) VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::jsonb, %s, %s)
                ON CONFLICT (field_fqn) DO UPDATE SET
                    unit = EXCLUDED.unit,
                    domain = EXCLUDED.domain,
                    invariants_json = EXCLUDED.invariants_json,
                    risk_flags_json = EXCLUDED.risk_flags_json,
                    confidence = EXCLUDED.confidence,
                    evidence_json = EXCLUDED.evidence_json,
                    generated_at = EXCLUDED.generated_at,
                    source_commit_hash = EXCLUDED.source_commit_hash
                """,
                (
                    profile.field_fqn,
                    profile.unit,
                    profile.domain,
                    json.dumps(profile.invariants),
                    json.dumps(profile.risk_flags),
                    profile.confidence,
                    json.dumps(profile.evidence),
                    profile.generated_at,
                    profile.source_commit_hash,
                ),
            )
            conn.commit()

    def upsert_consumer_belief(self, belief: ConsumerBelief) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO consumer_beliefs (
                    consumer_service, field_fqn, assumed_unit, assumed_type,
                    assumed_nullable, assumed_format, inferred_constraints_json,
                    usage_expressions_json, confidence, extracted_at, source_file_hash
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s)
                ON CONFLICT (consumer_service, field_fqn) DO UPDATE SET
                    assumed_unit = EXCLUDED.assumed_unit,
                    assumed_type = EXCLUDED.assumed_type,
                    assumed_nullable = EXCLUDED.assumed_nullable,
                    assumed_format = EXCLUDED.assumed_format,
                    inferred_constraints_json = EXCLUDED.inferred_constraints_json,
                    usage_expressions_json = EXCLUDED.usage_expressions_json,
                    confidence = EXCLUDED.confidence,
                    extracted_at = EXCLUDED.extracted_at,
                    source_file_hash = EXCLUDED.source_file_hash
                """,
                (
                    belief.consumer_service,
                    belief.field_fqn,
                    belief.assumed_unit,
                    belief.assumed_type,
                    belief.assumed_nullable,
                    belief.assumed_format,
                    json.dumps(belief.inferred_constraints),
                    json.dumps(belief.usage_expressions),
                    belief.confidence,
                    belief.extracted_at,
                    belief.source_file_hash,
                ),
            )
            conn.commit()

    def upsert_disagreement(self, disagreement: Disagreement) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO disagreements (
                    field_fqn, consumer_service, kind, producer_says, consumer_assumes,
                    severity, evidence_json, explanation, detected_at, resolved_at, fix_pr_url, source,
                    requires_human_decision, human_decision_reason, mitigation_options_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (field_fqn, consumer_service, kind)
                WHERE resolved_at IS NULL DO UPDATE SET
                    mitigation_options_json = EXCLUDED.mitigation_options_json,
                    requires_human_decision = EXCLUDED.requires_human_decision,
                    human_decision_reason = EXCLUDED.human_decision_reason
                """,
                (
                    disagreement.field_fqn,
                    disagreement.consumer_service,
                    disagreement.kind.value,
                    disagreement.producer_says,
                    disagreement.consumer_assumes,
                    disagreement.severity.value,
                    json.dumps(disagreement.evidence),
                    disagreement.explanation,
                    disagreement.detected_at,
                    disagreement.resolved_at,
                    disagreement.fix_pr_url,
                    disagreement.source.value,
                    disagreement.requires_human_decision,
                    disagreement.human_decision_reason,
                    json.dumps(disagreement.mitigation_options),
                ),
            )
            conn.commit()

    def get_field(self, field_fqn: str) -> Optional[FieldNode]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM fields WHERE fqn = %s", (field_fqn,)
            ).fetchone()
        if row is None:
            return None
        return self._row_to_field(row)

    def get_semantic_profile(self, field_fqn: str) -> Optional[SemanticProfile]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM semantic_profiles WHERE field_fqn = %s",
                (field_fqn,),
            ).fetchone()
        if row is None:
            return None
        return SemanticProfile(
            field_fqn=row["field_fqn"],
            unit=row["unit"],
            domain=row["domain"],
            invariants=_json_list(row["invariants_json"]),
            risk_flags=_json_list(row["risk_flags_json"]),
            confidence=row["confidence"],
            evidence=_json_list(row["evidence_json"]),
            generated_at=row["generated_at"],
            source_commit_hash=row["source_commit_hash"] or "",
        )

    def get_consumer_belief(
        self, consumer_service: str, field_fqn: str
    ) -> Optional[ConsumerBelief]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM consumer_beliefs
                WHERE consumer_service = %s AND field_fqn = %s
                """,
                (consumer_service, field_fqn),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_belief(row)

    def get_usages_for_field(self, field_fqn: str) -> list[FieldUsage]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM field_usages WHERE field_fqn = %s", (field_fqn,)
            ).fetchall()
        return [self._row_to_usage(row) for row in rows]

    def get_history_signals(self, field_fqn: str) -> list[HistorySignal]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM history_signals
                WHERE field_fqn = %s ORDER BY committed_at DESC
                """,
                (field_fqn,),
            ).fetchall()
        return [
            HistorySignal(
                field_fqn=row["field_fqn"],
                commit_hash=row["commit_hash"],
                commit_message=row["commit_message"],
                author=row["author"],
                committed_at=row["committed_at"],
                risk_keywords=_json_list(row["risk_keywords_json"]),
            )
            for row in rows
        ]

    def get_active_disagreements(self) -> list[Disagreement]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM disagreements
                WHERE resolved_at IS NULL ORDER BY detected_at DESC
                """
            ).fetchall()
        return [self._row_to_disagreement(row) for row in rows]

    def get_all_disagreements(self, limit: int = 200) -> list[Disagreement]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM disagreements
                ORDER BY COALESCE(resolved_at, detected_at) DESC
                LIMIT %s
                """,
                (limit,),
            ).fetchall()
        return [self._row_to_disagreement(row) for row in rows]

    def get_disagreements_for_field(self, field_fqn: str) -> list[Disagreement]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM disagreements WHERE field_fqn = %s", (field_fqn,)
            ).fetchall()
        return [self._row_to_disagreement(row) for row in rows]

    def get_blast_radius(self, field_fqn: str) -> BlastRadius:
        field = self.get_field(field_fqn)
        if field is None:
            raise ValueError(f"Field not found: {field_fqn}")

        profile = self.get_semantic_profile(field_fqn)
        usages = self.get_usages_for_field(field_fqn)
        disagreements = {
            (d.consumer_service, d.field_fqn): d
            for d in self.get_disagreements_for_field(field_fqn)
            if d.resolved_at is None
        }

        consumers_by_service: dict[str, list[FieldUsage]] = {}
        for usage in usages:
            consumers_by_service.setdefault(usage.consumer_service, []).append(usage)

        # Look up repo URLs for all consumer services in one query
        consumer_repo_urls: dict[str, str] = {}
        if consumers_by_service:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT name, repo_url FROM services WHERE name = ANY(%s)",
                    (list(consumers_by_service.keys()),),
                ).fetchall()
                consumer_repo_urls = {r["name"]: r["repo_url"] or "" for r in rows}

        entries: list[BlastRadiusEntry] = []
        critical_count = 0
        for service_name, service_usages in consumers_by_service.items():
            belief = self.get_consumer_belief(service_name, field_fqn)
            active = [
                disagreements[(service_name, field_fqn)]
                for key in [(service_name, field_fqn)]
                if key in disagreements
            ]
            for disagreement in active:
                if disagreement.severity == Severity.CRITICAL:
                    critical_count += 1
            entries.append(
                BlastRadiusEntry(
                    consumer_service=service_name,
                    repo_url=consumer_repo_urls.get(service_name, ""),
                    usages=service_usages,
                    active_disagreements=active,
                    belief=belief,
                )
            )

        return BlastRadius(
            field=field,
            semantic_profile=profile,
            consumers=entries,
            total_consumers=len(entries),
            critical_disagreement_count=critical_count,
        )

    def get_all_fields(self) -> list[FieldNode]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM fields").fetchall()
        return [self._row_to_field(row) for row in rows]

    def get_fields_for_service(self, service_name: str) -> list[FieldNode]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM fields WHERE producer_service = %s",
                (service_name,),
            ).fetchall()
        return [self._row_to_field(row) for row in rows]

    def mark_disagreement_resolved(
        self, field_fqn: str, consumer_service: str, fix_pr_url: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE disagreements
                SET resolved_at = %s, fix_pr_url = %s
                WHERE field_fqn = %s AND consumer_service = %s AND resolved_at IS NULL
                """,
                (
                    datetime.now(timezone.utc),
                    fix_pr_url,
                    field_fqn,
                    consumer_service,
                ),
            )
            conn.commit()

    def get_file_content_hash(self, file_path: str, service_name: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT content_hash FROM indexed_files
                WHERE service_name = %s AND file_path = %s
                """,
                (service_name, file_path),
            ).fetchone()
        return row["content_hash"] if row else None

    def upsert_indexed_file(
        self, service_name: str, file_path: str, content_hash: str
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO indexed_files (service_name, file_path, content_hash, indexed_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (service_name, file_path) DO UPDATE SET
                    content_hash = EXCLUDED.content_hash,
                    indexed_at = EXCLUDED.indexed_at
                """,
                (
                    service_name,
                    file_path,
                    content_hash,
                    datetime.now(timezone.utc),
                ),
            )
            conn.commit()

    def upsert_service(self, record: ServiceRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO services (name, repo_url, language, last_indexed_at)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (name) DO UPDATE SET
                    repo_url = COALESCE(EXCLUDED.repo_url, services.repo_url),
                    language = COALESCE(NULLIF(EXCLUDED.language, ''), services.language),
                    last_indexed_at = EXCLUDED.last_indexed_at
                """,
                (record.name, record.repo_url, record.language, record.last_indexed_at),
            )
            conn.commit()

    def get_all_services(self) -> list[ServiceRecord]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM services ORDER BY name").fetchall()
            # Count fields per producer service
            field_counts = {
                r["producer_service"]: r["cnt"]
                for r in conn.execute(
                    "SELECT producer_service, COUNT(*) AS cnt FROM fields GROUP BY producer_service"
                ).fetchall()
            }
            # Count distinct consumer services per producer
            consumer_counts = {
                r["producer_service"]: r["cnt"]
                for r in conn.execute(
                    """
                    SELECT f.producer_service, COUNT(DISTINCT fu.consumer_service) AS cnt
                    FROM field_usages fu
                    JOIN fields f ON f.fqn = fu.field_fqn
                    GROUP BY f.producer_service
                    """
                ).fetchall()
            }
            # All known consumer services (may not be in services table as producers)
            consumer_services = {
                r["consumer_service"]
                for r in conn.execute(
                    "SELECT DISTINCT consumer_service FROM field_usages"
                ).fetchall()
            }
            producer_services = {r["name"] for r in rows}

        result = []
        for row in rows:
            name = row["name"]
            is_consumer = name in consumer_services
            role = "both" if is_consumer else "producer"
            result.append(ServiceRecord(
                name=name,
                repo_url=row["repo_url"] or "",
                language=row["language"] or "",
                role=role,
                field_count=field_counts.get(name, 0),
                consumer_count=consumer_counts.get(name, 0),
                last_indexed_at=row["last_indexed_at"],
            ))

        # Add pure consumer services not yet in the services table
        for svc in sorted(consumer_services - producer_services):
            result.append(ServiceRecord(
                name=svc,
                role="consumer",
                field_count=0,
                consumer_count=0,
            ))

        return result

    def ping(self) -> bool:
        with self._connect() as conn:
            conn.execute("SELECT 1")
        return True

    def _row_to_field(self, row: dict[str, Any]) -> FieldNode:
        constraints_raw = _json_list(row["constraints_json"])
        constraints = [Constraint(**c) for c in constraints_raw]
        return FieldNode(
            fqn=row["fqn"],
            name=row["name"],
            producer_service=row["producer_service"],
            transport=TransportKind(row["transport"]),
            endpoint_or_topic=row["endpoint_or_topic"],
            field_path=row["field_path"],
            declared_type=row["declared_type"],
            nullable=row["nullable"],
            deprecated=row["deprecated"],
            constraints=constraints,
            schema_source_path=row["schema_source_path"] or "",
        )

    def _row_to_usage(self, row: dict[str, Any]) -> FieldUsage:
        return FieldUsage(
            field_fqn=row["field_fqn"],
            consumer_service=row["consumer_service"],
            file_path=row["file_path"],
            line=row["line"],
            expression=row["expression"],
            surrounding_context=row["surrounding_context"] or "",
            containing_function=row["containing_function"] or "",
            containing_class=row.get("containing_class") or "",
            local_var_name=row.get("local_var_name") or "",
            operations=_json_list(row.get("operations_json")),
            scip_symbol_id=row["scip_symbol_id"] or "",
            is_test=row.get("is_test") or False,
            source_context=row.get("source_context") or "",
        )

    def _row_to_belief(self, row: dict[str, Any]) -> ConsumerBelief:
        return ConsumerBelief(
            consumer_service=row["consumer_service"],
            field_fqn=row["field_fqn"],
            assumed_unit=row["assumed_unit"],
            assumed_type=row["assumed_type"],
            assumed_nullable=row["assumed_nullable"],
            assumed_format=row["assumed_format"],
            inferred_constraints=_json_list(row["inferred_constraints_json"]),
            usage_expressions=_json_list(row["usage_expressions_json"]),
            confidence=row["confidence"],
            extracted_at=row["extracted_at"],
            source_file_hash=row["source_file_hash"] or "",
        )

    def _row_to_disagreement(self, row: dict[str, Any]) -> Disagreement:
        return Disagreement(
            field_fqn=row["field_fqn"],
            consumer_service=row["consumer_service"],
            kind=DisagreementKind(row["kind"]),
            producer_says=row["producer_says"],
            consumer_assumes=row["consumer_assumes"],
            severity=Severity(row["severity"]),
            evidence=_json_list(row["evidence_json"]),
            explanation=row["explanation"] or "",
            detected_at=row["detected_at"],
            resolved_at=row["resolved_at"],
            fix_pr_url=row["fix_pr_url"] or "",
            source=DisagreementSource(row.get("source") or "RULES"),
            requires_human_decision=bool(row.get("requires_human_decision") or False),
            human_decision_reason=row.get("human_decision_reason") or "",
            mitigation_options=_json_list(row.get("mitigation_options_json")),
            resolution_reason=row.get("resolution_reason") or "",
        )

    def resolve_disagreement(self, field_fqn: str, consumer_service: str) -> None:
        """Mark a disagreement as resolved (human handled it)."""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE disagreements
                SET resolved_at = %s
                WHERE field_fqn = %s AND consumer_service = %s AND resolved_at IS NULL
                """,
                (datetime.now(timezone.utc), field_fqn, consumer_service),
            )
            conn.commit()

    def mark_producer_merged(self, producer_service: str) -> int:
        """Mark all active disagreements for a producer as producer_merged. Returns count."""
        with self._connect() as conn:
            result = conn.execute(
                """
                UPDATE disagreements
                SET resolved_at = %s, resolution_reason = 'producer_merged'
                WHERE resolved_at IS NULL
                  AND field_fqn LIKE %s
                RETURNING id
                """,
                (datetime.now(timezone.utc), f"{producer_service}::%"),
            )
            conn.commit()
            return result.rowcount

    def upsert_code_class(self, code_class: CodeClass) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO code_classes (
                    service_name, file_path, class_name, docstring,
                    superclasses_json, line_start, line_end, language
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s)
                ON CONFLICT (service_name, file_path, class_name) DO UPDATE SET
                    docstring = EXCLUDED.docstring,
                    superclasses_json = EXCLUDED.superclasses_json,
                    line_start = EXCLUDED.line_start,
                    line_end = EXCLUDED.line_end,
                    language = EXCLUDED.language
                """,
                (
                    code_class.service_name, code_class.file_path, code_class.class_name,
                    code_class.docstring, json.dumps(code_class.superclasses),
                    code_class.line_start, code_class.line_end, code_class.language,
                ),
            )
            conn.commit()

    def upsert_code_method(self, method: CodeMethod) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO code_methods (
                    service_name, file_path, class_name, method_name,
                    signature, docstring, line, language
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (service_name, file_path, class_name, method_name) DO UPDATE SET
                    signature = EXCLUDED.signature,
                    docstring = EXCLUDED.docstring,
                    line = EXCLUDED.line,
                    language = EXCLUDED.language
                """,
                (
                    method.service_name, method.file_path, method.class_name,
                    method.method_name, method.signature, method.docstring,
                    method.line, method.language,
                ),
            )
            conn.commit()

    def upsert_test_evidence(self, evidence: TestEvidence) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO test_evidences (
                    field_fqn, service_name, test_file, test_method,
                    assertion_code, semantic_hint
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (field_fqn, service_name, test_file, test_method) DO UPDATE SET
                    assertion_code = EXCLUDED.assertion_code,
                    semantic_hint = EXCLUDED.semantic_hint
                """,
                (
                    evidence.field_fqn, evidence.service_name, evidence.test_file,
                    evidence.test_method, evidence.assertion_code, evidence.semantic_hint,
                ),
            )
            conn.commit()

    def upsert_business_context(self, ctx: BusinessContext) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO business_contexts (
                    field_fqn, unit, domain, producer_intent, consumer_guidance,
                    invariants_json, confidence, evidence_sources_json, synthesized_at
                ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s)
                ON CONFLICT (field_fqn) DO UPDATE SET
                    unit = EXCLUDED.unit,
                    domain = EXCLUDED.domain,
                    producer_intent = EXCLUDED.producer_intent,
                    consumer_guidance = EXCLUDED.consumer_guidance,
                    invariants_json = EXCLUDED.invariants_json,
                    confidence = EXCLUDED.confidence,
                    evidence_sources_json = EXCLUDED.evidence_sources_json,
                    synthesized_at = EXCLUDED.synthesized_at
                """,
                (
                    ctx.field_fqn, ctx.unit, ctx.domain, ctx.producer_intent,
                    ctx.consumer_guidance, json.dumps(ctx.invariants),
                    ctx.confidence, json.dumps(ctx.evidence_sources), ctx.synthesized_at,
                ),
            )
            conn.commit()

    def get_business_context(self, field_fqn: str) -> Optional[BusinessContext]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM business_contexts WHERE field_fqn = %s", (field_fqn,)
            ).fetchone()
        if row is None:
            return None
        return BusinessContext(
            field_fqn=row["field_fqn"],
            unit=row["unit"],
            domain=row["domain"] or "",
            producer_intent=row["producer_intent"] or "",
            consumer_guidance=row["consumer_guidance"] or "",
            invariants=_json_list(row["invariants_json"]),
            confidence=row["confidence"],
            evidence_sources=_json_list(row["evidence_sources_json"]),
            synthesized_at=row["synthesized_at"],
        )

    def get_code_classes_for_service(self, service_name: str) -> list[CodeClass]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM code_classes WHERE service_name = %s", (service_name,)
            ).fetchall()
        return [
            CodeClass(
                service_name=r["service_name"], file_path=r["file_path"],
                class_name=r["class_name"], docstring=r["docstring"],
                superclasses=_json_list(r["superclasses_json"]),
                line_start=r["line_start"], line_end=r["line_end"], language=r["language"],
            )
            for r in rows
        ]

    def get_code_methods_for_service(self, service_name: str) -> list[CodeMethod]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM code_methods WHERE service_name = %s", (service_name,)
            ).fetchall()
        return [
            CodeMethod(
                service_name=r["service_name"], file_path=r["file_path"],
                class_name=r["class_name"], method_name=r["method_name"],
                signature=r["signature"] or "", docstring=r["docstring"],
                line=r["line"], language=r["language"],
            )
            for r in rows
        ]

    def get_test_evidences_for_field(self, field_fqn: str) -> list[TestEvidence]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM test_evidences WHERE field_fqn = %s", (field_fqn,)
            ).fetchall()
        return [
            TestEvidence(
                field_fqn=r["field_fqn"], service_name=r["service_name"],
                test_file=r["test_file"], test_method=r["test_method"],
                assertion_code=r["assertion_code"], semantic_hint=r["semantic_hint"],
            )
            for r in rows
        ]

    def upsert_drift_event(self, event: DriftEvent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO drift_events (
                    field_fqn, detected_at, previous_intent, current_intent,
                    drift_explanation, severity, is_breaking
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    event.field_fqn, event.detected_at, event.previous_intent,
                    event.current_intent, event.drift_explanation,
                    event.severity.value, event.is_breaking,
                ),
            )
            conn.commit()

    def get_drift_events(self, field_fqn: str | None = None) -> list[DriftEvent]:
        with self._connect() as conn:
            if field_fqn:
                rows = conn.execute(
                    "SELECT * FROM drift_events WHERE field_fqn = %s ORDER BY detected_at DESC",
                    (field_fqn,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM drift_events ORDER BY detected_at DESC LIMIT 200"
                ).fetchall()
        return [
            DriftEvent(
                field_fqn=r["field_fqn"], detected_at=r["detected_at"],
                previous_intent=r["previous_intent"], current_intent=r["current_intent"],
                drift_explanation=r["drift_explanation"],
                severity=Severity(r["severity"]), is_breaking=r["is_breaking"],
            )
            for r in rows
        ]

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

    def get_architectural_review_globally_enabled(self) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM global_settings WHERE key = 'architectural_review_enabled'"
            ).fetchone()
        return row["value"] == "true" if row else False

    def set_architectural_review_globally_enabled(self, enabled: bool) -> None:
        value = "true" if enabled else "false"
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO global_settings (key, value) VALUES ('architectural_review_enabled', %s)"
                " ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                (value,),
            )
            conn.commit()


def _json_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        return json.loads(value)
    return list(value)
