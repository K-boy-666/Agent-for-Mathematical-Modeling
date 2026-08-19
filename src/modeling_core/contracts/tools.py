from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Literal, TypeAlias

from pydantic import Discriminator, Field, Tag, model_validator

from modeling_core.contracts.common import (
    EntityId,
    Hash,
    JsonObject,
    ProjectSummary,
    RegistrySummary,
    StrictModel,
    Timestamp,
    Warning,
)
from modeling_core.contracts.errors import ErrorResponse

TOOL_NAMES = (
    "health_check",
    "create_project",
    "get_project_status",
    "list_capabilities",
    "run_experiment",
    "validate_experiment",
    "register_problem_assets",
    "put_subproblem_mmir",
    "confirm_subproblem_mmir",
    "export_subproblem",
)


class HealthCheckRequest(StrictModel):
    pass


class CreateProjectRequest(StrictModel):
    operation_id: EntityId
    display_name: Annotated[str | None, Field(min_length=1, max_length=128)] = None


class GetProjectStatusSummaryRequest(StrictModel):
    project_id: EntityId
    view: Literal["summary"] = "summary"
    limit: Annotated[int, Field(ge=1, le=100)] | None = None


class GetProjectStatusExperimentRequest(StrictModel):
    project_id: EntityId
    view: Literal["experiment"]
    experiment_id: EntityId
    cursor: Annotated[str, Field(min_length=1)] | None = None
    limit: Annotated[int, Field(ge=1, le=100)] | None = None


def _get_project_status_view(value: object) -> str | None:
    if isinstance(value, Mapping):
        view = value.get("view", "summary")
        return view if isinstance(view, str) else None
    view = getattr(value, "view", None)
    return view if isinstance(view, str) else None


GetProjectStatusRequest: TypeAlias = Annotated[
    Annotated[GetProjectStatusSummaryRequest, Tag("summary")]
    | Annotated[GetProjectStatusExperimentRequest, Tag("experiment")],
    Discriminator(_get_project_status_view),
]


class ListCapabilitiesSummaryRequest(StrictModel):
    detail: Literal["summary"] = "summary"
    category: str | None = None
    capability_id: str | None = None


class ListCapabilitiesContractRequest(StrictModel):
    detail: Literal["contract"]
    capability_id: str
    contract_version: str


def _list_capabilities_detail(value: object) -> str | None:
    if isinstance(value, Mapping):
        detail = value.get("detail", "summary")
        return detail if isinstance(detail, str) else None
    detail = getattr(value, "detail", None)
    return detail if isinstance(detail, str) else None


ListCapabilitiesRequest: TypeAlias = Annotated[
    Annotated[ListCapabilitiesSummaryRequest, Tag("summary")]
    | Annotated[ListCapabilitiesContractRequest, Tag("contract")],
    Discriminator(_list_capabilities_detail),
]


class CapabilitySelection(StrictModel):
    capability_id: str
    contract_version: str


class RootFindingInput(StrictModel):
    expression: Annotated[str, Field(min_length=1)]
    lower: float
    upper: float
    absolute_tolerance: Annotated[float, Field(gt=0, le=1)] = 1e-10
    relative_tolerance: Annotated[float, Field(gt=0, le=1)] = 1e-10
    function_tolerance: Annotated[float, Field(gt=0, le=1)] = 1e-10
    max_iterations: Annotated[int, Field(ge=1, le=10000)] = 100


class ExecutionOptions(StrictModel):
    timeout_ms: Annotated[int, Field(ge=1, le=60000)] = 10000
    seed: Annotated[int | None, Field(ge=-9007199254740991, le=9007199254740991)] = None


class RunExperimentRequest(StrictModel):
    operation_id: EntityId
    project_id: EntityId
    mode: Literal["new"]
    capability: CapabilitySelection
    payload: RootFindingInput
    execution: ExecutionOptions | None = None


class ValidateExperimentRequest(StrictModel):
    operation_id: EntityId
    project_id: EntityId
    attempt_id: EntityId
    expected_result_hash: Hash
    validator_id: Literal["numerical.root_finding.residual"]
    policy_version: Literal["0.1.0"]
    policy: JsonObject
    timeout_ms: Annotated[int, Field(ge=1, le=60000)] = 10000


class CommonResult(StrictModel):
    tool_contract_version: Literal["modeling-tools/0.1.0"]
    correlation_id: EntityId
    server_time: Timestamp


class CommonWriteResult(CommonResult):
    operation_id: EntityId
    replayed: bool


class HealthVersions(StrictModel):
    application_version: Literal["0.1.0"]
    mcp_protocol_version: Literal["2025-11-25"]
    tool_contract_version: Literal["modeling-tools/0.1.0"]
    project_format_version: Literal["modeling-project/0.1.0"]
    database_schema_version: Literal[1]
    capability_api_version: Literal["modeling-capability/0.1.0"]
    error_schema_version: Literal["modeling-error/0.1.0"]
    result_schema_version: Literal["modeling-result/0.1.0"]
    validation_report_schema_version: Literal["modeling-validation-report/0.1.0"]
    canonicalization_version: Literal["canonical-json/0.1.0"]
    root_finding_contract_version: Literal["numerical.root_finding/0.1.0"]
    root_finding_canonical_input_version: Literal[
        "numerical.root_finding.canonical-input/0.1.0"
    ]
    residual_policy_version: Literal["numerical.root_finding.residual/0.1.0"]

    @classmethod
    def m1a(cls) -> HealthVersions:
        return cls(
            application_version="0.1.0",
            mcp_protocol_version="2025-11-25",
            tool_contract_version="modeling-tools/0.1.0",
            project_format_version="modeling-project/0.1.0",
            database_schema_version=1,
            capability_api_version="modeling-capability/0.1.0",
            error_schema_version="modeling-error/0.1.0",
            result_schema_version="modeling-result/0.1.0",
            validation_report_schema_version="modeling-validation-report/0.1.0",
            canonicalization_version="canonical-json/0.1.0",
            root_finding_contract_version="numerical.root_finding/0.1.0",
            root_finding_canonical_input_version=(
                "numerical.root_finding.canonical-input/0.1.0"
            ),
            residual_policy_version="numerical.root_finding.residual/0.1.0",
        )


class HealthCheck(StrictModel):
    name: str
    status: Literal["OK", "WARN", "FAIL"]
    code: str


class HealthCheckResult(CommonResult):
    status: Literal["OK", "DEGRADED"]
    project_state: Literal["UNINITIALIZED", "STORAGE_READY", "READY", "DEGRADED"]
    ready_for_project_creation: bool
    versions: HealthVersions
    registry: RegistrySummary
    checks: tuple[HealthCheck, ...]
    warnings: Annotated[tuple[Warning, ...], Field(max_length=50)]


class CreateProjectResult(CommonWriteResult):
    project_id: EntityId
    display_name: Annotated[str, Field(min_length=1, max_length=128)]
    project_format_version: Literal["modeling-project/0.1.0"]
    project_state: Literal["READY"]
    created: bool
    created_at: Timestamp


class AttemptStatusCounts(StrictModel):
    pending: Annotated[int, Field(ge=0)]
    running: Annotated[int, Field(ge=0)]
    succeeded: Annotated[int, Field(ge=0)]
    numerical_failure: Annotated[int, Field(ge=0)]
    errored: Annotated[int, Field(ge=0)]
    timed_out: Annotated[int, Field(ge=0)]
    abandoned: Annotated[int, Field(ge=0)]


class ValidationStatusCounts(StrictModel):
    pending: Annotated[int, Field(ge=0)]
    running: Annotated[int, Field(ge=0)]
    succeeded: Annotated[int, Field(ge=0)]
    errored: Annotated[int, Field(ge=0)]
    timed_out: Annotated[int, Field(ge=0)]
    abandoned: Annotated[int, Field(ge=0)]


class ExperimentSummary(StrictModel):
    experiment_id: EntityId
    capability_id: str
    contract_version: str
    created_at: Timestamp
    attempt_count: Annotated[int, Field(ge=1)]
    latest_attempt_id: EntityId
    latest_attempt_status: Literal[
        "PENDING",
        "RUNNING",
        "SUCCEEDED",
        "NUMERICAL_FAILURE",
        "ERRORED",
        "TIMED_OUT",
        "ABANDONED",
    ]
    latest_attempt_at: Timestamp
    validation_count: Annotated[int, Field(ge=0)]


class ExperimentItems(StrictModel):
    items: Annotated[tuple[ExperimentSummary, ...], Field(max_length=20)]
    truncated: bool
    next_cursor: Annotated[str | None, Field(exclude=True)] = None


class GetProjectStatusSummaryResult(CommonResult):
    view: Literal["summary"]
    project: ProjectSummary
    attempt_status_counts: AttemptStatusCounts
    validation_status_counts: ValidationStatusCounts
    registry_fingerprint: Hash
    last_activity_at: Timestamp
    experiments: ExperimentItems


class NumberNode(StrictModel):
    kind: Literal["number"]
    value: float


class VariableNode(StrictModel):
    kind: Literal["variable"]
    name: Literal["x"]


class ConstantNode(StrictModel):
    kind: Literal["constant"]
    name: Literal["pi", "e"]


class UnaryNode(StrictModel):
    kind: Literal["unary"]
    op: Literal["positive", "negative"]
    operand: ExpressionNode


class BinaryNode(StrictModel):
    kind: Literal["binary"]
    op: Literal["add", "subtract", "multiply", "divide", "power"]
    left: ExpressionNode
    right: ExpressionNode


class CallNode(StrictModel):
    kind: Literal["call"]
    name: Literal["abs", "sqrt", "exp", "log", "sin", "cos", "tan"]
    argument: ExpressionNode


ExpressionNode: TypeAlias = Annotated[
    NumberNode | VariableNode | ConstantNode | UnaryNode | BinaryNode | CallNode,
    Field(discriminator="kind"),
]


class CanonicalRootFindingInput(StrictModel):
    canonical_input_schema_version: Literal[
        "numerical.root_finding.canonical-input/0.1.0"
    ]
    expression_ast: ExpressionNode
    lower: float
    upper: float
    absolute_tolerance: float
    relative_tolerance: float
    function_tolerance: float
    max_iterations: Annotated[int, Field(ge=1, le=10000)]


class DataSnapshotReference(StrictModel):
    snapshot_id: EntityId
    sha256: Hash


class ExperimentRecord(StrictModel):
    experiment_id: EntityId
    project_id: EntityId
    capability_id: str
    contract_version: str
    canonical_input_schema_version: str
    canonical_payload: CanonicalRootFindingInput
    canonical_payload_hash: Hash
    canonicalization_version: Literal["canonical-json/0.1.0"]
    model_snapshot_hash: Hash
    data_snapshot_references: tuple[DataSnapshotReference, ...]
    data_snapshot_set_hash: Hash
    execution_policy: ExecutionOptions
    created_at: Timestamp


class ResultSuccessData(StrictModel):
    root: float
    function_value: float
    iterations: Annotated[int, Field(ge=0)]
    evaluations: Annotated[int, Field(ge=1, le=20000)]
    termination_reason: Literal[
        "endpoint_root", "residual_tolerance", "interval_tolerance"
    ]


class NumericalFailureData(StrictModel):
    failure_code: Literal[
        "no_sign_change",
        "non_convergence",
        "domain_error",
        "non_finite_evaluation",
    ]
    iterations: Annotated[int, Field(ge=0)]
    evaluations: Annotated[int, Field(ge=0, le=20000)]


class SuccessResultPayload(StrictModel):
    result_schema_version: Literal["modeling-result/0.1.0"]
    capability_id: Literal["numerical.root_finding"]
    contract_version: Literal["0.1.0"]
    result_kind: Literal["success"]
    data: ResultSuccessData


class FailureResultPayload(StrictModel):
    result_schema_version: Literal["modeling-result/0.1.0"]
    capability_id: Literal["numerical.root_finding"]
    contract_version: Literal["0.1.0"]
    result_kind: Literal["numerical_failure"]
    data: NumericalFailureData


ResultPayload: TypeAlias = Annotated[
    SuccessResultPayload | FailureResultPayload, Field(discriminator="result_kind")
]


class ResultTrace(StrictModel):
    result_snapshot_id: EntityId
    result_kind: Literal["success", "numerical_failure"]
    result_schema_version: Literal["modeling-result/0.1.0"]
    result_hash: Hash
    result_payload: ResultPayload

    @model_validator(mode="after")
    def validate_matching_result_kind(self) -> ResultTrace:
        if self.result_kind != self.result_payload.result_kind:
            raise ValueError("result trace kind must match its payload kind")
        return self


class EnvironmentSummary(StrictModel):
    python_version: str
    application_version: Literal["0.1.0"]
    lock_hash: Hash


class AttemptTrace(StrictModel):
    record_type: Literal["attempt"]
    attempt_id: EntityId
    experiment_id: EntityId
    implementation_id: str
    implementation_version: str
    environment_summary: EnvironmentSummary
    randomness: str
    seed: int | None
    session_id: EntityId
    status: Literal[
        "PENDING",
        "RUNNING",
        "SUCCEEDED",
        "NUMERICAL_FAILURE",
        "ERRORED",
        "TIMED_OUT",
        "ABANDONED",
    ]
    created_at: Timestamp
    started_at: Timestamp | None
    finished_at: Timestamp | None
    warnings: Annotated[tuple[Warning, ...], Field(max_length=50)]
    result: ResultTrace | None
    system_error: ErrorResponse | None
    numerical_failure: NumericalFailureData | None
    terminal_reason: (
        Literal["deadline_exceeded", "host_cancelled", "server_recovery"] | None
    )

    @model_validator(mode="after")
    def validate_status_outputs(self) -> AttemptTrace:
        no_outputs = (
            self.result is None
            and self.system_error is None
            and self.numerical_failure is None
            and self.terminal_reason is None
        )
        if self.status == "PENDING":
            if (
                self.started_at is not None
                or self.finished_at is not None
                or not no_outputs
            ):
                raise ValueError("PENDING attempt has no timestamps or outputs")
        elif self.status == "RUNNING":
            if (
                self.started_at is None
                or self.finished_at is not None
                or not no_outputs
            ):
                raise ValueError("RUNNING attempt requires only started_at")
        elif self.status == "SUCCEEDED":
            if (
                self.started_at is None
                or self.finished_at is None
                or self.result is None
                or self.result.result_kind != "success"
                or self.system_error is not None
                or self.numerical_failure is not None
                or self.terminal_reason is not None
            ):
                raise ValueError("SUCCEEDED attempt requires only a success result")
        elif self.status == "NUMERICAL_FAILURE":
            failure_payload = (
                self.result.result_payload.data
                if self.result is not None
                and self.result.result_kind == "numerical_failure"
                else None
            )
            if (
                self.started_at is None
                or self.finished_at is None
                or failure_payload is None
                or self.numerical_failure is None
                or failure_payload != self.numerical_failure
                or self.system_error is not None
                or self.terminal_reason is not None
            ):
                raise ValueError(
                    "NUMERICAL_FAILURE attempt requires one matching failure result"
                )
        elif self.status == "ERRORED":
            if (
                self.started_at is None
                or self.finished_at is None
                or self.result is not None
                or self.system_error is None
                or self.numerical_failure is not None
                or self.terminal_reason is not None
            ):
                raise ValueError("ERRORED attempt requires only system_error")
        elif self.status == "TIMED_OUT":
            if (
                self.started_at is None
                or self.finished_at is None
                or self.result is not None
                or self.system_error is not None
                or self.numerical_failure is not None
                or self.terminal_reason != "deadline_exceeded"
            ):
                raise ValueError("TIMED_OUT attempt requires deadline_exceeded")
        elif (
            self.finished_at is None
            or self.result is not None
            or self.system_error is not None
            or self.numerical_failure is not None
            or self.terminal_reason not in {"host_cancelled", "server_recovery"}
        ):
            raise ValueError("ABANDONED attempt requires only a terminal reason")
        return self


class ValidationMetrics(StrictModel):
    root_within_interval: bool
    reported_function_value: float
    recomputed_function_value: float | None
    absolute_reported_delta: float | None
    absolute_residual: float | None
    function_tolerance: float
    failed_checks: tuple[
        Literal[
            "root_out_of_interval",
            "expression_undefined",
            "non_finite_recomputed_value",
            "reported_value_mismatch",
            "residual_exceeds_tolerance",
        ],
        ...,
    ]


class ValidationReportPayload(StrictModel):
    report_schema_version: Literal["modeling-validation-report/0.1.0"]
    validator_id: Literal["numerical.root_finding.residual"]
    validator_implementation_id: str
    validator_implementation_version: str
    policy_version: Literal["0.1.0"]
    policy: JsonObject
    policy_hash: Hash
    capability_id: Literal["numerical.root_finding"]
    contract_version: Literal["0.1.0"]
    canonical_payload_hash: Hash
    model_snapshot_hash: Hash
    data_snapshot_set_hash: Hash
    result_hash: Hash
    outcome: Literal["PASSED", "FAILED", "INCONCLUSIVE"]
    metrics: ValidationMetrics

    @model_validator(mode="after")
    def validate_empty_m1a_policy(self) -> ValidationReportPayload:
        if self.policy:
            raise ValueError("M1a residual policy must be empty")
        return self


class ValidationTrace(StrictModel):
    record_type: Literal["validation"]
    validation_id: EntityId
    attempt_id: EntityId
    expected_result_hash: Hash
    result_hash: Hash
    validator_id: Literal["numerical.root_finding.residual"]
    validator_implementation_id: str
    validator_implementation_version: str
    policy_version: Literal["0.1.0"]
    policy: JsonObject
    policy_hash: Hash
    status: Literal[
        "PENDING", "RUNNING", "SUCCEEDED", "ERRORED", "TIMED_OUT", "ABANDONED"
    ]
    created_at: Timestamp
    started_at: Timestamp | None
    finished_at: Timestamp | None
    outcome: Literal["PASSED", "FAILED", "INCONCLUSIVE"] | None
    metrics: ValidationMetrics | None
    validation_report_hash: Hash | None
    report_payload: ValidationReportPayload | None
    operational_error: ErrorResponse | None
    terminal_reason: (
        Literal["deadline_exceeded", "host_cancelled", "server_recovery"] | None
    )

    @model_validator(mode="after")
    def validate_empty_m1a_policy(self) -> ValidationTrace:
        if self.policy:
            raise ValueError("M1a residual policy must be empty")
        return self

    @model_validator(mode="after")
    def validate_status_outputs(self) -> ValidationTrace:
        no_outputs = (
            self.outcome is None
            and self.metrics is None
            and self.validation_report_hash is None
            and self.report_payload is None
            and self.operational_error is None
            and self.terminal_reason is None
        )
        if self.status == "PENDING":
            if (
                self.started_at is not None
                or self.finished_at is not None
                or not no_outputs
            ):
                raise ValueError("PENDING validation has no timestamps or outputs")
        elif self.status == "RUNNING":
            if (
                self.started_at is None
                or self.finished_at is not None
                or not no_outputs
            ):
                raise ValueError("RUNNING validation requires only started_at")
        elif self.status == "SUCCEEDED":
            if (
                self.started_at is None
                or self.finished_at is None
                or self.outcome is None
                or self.metrics is None
                or self.validation_report_hash is None
                or self.report_payload is None
                or self.report_payload.outcome != self.outcome
                or self.report_payload.metrics != self.metrics
                or self.report_payload.result_hash != self.result_hash
                or self.operational_error is not None
                or self.terminal_reason is not None
            ):
                raise ValueError(
                    "SUCCEEDED validation requires one consistent report payload"
                )
        elif self.status == "ERRORED":
            if (
                self.started_at is None
                or self.finished_at is None
                or self.outcome is not None
                or self.metrics is not None
                or self.validation_report_hash is not None
                or self.report_payload is not None
                or self.operational_error is None
                or self.terminal_reason is not None
            ):
                raise ValueError("ERRORED validation requires only operational_error")
        elif self.status == "TIMED_OUT":
            if (
                self.started_at is None
                or self.finished_at is None
                or self.outcome is not None
                or self.metrics is not None
                or self.validation_report_hash is not None
                or self.report_payload is not None
                or self.operational_error is not None
                or self.terminal_reason != "deadline_exceeded"
            ):
                raise ValueError("TIMED_OUT validation requires deadline_exceeded")
        elif (
            self.finished_at is None
            or self.outcome is not None
            or self.metrics is not None
            or self.validation_report_hash is not None
            or self.report_payload is not None
            or self.operational_error is not None
            or self.terminal_reason not in {"host_cancelled", "server_recovery"}
        ):
            raise ValueError("ABANDONED validation requires only a terminal reason")
        return self


TraceRecord: TypeAlias = Annotated[
    AttemptTrace | ValidationTrace, Field(discriminator="record_type")
]


class GetProjectStatusExperimentResult(CommonResult):
    view: Literal["experiment"]
    project: ProjectSummary
    experiment: ExperimentRecord
    trace: tuple[TraceRecord, ...]
    next_cursor: Annotated[str | None, Field(exclude=True)] = None


GetProjectStatusResult: TypeAlias = Annotated[
    GetProjectStatusSummaryResult | GetProjectStatusExperimentResult,
    Field(discriminator="view"),
]


class CapabilitySummary(StrictModel):
    capability_id: str
    contract_version: str
    title: str
    summary: str
    category: str
    tags: tuple[str, ...]
    determinism: str
    randomness: str
    input_schema_hash: Hash
    canonical_input_schema_version: str
    canonical_input_schema_hash: Hash
    success_schema_hash: Hash
    failure_schema_hash: Hash


class PolicyContract(StrictModel):
    policy_version: str
    policy_schema: JsonObject
    policy_schema_hash: Hash


class ValidatorSummary(StrictModel):
    validator_id: str
    policies: tuple[PolicyContract, ...]
    report_schema_version: str
    report_schema: JsonObject
    report_schema_hash: Hash
    summary: str


class CapabilityLimits(StrictModel):
    timeout_ms: Annotated[int, Field(ge=0)]
    max_iterations: Annotated[int, Field(ge=0)]
    max_evaluations: Annotated[int, Field(ge=0)]


class CapabilityContract(CapabilitySummary):
    capability_api_version: Literal["modeling-capability/0.1.0"]
    implementation_id: str
    implementation_version: str
    input_schema: JsonObject
    canonical_input_schema: JsonObject
    success_schema: JsonObject
    failure_schema: JsonObject
    default_limits: CapabilityLimits
    maximum_limits: CapabilityLimits
    artifact_roles: tuple[()]
    validators: tuple[ValidatorSummary, ...]
    context_ref: str


class ListCapabilitiesSummaryResult(CommonResult):
    detail: Literal["summary"]
    registry: RegistrySummary
    capabilities: tuple[CapabilitySummary, ...]


class ListCapabilitiesContractResult(CommonResult):
    detail: Literal["contract"]
    registry: RegistrySummary
    capability: CapabilityContract


ListCapabilitiesResult: TypeAlias = Annotated[
    ListCapabilitiesSummaryResult | ListCapabilitiesContractResult,
    Field(discriminator="detail"),
]


class RunResultBase(CommonWriteResult):
    experiment_id: EntityId
    attempt_id: EntityId
    capability_id: str
    contract_version: str
    implementation_id: str
    implementation_version: str
    randomness: str
    seed: int | None
    warnings: Annotated[tuple[Warning, ...], Field(max_length=50)]


class RunExperimentSucceededResult(RunResultBase):
    attempt_status: Literal["SUCCEEDED"]
    result_kind: Literal["success"]
    result_hash: Hash
    result_summary: ResultSuccessData


class RunExperimentNumericalFailureResult(RunResultBase):
    attempt_status: Literal["NUMERICAL_FAILURE"]
    result_kind: Literal["numerical_failure"]
    result_hash: Hash
    result_summary: NumericalFailureData


class RunExperimentErroredResult(RunResultBase):
    attempt_status: Literal["ERRORED"]
    system_error: ErrorResponse


class RunExperimentStoppedResult(RunResultBase):
    attempt_status: Literal["TIMED_OUT", "ABANDONED"]
    terminal_reason: Literal["deadline_exceeded", "host_cancelled", "server_recovery"]


RunExperimentResult: TypeAlias = (
    RunExperimentSucceededResult
    | RunExperimentNumericalFailureResult
    | RunExperimentErroredResult
    | RunExperimentStoppedResult
)


class ValidationResultBase(CommonWriteResult):
    validation_id: EntityId
    attempt_id: EntityId
    result_hash: Hash
    validator_id: Literal["numerical.root_finding.residual"]
    validator_implementation_id: str
    validator_implementation_version: str
    policy_version: Literal["0.1.0"]
    policy_hash: Hash


class ValidateExperimentSucceededResult(ValidationResultBase):
    validation_status: Literal["SUCCEEDED"]
    outcome: Literal["PASSED", "FAILED", "INCONCLUSIVE"]
    metrics: ValidationMetrics
    validation_report_hash: Hash


class ValidateExperimentErroredResult(ValidationResultBase):
    validation_status: Literal["ERRORED"]
    operational_error: ErrorResponse


class ValidateExperimentStoppedResult(ValidationResultBase):
    validation_status: Literal["TIMED_OUT", "ABANDONED"]
    terminal_reason: Literal["deadline_exceeded", "host_cancelled", "server_recovery"]


ValidateExperimentResult: TypeAlias = (
    ValidateExperimentSucceededResult
    | ValidateExperimentErroredResult
    | ValidateExperimentStoppedResult
)


# ── C1 preview tool contracts ──


class AssetPathEntry(StrictModel):
    label: Annotated[str, Field(min_length=1, max_length=128)]
    path: Annotated[str, Field(min_length=1)]


class RegisterProblemAssetsRequest(StrictModel):
    operation_id: EntityId
    project_id: EntityId
    asset_paths: Annotated[
        tuple[AssetPathEntry, ...], Field(min_length=1, max_length=20)
    ]


class AssetSnapshotEntry(StrictModel):
    label: str
    sha256: Hash
    official_match: bool


class RegisterProblemAssetsResult(CommonWriteResult):
    project_id: EntityId
    snapshots: tuple[AssetSnapshotEntry, ...]


class MmirContent(StrictModel):
    schema_version: Literal["modeling-mmir/0.1.0"]
    problem_id: Annotated[str, Field(min_length=1)]
    question_id: Annotated[str, Field(min_length=1)]
    assumptions: Annotated[tuple[str, ...], Field(min_length=1)]
    asset_labels: tuple[str, ...] = ()
    derivation: str = ""
    parameters: JsonObject = {}


class PutSubproblemMmirRequest(StrictModel):
    operation_id: EntityId
    project_id: EntityId
    subproblem_id: Annotated[str, Field(min_length=1, max_length=128)]
    mmir: MmirContent


class PutSubproblemMmirResult(CommonWriteResult):
    project_id: EntityId
    subproblem_id: str
    mmir_revision: Hash
    status: Literal["UNCONFIRMED", "CONFIRMED"]


class ConfirmSubproblemMmirRequest(StrictModel):
    operation_id: EntityId
    project_id: EntityId
    subproblem_id: Annotated[str, Field(min_length=1, max_length=128)]
    mmir_revision: Hash


class ConfirmSubproblemMmirResult(CommonWriteResult):
    project_id: EntityId
    subproblem_id: str
    mmir_revision: Hash
    status: Literal["CONFIRMED"]


class ExportEntry(StrictModel):
    kind: Annotated[str, Field(min_length=1)]
    label: Annotated[str, Field(min_length=1)]
    sha256: Hash


class ExportSubproblemRequest(StrictModel):
    operation_id: EntityId
    project_id: EntityId
    subproblem_id: Annotated[str, Field(min_length=1, max_length=128)]


class ExportSubproblemResult(CommonWriteResult):
    project_id: EntityId
    subproblem_id: str
    exports: tuple[ExportEntry, ...]
