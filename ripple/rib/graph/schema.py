from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class TransportKind(str, Enum):
    REST = "REST"
    KAFKA = "KAFKA"
    GRPC = "GRPC"
    GRAPHQL = "GRAPHQL"
    SHARED_LIB = "SHARED_LIB"


class DisagreementKind(str, Enum):
    UNIT_MISMATCH = "UNIT_MISMATCH"
    TYPE_CHANGED = "TYPE_CHANGED"
    NULLABLE_CHANGED = "NULLABLE_CHANGED"
    ENUM_VALUE_CHANGED = "ENUM_VALUE_CHANGED"
    CONSTRAINT_UNKNOWN_TO_CONSUMER = "CONSTRAINT_UNKNOWN_TO_CONSUMER"
    FORMAT_MISMATCH = "FORMAT_MISMATCH"
    FIELD_REMOVED = "FIELD_REMOVED"
    NEW_REQUIRED_FIELD = "NEW_REQUIRED_FIELD"
    ANNOTATION_CHANGE = "ANNOTATION_CHANGE"          # serialization annotation changed (@JsonProperty, @JsonValue)
    STRUCTURE_CHANGE = "STRUCTURE_CHANGE"            # response shape changed (string → object wrapper)
    BEHAVIORAL_CHANGE = "BEHAVIORAL_CHANGE"          # behavior changed, schema looks identical
    SEMANTIC_INTENT_MISMATCH = "SEMANTIC_INTENT_MISMATCH"  # consumer assumption conflicts with producer's stated intent


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Constraint(BaseModel):
    kind: str
    value: str
    source: str


class FieldNode(BaseModel):
    fqn: str
    name: str
    producer_service: str
    transport: TransportKind
    endpoint_or_topic: str
    field_path: str
    declared_type: str
    nullable: bool
    deprecated: bool = False
    constraints: list[Constraint] = []
    schema_source_path: str = ""


class SymbolNode(BaseModel):
    scip_id: str
    display_name: str
    kind: str
    service_name: str
    file_path: str
    line: int
    containing_function: str = ""
    visibility: str = "public"


class FieldUsage(BaseModel):
    field_fqn: str
    consumer_service: str
    file_path: str
    line: int
    expression: str
    surrounding_context: str
    containing_function: str = ""
    containing_class: str = ""
    local_var_name: str = ""
    operations: list[str] = []
    scip_symbol_id: str = ""
    is_test: bool = False          # True when file_path matches a test pattern
    source_context: str = ""       # 3-5 source lines around the usage for operation inference


class HistorySignal(BaseModel):
    field_fqn: str
    commit_hash: str
    commit_message: str
    author: str
    committed_at: datetime
    risk_keywords: list[str] = []


class SemanticProfile(BaseModel):
    field_fqn: str
    unit: Optional[str]
    domain: Optional[str]
    invariants: list[str] = []
    risk_flags: list[str] = []
    confidence: float
    evidence: list[str] = []
    generated_at: datetime
    source_commit_hash: str = ""


class ConsumerBelief(BaseModel):
    consumer_service: str
    field_fqn: str
    assumed_unit: Optional[str]
    assumed_type: Optional[str]
    assumed_nullable: Optional[bool]
    assumed_format: Optional[str]
    inferred_constraints: list[str] = []
    usage_expressions: list[str] = []
    confidence: float
    extracted_at: datetime
    source_file_hash: str = ""


class DisagreementSource(str, Enum):
    RULES = "RULES"
    LLM = "LLM"


class Disagreement(BaseModel):
    field_fqn: str
    consumer_service: str
    kind: DisagreementKind
    producer_says: str
    consumer_assumes: str
    severity: Severity
    evidence: list[str] = []
    explanation: str = ""
    detected_at: datetime
    resolved_at: Optional[datetime] = None
    fix_pr_url: str = ""
    source: DisagreementSource = DisagreementSource.RULES
    requires_human_decision: bool = False
    human_decision_reason: str = ""
    mitigation_options: list[dict] = []  # list of {id, label, description}
    resolution_reason: str = ""


class DriftEvent(BaseModel):
    field_fqn: str
    detected_at: datetime
    previous_intent: str
    current_intent: str
    drift_explanation: str
    severity: Severity
    is_breaking: bool = False


class CodeClass(BaseModel):
    service_name: str
    file_path: str
    class_name: str
    docstring: Optional[str] = None
    superclasses: list[str] = []
    line_start: int = 0
    line_end: int = 0
    language: str = ""


class CodeMethod(BaseModel):
    service_name: str
    file_path: str
    class_name: Optional[str] = None
    method_name: str
    signature: str = ""
    docstring: Optional[str] = None
    line: int = 0
    language: str = ""


class TestEvidence(BaseModel):
    field_fqn: str
    service_name: str
    test_file: str
    test_method: str
    assertion_code: str
    semantic_hint: Optional[str] = None


class BusinessContext(BaseModel):
    field_fqn: str
    unit: Optional[str] = None
    domain: str = ""
    producer_intent: str = ""
    consumer_guidance: str = ""
    invariants: list[str] = []
    confidence: float = 0.0
    evidence_sources: list[str] = []
    synthesized_at: datetime


class ArchitecturalIntent(BaseModel):
    id: Optional[int] = None
    repo: str
    constraint_type: str
    natural_language: str
    encoded_rule: dict = {}
    source: str = "learned"
    pr_url: Optional[str] = None
    pr_comment_id: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ServiceRecord(BaseModel):
    name: str
    repo_url: str = ""
    language: str = ""
    role: str = ""          # "producer" | "consumer" | "both"
    field_count: int = 0
    consumer_count: int = 0
    last_indexed_at: Optional[datetime] = None


class BlastRadiusEntry(BaseModel):
    consumer_service: str
    repo_url: str
    usages: list[FieldUsage]
    active_disagreements: list[Disagreement]
    belief: Optional[ConsumerBelief]


class BlastRadius(BaseModel):
    field: FieldNode
    semantic_profile: Optional[SemanticProfile]
    consumers: list[BlastRadiusEntry]
    total_consumers: int
    critical_disagreement_count: int


class ServiceRole(str, Enum):
    PRODUCER = "producer"
    CONSUMER = "consumer"


class ServiceSpec(BaseModel):
    repo_url: str
    service_name: str = ""
    roles: list[ServiceRole]
    openapi_path: str = "openapi.yaml"


class IngestEcosystemRequest(BaseModel):
    services: list[ServiceSpec]
    tenant_id: str = "default"


class IngestionRequest(BaseModel):
    producer_repo_url: str
    consumer_repo_urls: list[str]
    openapi_path: str = "openapi.yaml"


class IngestionResult(BaseModel):
    services_indexed: list[str]
    fields_extracted: int
    usages_found: int
    beliefs_extracted: int
    disagreements_detected: int
    llm_profiles_generated: int
    duration_seconds: float
    workflow_id: str = ""
    errors: list[str] = []


class IngestWorkflowStatus(BaseModel):
    workflow_id: str
    run_id: str
    status: str
    progress: dict[str, str | int] = {}
    result: IngestionResult | None = None


class AnalyzePRRequest(BaseModel):
    repo: str
    prNumber: int
    branch: str
    baseBranch: str
    headCommit: str
    producerService: str = ""
    githubToken: str = ""


class AnalyzeWorkflowStatus(BaseModel):
    workflow_id: str
    run_id: str
    status: str
    diff_path: str = ""
    lines_changed: int = 0
