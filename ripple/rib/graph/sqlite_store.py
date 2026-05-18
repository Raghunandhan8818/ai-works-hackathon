from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from ripple.rib.graph.schema import (
    BlastRadius,
    BlastRadiusEntry,
    Constraint,
    ConsumerBelief,
    Disagreement,
    DisagreementKind,
    FieldNode,
    FieldUsage,
    HistorySignal,
    SemanticProfile,
    Severity,
    SymbolNode,
    TransportKind,
)

SCHEMA_VERSION = 1

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS services (
        name TEXT PRIMARY KEY,
        repo_url TEXT,
        language TEXT,
        last_indexed_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fields (
        fqn TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        producer_service TEXT NOT NULL,
        transport TEXT NOT NULL,
        endpoint_or_topic TEXT NOT NULL,
        field_path TEXT NOT NULL,
        declared_type TEXT NOT NULL,
        nullable INTEGER NOT NULL,
        deprecated INTEGER NOT NULL DEFAULT 0,
        schema_source_path TEXT,
        constraints_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS symbols (
        scip_id TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        kind TEXT NOT NULL,
        service_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        line INTEGER NOT NULL,
        containing_function TEXT,
        visibility TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS field_usages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        field_fqn TEXT NOT NULL,
        consumer_service TEXT NOT NULL,
        file_path TEXT NOT NULL,
        line INTEGER NOT NULL,
        expression TEXT NOT NULL,
        surrounding_context TEXT,
        containing_function TEXT,
        scip_symbol_id TEXT,
        UNIQUE(field_fqn, consumer_service, file_path, line)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS history_signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        field_fqn TEXT NOT NULL,
        commit_hash TEXT NOT NULL,
        commit_message TEXT NOT NULL,
        author TEXT NOT NULL,
        committed_at TEXT NOT NULL,
        risk_keywords_json TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS semantic_profiles (
        field_fqn TEXT PRIMARY KEY,
        unit TEXT,
        domain TEXT,
        invariants_json TEXT,
        risk_flags_json TEXT,
        confidence REAL NOT NULL,
        evidence_json TEXT,
        generated_at TEXT NOT NULL,
        source_commit_hash TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS consumer_beliefs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        consumer_service TEXT NOT NULL,
        field_fqn TEXT NOT NULL,
        assumed_unit TEXT,
        assumed_type TEXT,
        assumed_nullable INTEGER,
        assumed_format TEXT,
        inferred_constraints_json TEXT,
        usage_expressions_json TEXT,
        confidence REAL NOT NULL,
        extracted_at TEXT NOT NULL,
        source_file_hash TEXT,
        UNIQUE(consumer_service, field_fqn)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS disagreements (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        field_fqn TEXT NOT NULL,
        consumer_service TEXT NOT NULL,
        kind TEXT NOT NULL,
        producer_says TEXT NOT NULL,
        consumer_assumes TEXT NOT NULL,
        severity TEXT NOT NULL,
        evidence_json TEXT,
        explanation TEXT,
        detected_at TEXT NOT NULL,
        resolved_at TEXT,
        fix_pr_url TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS indexed_files (
        service_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        content_hash TEXT NOT NULL,
        indexed_at TEXT NOT NULL,
        PRIMARY KEY (service_name, file_path)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_usages_field ON field_usages(field_fqn)",
    "CREATE INDEX IF NOT EXISTS idx_usages_consumer ON field_usages(consumer_service)",
    "CREATE INDEX IF NOT EXISTS idx_beliefs_field ON consumer_beliefs(field_fqn)",
    "CREATE INDEX IF NOT EXISTS idx_disagreements_field ON disagreements(field_fqn)",
    "CREATE INDEX IF NOT EXISTS idx_disagreements_unresolved ON disagreements(resolved_at) WHERE resolved_at IS NULL",
    "CREATE INDEX IF NOT EXISTS idx_history_field ON history_signals(field_fqn)",
]


class SQLiteStore:
    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self._database_path))
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._initialize_schema()

    def close(self) -> None:
        self._connection.close()

    def _initialize_schema(self) -> None:
        for statement in DDL_STATEMENTS:
            self._connection.execute(statement)
        row = self._connection.execute(
            "SELECT version FROM schema_version LIMIT 1"
        ).fetchone()
        if row is None:
            self._connection.execute(
                "INSERT INTO schema_version (version) VALUES (?)", (SCHEMA_VERSION,)
            )
        self._connection.commit()

    def upsert_field(self, field: FieldNode) -> None:
        constraints_json = json.dumps([c.model_dump() for c in field.constraints])
        self._connection.execute(
            """
            INSERT INTO fields (
                fqn, name, producer_service, transport, endpoint_or_topic,
                field_path, declared_type, nullable, deprecated,
                schema_source_path, constraints_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(fqn) DO UPDATE SET
                name=excluded.name,
                producer_service=excluded.producer_service,
                transport=excluded.transport,
                endpoint_or_topic=excluded.endpoint_or_topic,
                field_path=excluded.field_path,
                declared_type=excluded.declared_type,
                nullable=excluded.nullable,
                deprecated=excluded.deprecated,
                schema_source_path=excluded.schema_source_path,
                constraints_json=excluded.constraints_json
            """,
            (
                field.fqn,
                field.name,
                field.producer_service,
                field.transport.value,
                field.endpoint_or_topic,
                field.field_path,
                field.declared_type,
                int(field.nullable),
                int(field.deprecated),
                field.schema_source_path,
                constraints_json,
            ),
        )
        self._connection.commit()

    def upsert_symbol(self, symbol: SymbolNode) -> None:
        self._connection.execute(
            """
            INSERT INTO symbols (
                scip_id, display_name, kind, service_name,
                file_path, line, containing_function, visibility
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scip_id) DO UPDATE SET
                display_name=excluded.display_name,
                kind=excluded.kind,
                service_name=excluded.service_name,
                file_path=excluded.file_path,
                line=excluded.line,
                containing_function=excluded.containing_function,
                visibility=excluded.visibility
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
        self._connection.commit()

    def upsert_usage(self, usage: FieldUsage) -> None:
        self._connection.execute(
            """
            INSERT INTO field_usages (
                field_fqn, consumer_service, file_path, line,
                expression, surrounding_context, containing_function, scip_symbol_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(field_fqn, consumer_service, file_path, line) DO UPDATE SET
                expression=excluded.expression,
                surrounding_context=excluded.surrounding_context,
                containing_function=excluded.containing_function,
                scip_symbol_id=excluded.scip_symbol_id
            """,
            (
                usage.field_fqn,
                usage.consumer_service,
                usage.file_path,
                usage.line,
                usage.expression,
                usage.surrounding_context,
                usage.containing_function,
                usage.scip_symbol_id,
            ),
        )
        self._connection.commit()

    def upsert_history_signal(self, signal: HistorySignal) -> None:
        self._connection.execute(
            """
            INSERT INTO history_signals (
                field_fqn, commit_hash, commit_message, author,
                committed_at, risk_keywords_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                signal.field_fqn,
                signal.commit_hash,
                signal.commit_message,
                signal.author,
                signal.committed_at.isoformat(),
                json.dumps(signal.risk_keywords),
            ),
        )
        self._connection.commit()

    def upsert_semantic_profile(self, profile: SemanticProfile) -> None:
        self._connection.execute(
            """
            INSERT INTO semantic_profiles (
                field_fqn, unit, domain, invariants_json, risk_flags_json,
                confidence, evidence_json, generated_at, source_commit_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(field_fqn) DO UPDATE SET
                unit=excluded.unit,
                domain=excluded.domain,
                invariants_json=excluded.invariants_json,
                risk_flags_json=excluded.risk_flags_json,
                confidence=excluded.confidence,
                evidence_json=excluded.evidence_json,
                generated_at=excluded.generated_at,
                source_commit_hash=excluded.source_commit_hash
            """,
            (
                profile.field_fqn,
                profile.unit,
                profile.domain,
                json.dumps(profile.invariants),
                json.dumps(profile.risk_flags),
                profile.confidence,
                json.dumps(profile.evidence),
                profile.generated_at.isoformat(),
                profile.source_commit_hash,
            ),
        )
        self._connection.commit()

    def upsert_consumer_belief(self, belief: ConsumerBelief) -> None:
        self._connection.execute(
            """
            INSERT INTO consumer_beliefs (
                consumer_service, field_fqn, assumed_unit, assumed_type,
                assumed_nullable, assumed_format, inferred_constraints_json,
                usage_expressions_json, confidence, extracted_at, source_file_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(consumer_service, field_fqn) DO UPDATE SET
                assumed_unit=excluded.assumed_unit,
                assumed_type=excluded.assumed_type,
                assumed_nullable=excluded.assumed_nullable,
                assumed_format=excluded.assumed_format,
                inferred_constraints_json=excluded.inferred_constraints_json,
                usage_expressions_json=excluded.usage_expressions_json,
                confidence=excluded.confidence,
                extracted_at=excluded.extracted_at,
                source_file_hash=excluded.source_file_hash
            """,
            (
                belief.consumer_service,
                belief.field_fqn,
                belief.assumed_unit,
                belief.assumed_type,
                None if belief.assumed_nullable is None else int(belief.assumed_nullable),
                belief.assumed_format,
                json.dumps(belief.inferred_constraints),
                json.dumps(belief.usage_expressions),
                belief.confidence,
                belief.extracted_at.isoformat(),
                belief.source_file_hash,
            ),
        )
        self._connection.commit()

    def upsert_disagreement(self, disagreement: Disagreement) -> None:
        self._connection.execute(
            """
            INSERT INTO disagreements (
                field_fqn, consumer_service, kind, producer_says, consumer_assumes,
                severity, evidence_json, explanation, detected_at, resolved_at, fix_pr_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                disagreement.detected_at.isoformat(),
                disagreement.resolved_at.isoformat() if disagreement.resolved_at else None,
                disagreement.fix_pr_url,
            ),
        )
        self._connection.commit()

    def get_field(self, field_fqn: str) -> Optional[FieldNode]:
        row = self._connection.execute(
            "SELECT * FROM fields WHERE fqn = ?", (field_fqn,)
        ).fetchone()
        if row is None:
            return None
        return self._row_to_field(row)

    def get_semantic_profile(self, field_fqn: str) -> Optional[SemanticProfile]:
        row = self._connection.execute(
            "SELECT * FROM semantic_profiles WHERE field_fqn = ?", (field_fqn,)
        ).fetchone()
        if row is None:
            return None
        return SemanticProfile(
            field_fqn=row["field_fqn"],
            unit=row["unit"],
            domain=row["domain"],
            invariants=json.loads(row["invariants_json"] or "[]"),
            risk_flags=json.loads(row["risk_flags_json"] or "[]"),
            confidence=row["confidence"],
            evidence=json.loads(row["evidence_json"] or "[]"),
            generated_at=datetime.fromisoformat(row["generated_at"]),
            source_commit_hash=row["source_commit_hash"] or "",
        )

    def get_consumer_belief(
        self, consumer_service: str, field_fqn: str
    ) -> Optional[ConsumerBelief]:
        row = self._connection.execute(
            """
            SELECT * FROM consumer_beliefs
            WHERE consumer_service = ? AND field_fqn = ?
            """,
            (consumer_service, field_fqn),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_belief(row)

    def get_usages_for_field(self, field_fqn: str) -> list[FieldUsage]:
        rows = self._connection.execute(
            "SELECT * FROM field_usages WHERE field_fqn = ?", (field_fqn,)
        ).fetchall()
        return [self._row_to_usage(row) for row in rows]

    def get_history_signals(self, field_fqn: str) -> list[HistorySignal]:
        rows = self._connection.execute(
            "SELECT * FROM history_signals WHERE field_fqn = ? ORDER BY committed_at DESC",
            (field_fqn,),
        ).fetchall()
        return [
            HistorySignal(
                field_fqn=row["field_fqn"],
                commit_hash=row["commit_hash"],
                commit_message=row["commit_message"],
                author=row["author"],
                committed_at=datetime.fromisoformat(row["committed_at"]),
                risk_keywords=json.loads(row["risk_keywords_json"] or "[]"),
            )
            for row in rows
        ]

    def get_active_disagreements(self) -> list[Disagreement]:
        rows = self._connection.execute(
            "SELECT * FROM disagreements WHERE resolved_at IS NULL ORDER BY detected_at DESC"
        ).fetchall()
        return [self._row_to_disagreement(row) for row in rows]

    def get_disagreements_for_field(self, field_fqn: str) -> list[Disagreement]:
        rows = self._connection.execute(
            "SELECT * FROM disagreements WHERE field_fqn = ?", (field_fqn,)
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
                    repo_url="",
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
        rows = self._connection.execute("SELECT * FROM fields").fetchall()
        return [self._row_to_field(row) for row in rows]

    def get_fields_for_service(self, service_name: str) -> list[FieldNode]:
        rows = self._connection.execute(
            "SELECT * FROM fields WHERE producer_service = ?", (service_name,)
        ).fetchall()
        return [self._row_to_field(row) for row in rows]

    def mark_disagreement_resolved(
        self, field_fqn: str, consumer_service: str, fix_pr_url: str
    ) -> None:
        self._connection.execute(
            """
            UPDATE disagreements
            SET resolved_at = ?, fix_pr_url = ?
            WHERE field_fqn = ? AND consumer_service = ? AND resolved_at IS NULL
            """,
            (datetime.utcnow().isoformat(), fix_pr_url, field_fqn, consumer_service),
        )
        self._connection.commit()

    def get_file_content_hash(self, file_path: str, service_name: str) -> Optional[str]:
        row = self._connection.execute(
            "SELECT content_hash FROM indexed_files WHERE service_name = ? AND file_path = ?",
            (service_name, file_path),
        ).fetchone()
        return row["content_hash"] if row else None

    def upsert_indexed_file(
        self, service_name: str, file_path: str, content_hash: str
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO indexed_files (service_name, file_path, content_hash, indexed_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(service_name, file_path) DO UPDATE SET
                content_hash=excluded.content_hash,
                indexed_at=excluded.indexed_at
            """,
            (service_name, file_path, content_hash, datetime.utcnow().isoformat()),
        )
        self._connection.commit()

    def _row_to_field(self, row: sqlite3.Row) -> FieldNode:
        constraints_raw = json.loads(row["constraints_json"] or "[]")
        constraints = [Constraint(**c) for c in constraints_raw]
        return FieldNode(
            fqn=row["fqn"],
            name=row["name"],
            producer_service=row["producer_service"],
            transport=TransportKind(row["transport"]),
            endpoint_or_topic=row["endpoint_or_topic"],
            field_path=row["field_path"],
            declared_type=row["declared_type"],
            nullable=bool(row["nullable"]),
            deprecated=bool(row["deprecated"]),
            constraints=constraints,
            schema_source_path=row["schema_source_path"] or "",
        )

    def _row_to_usage(self, row: sqlite3.Row) -> FieldUsage:
        return FieldUsage(
            field_fqn=row["field_fqn"],
            consumer_service=row["consumer_service"],
            file_path=row["file_path"],
            line=row["line"],
            expression=row["expression"],
            surrounding_context=row["surrounding_context"] or "",
            containing_function=row["containing_function"] or "",
            scip_symbol_id=row["scip_symbol_id"] or "",
        )

    def _row_to_belief(self, row: sqlite3.Row) -> ConsumerBelief:
        assumed_nullable = row["assumed_nullable"]
        return ConsumerBelief(
            consumer_service=row["consumer_service"],
            field_fqn=row["field_fqn"],
            assumed_unit=row["assumed_unit"],
            assumed_type=row["assumed_type"],
            assumed_nullable=None if assumed_nullable is None else bool(assumed_nullable),
            assumed_format=row["assumed_format"],
            inferred_constraints=json.loads(row["inferred_constraints_json"] or "[]"),
            usage_expressions=json.loads(row["usage_expressions_json"] or "[]"),
            confidence=row["confidence"],
            extracted_at=datetime.fromisoformat(row["extracted_at"]),
            source_file_hash=row["source_file_hash"] or "",
        )

    def _row_to_disagreement(self, row: sqlite3.Row) -> Disagreement:
        resolved_at = row["resolved_at"]
        return Disagreement(
            field_fqn=row["field_fqn"],
            consumer_service=row["consumer_service"],
            kind=DisagreementKind(row["kind"]),
            producer_says=row["producer_says"],
            consumer_assumes=row["consumer_assumes"],
            severity=Severity(row["severity"]),
            evidence=json.loads(row["evidence_json"] or "[]"),
            explanation=row["explanation"] or "",
            detected_at=datetime.fromisoformat(row["detected_at"]),
            resolved_at=datetime.fromisoformat(resolved_at) if resolved_at else None,
            fix_pr_url=row["fix_pr_url"] or "",
        )
