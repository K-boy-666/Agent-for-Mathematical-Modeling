"""Concrete host-neutral orchestration for the six M1a use cases."""

from __future__ import annotations

import threading
import unicodedata
from datetime import UTC, datetime
from typing import Literal, NoReturn, TypedDict, cast

from pydantic import TypeAdapter

from modeling_core.application.facade import ApplicationFacade
from modeling_core.application.idempotency import (
    create_project_request_hash,
    run_experiment_request_hash,
    validate_experiment_request_hash,
)
from modeling_core.contracts.canonical_json import sha256_json
from modeling_core.contracts.capability import (
    CancellationSignal,
    CanonicalInputRecord,
    CapabilityInputRejected,
    CapabilityInputResourceLimitExceeded,
    CapabilitySecurityViolation,
    ExecutionCancelled,
    ExecutionContext,
    ExecutionDeadlineExceeded,
    ExecutionResourceLimitExceeded,
    ResultSnapshotView,
    ValidationContext,
)
from modeling_core.contracts.common import (
    EntityId,
    JsonObject,
    ProjectSummary,
    RegistrySummary,
    Warning,
)
from modeling_core.contracts.errors import (
    ErrorDetails,
    ErrorResponse,
    ModelingError,
    UnsupportedVersionDetails,
)
from modeling_core.contracts.tools import (
    AttemptTrace,
    CapabilityContract,
    CanonicalRootFindingInput,
    CreateProjectRequest,
    CreateProjectResult,
    DataSnapshotReference,
    EnvironmentSummary,
    ExecutionOptions,
    ExperimentItems,
    ExperimentRecord,
    GetProjectStatusExperimentRequest,
    GetProjectStatusExperimentResult,
    GetProjectStatusRequest,
    GetProjectStatusResult,
    GetProjectStatusSummaryRequest,
    GetProjectStatusSummaryResult,
    HealthCheck,
    HealthCheckRequest,
    HealthCheckResult,
    HealthVersions,
    ListCapabilitiesContractRequest,
    ListCapabilitiesContractResult,
    ListCapabilitiesRequest,
    ListCapabilitiesResult,
    ListCapabilitiesSummaryRequest,
    ListCapabilitiesSummaryResult,
    ResultTrace,
    RunExperimentErroredResult,
    RunExperimentNumericalFailureResult,
    RunExperimentRequest,
    RunExperimentResult,
    RunExperimentStoppedResult,
    RunExperimentSucceededResult,
    SuccessResultPayload,
    FailureResultPayload,
    ValidateExperimentRequest,
    ValidateExperimentErroredResult,
    ValidateExperimentResult,
    ValidateExperimentStoppedResult,
    ValidateExperimentSucceededResult,
    ValidationTrace,
    ValidationReportPayload,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.domain.models import (
    Attempt,
    Experiment,
    Project,
    ResultSnapshot,
    Validation,
)
from modeling_core.domain.states import (
    AttemptStatus,
    ProjectState,
    ResultKind,
    TerminalReason,
    ValidationOutcome,
    ValidationStatus,
)
from modeling_core.ports.clock import Clock
from modeling_core.ports.ids import IdGenerator
from modeling_core.ports.project_store import (
    BeginRunCommand,
    BeginValidationCommand,
    CompleteAttemptCommand,
    CompleteValidationCommand,
    CreateProjectCommand,
    ExperimentTraceQuery,
    ProjectStore,
    ProjectStoreError,
    WriteOperation,
)
from modeling_core.registry import CapabilityRegistry, RegistryError

_ENTITY_ID = TypeAdapter(EntityId)


class _CommonFields(TypedDict):
    tool_contract_version: Literal["modeling-tools/0.1.0"]
    correlation_id: str
    server_time: str


class _RunResultFields(_CommonFields):
    operation_id: str
    replayed: bool
    experiment_id: str
    attempt_id: str
    capability_id: str
    contract_version: str
    implementation_id: str
    implementation_version: str
    randomness: str
    seed: int | None
    warnings: tuple[Warning, ...]


class _ValidationResultFields(_CommonFields):
    operation_id: str
    replayed: bool
    validation_id: str
    attempt_id: str
    result_hash: str
    validator_id: Literal["numerical.root_finding.residual"]
    validator_implementation_id: str
    validator_implementation_version: str
    policy_version: Literal["0.1.0"]
    policy_hash: str


def _millisecond_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(
        microsecond=(value.microsecond // 1000) * 1000
    )


def _timestamp(value: datetime) -> str:
    value = _millisecond_utc(value)
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _project_summary(project: Project) -> ProjectSummary:
    return ProjectSummary(
        project_id=project.project_id,
        display_name=project.display_name,
        project_format_version=project.project_format_version,
        project_state="READY",
        created_at=_timestamp(project.created_at),
    )


def _experiment_record(experiment: Experiment) -> ExperimentRecord:
    return ExperimentRecord(
        experiment_id=experiment.experiment_id,
        project_id=experiment.project_id,
        capability_id=experiment.capability_id,
        contract_version=experiment.contract_version,
        canonical_input_schema_version=experiment.canonical_input_schema_version,
        canonical_payload=experiment.canonical_payload,
        canonical_payload_hash=experiment.canonical_payload_hash,
        canonicalization_version="canonical-json/0.1.0",
        model_snapshot_hash=experiment.model_snapshot_hash,
        data_snapshot_references=experiment.data_snapshot_references,
        data_snapshot_set_hash=experiment.data_snapshot_set_hash,
        execution_policy=experiment.execution_policy,
        created_at=_timestamp(experiment.created_at),
    )


def _attempt_trace(attempt: Attempt) -> AttemptTrace:
    result = None
    if attempt.result is not None:
        result = ResultTrace(
            result_snapshot_id=attempt.result.result_snapshot_id,
            result_kind=attempt.result.result_kind.value,
            result_schema_version=attempt.result.result_schema_version,
            result_hash=attempt.result.result_hash,
            result_payload=attempt.result.result_payload,
        )
    return AttemptTrace(
        record_type="attempt",
        attempt_id=attempt.attempt_id,
        experiment_id=attempt.experiment_id,
        implementation_id=attempt.implementation_id,
        implementation_version=attempt.implementation_version,
        environment_summary=attempt.environment_summary,
        randomness=attempt.randomness,
        seed=attempt.seed,
        session_id=attempt.session_id,
        status=attempt.status.value,
        created_at=_timestamp(attempt.created_at),
        started_at=_timestamp(attempt.started_at) if attempt.started_at else None,
        finished_at=_timestamp(attempt.finished_at) if attempt.finished_at else None,
        warnings=attempt.warnings,
        result=result,
        system_error=attempt.system_error,
        numerical_failure=attempt.numerical_failure,
        terminal_reason=attempt.terminal_reason.value if attempt.terminal_reason else None,
    )


def _validation_trace(validation: Validation) -> ValidationTrace:
    return ValidationTrace(
        record_type="validation",
        validation_id=validation.validation_id,
        attempt_id=validation.attempt_id,
        expected_result_hash=validation.expected_result_hash,
        result_hash=validation.result_hash,
        validator_id=validation.validator_id,
        validator_implementation_id=validation.validator_implementation_id,
        validator_implementation_version=validation.validator_implementation_version,
        policy_version=validation.policy_version,
        policy=validation.policy,
        policy_hash=validation.policy_hash,
        status=validation.status.value,
        created_at=_timestamp(validation.created_at),
        started_at=_timestamp(validation.started_at) if validation.started_at else None,
        finished_at=_timestamp(validation.finished_at) if validation.finished_at else None,
        outcome=validation.outcome.value if validation.outcome else None,
        metrics=validation.metrics,
        validation_report_hash=validation.validation_report_hash,
        report_payload=validation.report_payload,
        operational_error=validation.operational_error,
        terminal_reason=validation.terminal_reason.value if validation.terminal_reason else None,
    )


class ModelingApplication(ApplicationFacade):
    """Coordinates registry, deterministic execution, and durable provenance."""

    def __init__(
        self,
        *,
        store: ProjectStore,
        registry: CapabilityRegistry,
        registry_summary: RegistrySummary,
        versions: VersionSet,
        clock: Clock,
        id_generator: IdGenerator,
        session_id: EntityId,
        environment_summary: EnvironmentSummary,
        cancellation: CancellationSignal,
        default_display_name: str,
    ) -> None:
        self._store = store
        self._registry = registry
        self._registry_summary = registry_summary
        self._versions = versions
        self._clock = clock
        self._ids = id_generator
        self._session_id = _ENTITY_ID.validate_python(session_id, strict=True)
        self._environment_summary = environment_summary
        self._cancellation = cancellation
        if not 1 <= len(default_display_name) <= 128:
            raise ValueError("default_display_name must contain 1 to 128 characters")
        if unicodedata.normalize("NFC", default_display_name) != default_display_name:
            raise ValueError("default_display_name must be Unicode NFC")
        self._default_display_name = default_display_name
        self._write_gate = threading.Lock()

    def _common(self) -> _CommonFields:
        return {
            "tool_contract_version": cast(
                Literal["modeling-tools/0.1.0"],
                self._versions.tool_contract_version,
            ),
            "correlation_id": self._ids.new_uuid4(),
            "server_time": _timestamp(self._clock.utc_now()),
        }

    @staticmethod
    def _raise_store(error: ProjectStoreError, correlation_id: str) -> NoReturn:
        response = ErrorResponse.model_validate(
            {
                "error_schema_version": "modeling-error/0.1.0",
                "code": error.code,
                "message": error.message,
                "retryable": error.retryable,
                "correlation_id": correlation_id,
                "details": error.details,
            }
        )
        raise ModelingError(response) from error

    def _raise_error(
        self,
        *,
        correlation_id: str,
        code: str,
        message: str,
        details: JsonObject | ErrorDetails,
        retryable: bool = False,
    ) -> NoReturn:
        raise ModelingError(
            self._error_response(
                correlation_id=correlation_id,
                code=code,
                message=message,
                details=details,
                retryable=retryable,
            )
        )

    @staticmethod
    def _error_response(
        *,
        correlation_id: str,
        code: str,
        message: str,
        details: JsonObject | ErrorDetails,
        retryable: bool = False,
    ) -> ErrorResponse:
        return ErrorResponse.model_validate(
            {
                "error_schema_version": "modeling-error/0.1.0",
                "code": code,
                "message": message,
                "retryable": retryable,
                "correlation_id": correlation_id,
                "details": details,
            }
        )

    def _acquire_write(
        self,
        correlation_id: str,
    ) -> None:
        if not self._write_gate.acquire(blocking=False):
            self._raise_error(
                correlation_id=correlation_id,
                code="CONFLICT",
                message="another project write is in progress",
                retryable=True,
                details={
                    "conflict_type": "project_busy",
                    "retry_after_ms": 250,
                },
            )

    def _release_write(self) -> None:
        self._write_gate.release()

    def _require_ready(self, project_id: str, correlation_id: str) -> Project:
        inspection = self._store.inspect_project_state()
        integrity = self._store.inspect_integrity(deep=False)
        if (
            inspection.state is ProjectState.DEGRADED
            or integrity.state is ProjectState.DEGRADED
            or integrity.issues
        ):
            self._raise_error(
                correlation_id=correlation_id,
                code="PRECONDITION_FAILED",
                message="project is degraded",
                details={"condition": "project_degraded", "current_state": "DEGRADED"},
            )
        if inspection.state is not ProjectState.READY or inspection.project is None:
            self._raise_error(
                correlation_id=correlation_id,
                code="PRECONDITION_FAILED",
                message="project is not ready",
                details={"condition": "project_not_ready", "current_state": inspection.state.value},
            )
        if inspection.project.project_id != project_id:
            self._raise_error(
                correlation_id=correlation_id,
                code="NOT_FOUND",
                message="project was not found",
                details={"resource_type": "project", "resource_id": project_id},
            )
        return inspection.project

    def health_check(self, request: HealthCheckRequest) -> HealthCheckResult:
        del request
        common = self._common()
        inspection = self._store.inspect_project_state()
        integrity = self._store.inspect_integrity(deep=False)
        degraded = inspection.state is ProjectState.DEGRADED or bool(integrity.issues)
        checks = (
            HealthCheck(name="mcp", status="OK", code="adapter_ready"),
            HealthCheck(
                name="sqlite",
                status="WARN" if degraded else "OK",
                code="degraded" if degraded else "available",
            ),
            HealthCheck(name="registry", status="OK", code="sealed"),
            HealthCheck(
                name="project",
                status="WARN"
                if inspection.state
                in {ProjectState.UNINITIALIZED, ProjectState.STORAGE_READY}
                else ("FAIL" if degraded else "OK"),
                code=inspection.state.value.lower(),
            ),
        )
        return HealthCheckResult(
            **common,
            status="DEGRADED" if degraded else "OK",
            project_state="DEGRADED" if degraded else inspection.state.value,
            ready_for_project_creation=inspection.state
            in {ProjectState.UNINITIALIZED, ProjectState.STORAGE_READY}
            and not degraded,
            versions=HealthVersions.m1a(),
            registry=self._registry_summary,
            checks=checks,
            warnings=(),
        )

    def create_project(self, request: CreateProjectRequest) -> CreateProjectResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        self._acquire_write(correlation_id)
        try:
            inspection = self._store.inspect_project_state()
            integrity = self._store.inspect_integrity(deep=False)
            state_inspection_failed = (
                inspection.state is ProjectState.DEGRADED
                or integrity.issues == ("project_state",)
            )
            if not state_inspection_failed and (
                inspection.state is ProjectState.DEGRADED
                or integrity.state is ProjectState.DEGRADED
                or integrity.issues
            ):
                self._raise_error(
                    correlation_id=correlation_id,
                    code="PRECONDITION_FAILED",
                    message="project is degraded",
                    details={"condition": "project_degraded", "current_state": "DEGRADED"},
                )
            display_name = request.display_name
            if display_name is None:
                display_name = inspection.project.display_name if inspection.project else self._default_display_name
            command = CreateProjectCommand(
                operation=WriteOperation(
                    operation_id=request.operation_id,
                    canonical_request_hash=create_project_request_hash(display_name),
                ),
                display_name=display_name,
            )
            try:
                stored = self._store.create_or_replay_project(command)
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            return CreateProjectResult(
                **common,
                operation_id=request.operation_id,
                replayed=stored.replayed,
                project_id=stored.project.project_id,
                display_name=stored.project.display_name,
                project_format_version=stored.project.project_format_version,
                project_state="READY",
                created=stored.created,
                created_at=_timestamp(stored.project.created_at),
            )
        finally:
            self._release_write()

    def get_project_status(self, request: GetProjectStatusRequest) -> GetProjectStatusResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        self._require_ready(request.project_id, correlation_id)
        try:
            if isinstance(request, GetProjectStatusSummaryRequest):
                snapshot = self._store.get_project_status(request.project_id)
                return GetProjectStatusSummaryResult(
                    **common,
                    view="summary",
                    project=_project_summary(snapshot.project),
                    attempt_status_counts=snapshot.attempt_status_counts,
                    validation_status_counts=snapshot.validation_status_counts,
                    registry_fingerprint=self._registry_summary.fingerprint,
                    last_activity_at=_timestamp(snapshot.last_activity_at),
                    experiments=ExperimentItems(items=snapshot.experiments, truncated=snapshot.truncated),
                )
            assert isinstance(request, GetProjectStatusExperimentRequest)
            trace = self._store.get_experiment_trace(
                ExperimentTraceQuery(project_id=request.project_id, experiment_id=request.experiment_id)
            )
        except ProjectStoreError as error:
            self._raise_store(error, correlation_id)
        records: list[AttemptTrace | ValidationTrace] = [
            *(_attempt_trace(item) for item in trace.attempts),
            *(_validation_trace(item) for item in trace.validations),
        ]
        records.sort(
            key=lambda item: (
                item.created_at,
                item.record_type,
                item.attempt_id
                if isinstance(item, AttemptTrace)
                else item.validation_id,
            )
        )
        return GetProjectStatusExperimentResult(
            **common,
            view="experiment",
            project=_project_summary(trace.project),
            experiment=_experiment_record(trace.experiment),
            trace=tuple(records),
        )

    def list_capabilities(self, request: ListCapabilitiesRequest) -> ListCapabilitiesResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        state = self._store.inspect_project_state().state
        integrity = self._store.inspect_integrity(deep=False)
        if (
            state is ProjectState.DEGRADED
            or integrity.state is ProjectState.DEGRADED
            or integrity.issues
        ):
            self._raise_error(
                correlation_id=correlation_id,
                code="PRECONDITION_FAILED",
                message="project is degraded",
                details={"condition": "project_degraded", "current_state": "DEGRADED"},
            )
        if isinstance(request, ListCapabilitiesSummaryRequest):
            return ListCapabilitiesSummaryResult(
                **common,
                detail="summary",
                registry=self._registry_summary,
                capabilities=tuple(self._registry.list_summaries(request.category, request.capability_id)),
            )
        assert isinstance(request, ListCapabilitiesContractRequest)
        available = self._registry.list_summaries(None, request.capability_id)
        if not available:
            self._raise_error(
                correlation_id=correlation_id,
                code="NOT_FOUND",
                message="capability was not found",
                details={"resource_type": "capability", "resource_id": request.capability_id},
            )
        if all(item.contract_version != request.contract_version for item in available):
            self._raise_error(
                correlation_id=correlation_id,
                code="UNSUPPORTED_VERSION",
                message="capability version is not supported",
                details=UnsupportedVersionDetails(
                    subject=f"capability_contract:{request.capability_id}",
                    requested_version=request.contract_version,
                    supported_versions=tuple(
                        item.contract_version for item in available
                    ),
                ),
            )
        try:
            descriptor = self._registry.resolve(request.capability_id, request.contract_version).descriptor
        except RegistryError as error:
            self._raise_error(correlation_id=correlation_id, code=error.code, message=str(error), details=cast(JsonObject, error.details))
        capability = CapabilityContract(
            capability_id=descriptor.capability_id,
            contract_version=descriptor.contract_version,
            title=descriptor.title,
            summary=descriptor.summary,
            category=descriptor.category,
            tags=descriptor.tags,
            determinism=descriptor.determinism,
            randomness=descriptor.randomness,
            input_schema_hash=descriptor.input_schema.schema_hash,
            canonical_input_schema_version=descriptor.canonical_input_schema.schema_version,
            canonical_input_schema_hash=descriptor.canonical_input_schema.schema_hash,
            success_schema_hash=descriptor.success_schema.schema_hash,
            failure_schema_hash=descriptor.failure_schema.schema_hash,
            capability_api_version=cast(
                Literal["modeling-capability/0.1.0"],
                descriptor.capability_api_version,
            ),
            implementation_id=descriptor.implementation_id,
            implementation_version=descriptor.implementation_version,
            input_schema=descriptor.input_schema.schema,
            canonical_input_schema=descriptor.canonical_input_schema.schema,
            success_schema=descriptor.success_schema.schema,
            failure_schema=descriptor.failure_schema.schema,
            default_limits=descriptor.default_limits,
            maximum_limits=descriptor.maximum_limits,
            artifact_roles=(),
            validators=descriptor.validators,
            context_ref=descriptor.context_ref,
        )
        return ListCapabilitiesContractResult(**common, detail="contract", registry=self._registry_summary, capability=capability)

    def _run_result(
        self,
        *,
        common: _CommonFields,
        operation_id: str,
        replayed: bool,
        experiment: Experiment,
        attempt: Attempt,
    ) -> RunExperimentResult:
        base: _RunResultFields = {
            **common,
            "operation_id": operation_id,
            "replayed": replayed,
            "experiment_id": experiment.experiment_id,
            "attempt_id": attempt.attempt_id,
            "capability_id": experiment.capability_id,
            "contract_version": experiment.contract_version,
            "implementation_id": attempt.implementation_id,
            "implementation_version": attempt.implementation_version,
            "randomness": attempt.randomness,
            "seed": attempt.seed,
            "warnings": attempt.warnings,
        }
        if attempt.status is AttemptStatus.SUCCEEDED:
            if attempt.result is None or not isinstance(
                attempt.result.result_payload, SuccessResultPayload
            ):
                raise ValueError("successful attempt is missing a success payload")
            return RunExperimentSucceededResult(
                **base,
                attempt_status="SUCCEEDED",
                result_kind="success",
                result_hash=attempt.result.result_hash,
                result_summary=attempt.result.result_payload.data,
            )
        if attempt.status is AttemptStatus.NUMERICAL_FAILURE:
            if attempt.result is None or not isinstance(
                attempt.result.result_payload, FailureResultPayload
            ):
                raise ValueError(
                    "numerical-failure attempt is missing a failure payload"
                )
            return RunExperimentNumericalFailureResult(
                **base,
                attempt_status="NUMERICAL_FAILURE",
                result_kind="numerical_failure",
                result_hash=attempt.result.result_hash,
                result_summary=attempt.result.result_payload.data,
            )
        if attempt.status is AttemptStatus.ERRORED:
            if attempt.system_error is None:
                raise ValueError("errored attempt is missing its system error")
            return RunExperimentErroredResult(
                **base,
                attempt_status="ERRORED",
                system_error=attempt.system_error,
            )
        if attempt.status in {AttemptStatus.TIMED_OUT, AttemptStatus.ABANDONED}:
            if attempt.terminal_reason is None:
                raise ValueError("stopped attempt is missing its terminal reason")
            return RunExperimentStoppedResult(
                **base,
                attempt_status=cast(
                    Literal["TIMED_OUT", "ABANDONED"],
                    attempt.status.value,
                ),
                terminal_reason=attempt.terminal_reason.value,
            )
        raise ValueError("synchronous run response cannot expose an active attempt")

    def run_experiment(self, request: RunExperimentRequest) -> RunExperimentResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        self._acquire_write(correlation_id)
        try:
            self._require_ready(request.project_id, correlation_id)
            try:
                capability = self._registry.resolve(
                    request.capability.capability_id,
                    request.capability.contract_version,
                )
            except RegistryError as error:
                self._raise_error(
                    correlation_id=correlation_id,
                    code=error.code,
                    message=str(error),
                    details=cast(JsonObject, error.details),
                )
            descriptor = capability.descriptor
            execution = request.execution or ExecutionOptions()
            if descriptor.randomness == "not_used" and execution.seed is not None:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INVALID_REQUEST",
                    message="deterministic capability does not accept a seed",
                    details={
                        "field_path": "/execution/seed",
                        "reason": "invalid_combination",
                    },
                )
            if execution.timeout_ms > descriptor.maximum_limits.timeout_ms:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INVALID_REQUEST",
                    message="requested timeout exceeds the capability maximum",
                    details={
                        "field_path": "/execution/timeout_ms",
                        "reason": "out_of_range",
                    },
                )
            try:
                canonical = capability.normalize_and_validate(
                    cast(JsonObject, request.payload.model_dump(mode="json"))
                )
            except CapabilityInputRejected as error:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INVALID_REQUEST",
                    message=str(error),
                    details={
                        "field_path": error.field_path,
                        "reason": error.reason,
                    },
                )
            except CapabilitySecurityViolation as error:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="SECURITY_VIOLATION",
                    message=str(error),
                    details={"rule": error.rule},
                )
            except CapabilityInputResourceLimitExceeded as error:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="RESOURCE_LIMIT_EXCEEDED",
                    message=str(error),
                    details={
                        "resource": error.resource,
                        "limit": error.limit,
                        "observed": error.observed,
                    },
                )

            operation = WriteOperation(
                operation_id=request.operation_id,
                canonical_request_hash=run_experiment_request_hash(
                    project_id=request.project_id,
                    mode=request.mode,
                    capability_id=request.capability.capability_id,
                    contract_version=request.capability.contract_version,
                    canonical_input=canonical,
                    execution=execution,
                ),
            )
            created_at = _millisecond_utc(self._clock.utc_now())
            experiment = Experiment(
                experiment_id=self._ids.new_uuid4(),
                project_id=request.project_id,
                capability_id=descriptor.capability_id,
                contract_version=descriptor.contract_version,
                canonical_input_schema_version=cast(
                    Literal[
                        "numerical.root_finding.canonical-input/0.1.0"
                    ],
                    canonical.canonical_input_schema_version,
                ),
                canonical_payload=CanonicalRootFindingInput.model_validate(
                    canonical.canonical_payload, strict=True
                ),
                canonical_payload_hash=canonical.canonical_payload_hash,
                model_snapshot_hash=canonical.model_snapshot_hash,
                data_snapshot_references=tuple(
                    DataSnapshotReference.model_validate(item, strict=True)
                    for item in canonical.data_snapshot_references
                ),
                data_snapshot_set_hash=canonical.data_snapshot_set_hash,
                execution_policy=execution,
                created_at=created_at,
            )
            pending = Attempt(
                attempt_id=self._ids.new_uuid4(),
                experiment_id=experiment.experiment_id,
                implementation_id=descriptor.implementation_id,
                implementation_version=descriptor.implementation_version,
                environment_summary=self._environment_summary,
                randomness=descriptor.randomness,
                seed=execution.seed,
                session_id=self._session_id,
                status=AttemptStatus.PENDING,
                created_at=created_at,
            )
            try:
                begun = self._store.begin_run(
                    BeginRunCommand(
                        operation=operation,
                        experiment=experiment,
                        attempt=pending,
                    )
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            if begun.replayed:
                return self._run_result(
                    common=common,
                    operation_id=request.operation_id,
                    replayed=True,
                    experiment=begun.experiment,
                    attempt=begun.attempt,
                )

            started_at = _millisecond_utc(self._clock.utc_now())
            try:
                self._store.mark_attempt_running(
                    pending.attempt_id, started_at, self._session_id
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            deadline = self._clock.monotonic() + (
                min(
                    execution.timeout_ms,
                    descriptor.maximum_limits.timeout_ms,
                    60_000,
                )
                / 1000.0
            )
            result_snapshot: ResultSnapshot | None = None
            system_error: ErrorResponse | None = None
            terminal_reason: TerminalReason | None = None
            numerical_failure = None
            try:
                outcome = capability.execute(
                    canonical,
                    ExecutionContext(
                        attempt_id=pending.attempt_id,
                        randomness=descriptor.randomness,
                        seed=execution.seed,
                        deadline=deadline,
                        clock=self._clock,
                        cancellation=self._cancellation,
                    ),
                )
                result_document = cast(
                    JsonObject,
                    outcome.result_payload.model_dump(mode="python"),
                )
                strict_result_payload: (
                    SuccessResultPayload | FailureResultPayload
                )
                if outcome.result_kind == "success":
                    strict_result_payload = SuccessResultPayload.model_validate(
                        result_document, strict=True
                    )
                else:
                    strict_result_payload = FailureResultPayload.model_validate(
                        result_document, strict=True
                    )
                result_hash = sha256_json(
                    cast(JsonObject, strict_result_payload.model_dump(mode="json"))
                )
                result_snapshot = ResultSnapshot(
                    result_snapshot_id=self._ids.new_uuid4(),
                    attempt_id=pending.attempt_id,
                    result_kind=ResultKind(outcome.result_kind),
                    result_schema_version=cast(
                        Literal["modeling-result/0.1.0"],
                        self._versions.result_schema_version,
                    ),
                    result_hash=result_hash,
                    result_payload=strict_result_payload,
                )
                if outcome.result_kind == "success":
                    final_status = AttemptStatus.SUCCEEDED
                else:
                    final_status = AttemptStatus.NUMERICAL_FAILURE
                    if not isinstance(
                        strict_result_payload, FailureResultPayload
                    ):
                        raise ValueError(
                            "numerical failure has the wrong payload type"
                        )
                    numerical_failure = strict_result_payload.data
            except ExecutionDeadlineExceeded:
                final_status = AttemptStatus.TIMED_OUT
                terminal_reason = TerminalReason.DEADLINE_EXCEEDED
            except ExecutionCancelled:
                final_status = AttemptStatus.ABANDONED
                terminal_reason = TerminalReason.HOST_CANCELLED
            except ExecutionResourceLimitExceeded as error:
                final_status = AttemptStatus.ERRORED
                system_error = self._error_response(
                    correlation_id=correlation_id,
                    code="RESOURCE_LIMIT_EXCEEDED",
                    message=str(error),
                    details={
                        "resource": error.resource,
                        "limit": error.limit,
                        "observed": error.observed,
                    },
                )
            except Exception:
                final_status = AttemptStatus.ERRORED
                system_error = self._error_response(
                    correlation_id=correlation_id,
                    code="INTERNAL_ERROR",
                    message="capability execution failed",
                    details={"event_id": self._ids.new_uuid4()},
                )

            final_attempt = Attempt(
                attempt_id=pending.attempt_id,
                experiment_id=pending.experiment_id,
                implementation_id=pending.implementation_id,
                implementation_version=pending.implementation_version,
                environment_summary=pending.environment_summary,
                randomness=pending.randomness,
                seed=pending.seed,
                session_id=pending.session_id,
                status=final_status,
                created_at=pending.created_at,
                started_at=started_at,
                finished_at=_millisecond_utc(self._clock.utc_now()),
                warnings=(),
                result=result_snapshot,
                system_error=system_error,
                numerical_failure=numerical_failure,
                terminal_reason=terminal_reason,
            )
            try:
                stored = self._store.complete_attempt(
                    CompleteAttemptCommand(
                        operation=operation,
                        attempt=final_attempt,
                    )
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            return self._run_result(
                common=common,
                operation_id=request.operation_id,
                replayed=False,
                experiment=experiment,
                attempt=stored.attempt,
            )
        finally:
            self._release_write()

    def _validation_result(
        self,
        *,
        common: _CommonFields,
        operation_id: str,
        replayed: bool,
        validation: Validation,
    ) -> ValidateExperimentResult:
        base: _ValidationResultFields = {
            **common,
            "operation_id": operation_id,
            "replayed": replayed,
            "validation_id": validation.validation_id,
            "attempt_id": validation.attempt_id,
            "result_hash": validation.result_hash,
            "validator_id": validation.validator_id,
            "validator_implementation_id": (
                validation.validator_implementation_id
            ),
            "validator_implementation_version": (
                validation.validator_implementation_version
            ),
            "policy_version": validation.policy_version,
            "policy_hash": validation.policy_hash,
        }
        if validation.status is ValidationStatus.SUCCEEDED:
            if (
                validation.outcome is None
                or validation.metrics is None
                or validation.validation_report_hash is None
            ):
                raise ValueError("successful validation is missing its report")
            return ValidateExperimentSucceededResult(
                **base,
                validation_status="SUCCEEDED",
                outcome=validation.outcome.value,
                metrics=validation.metrics,
                validation_report_hash=validation.validation_report_hash,
            )
        if validation.status is ValidationStatus.ERRORED:
            if validation.operational_error is None:
                raise ValueError("errored validation is missing its error")
            return ValidateExperimentErroredResult(
                **base,
                validation_status="ERRORED",
                operational_error=validation.operational_error,
            )
        if validation.status in {
            ValidationStatus.TIMED_OUT,
            ValidationStatus.ABANDONED,
        }:
            if validation.terminal_reason is None:
                raise ValueError("stopped validation is missing its reason")
            return ValidateExperimentStoppedResult(
                **base,
                validation_status=cast(
                    Literal["TIMED_OUT", "ABANDONED"],
                    validation.status.value,
                ),
                terminal_reason=validation.terminal_reason.value,
            )
        raise ValueError(
            "synchronous validation response cannot expose an active validation"
        )

    def validate_experiment(
        self, request: ValidateExperimentRequest
    ) -> ValidateExperimentResult:
        common = self._common()
        correlation_id = common["correlation_id"]
        self._acquire_write(correlation_id)
        try:
            self._require_ready(request.project_id, correlation_id)
            try:
                source = self._store.get_validation_source(
                    request.project_id, request.attempt_id
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)

            payload_document = cast(
                JsonObject,
                source.experiment.canonical_payload.model_dump(mode="json"),
            )
            observed_input_hash = sha256_json(payload_document)
            observed_model_hash = sha256_json(
                {
                    "language": "math-expr-v1",
                    "ast": payload_document["expression_ast"],
                }
            )
            data_documents = [
                cast(JsonObject, item.model_dump(mode="json"))
                for item in source.experiment.data_snapshot_references
            ]
            observed_data_hash = sha256_json(data_documents)
            if (
                observed_input_hash
                != source.experiment.canonical_payload_hash
                or observed_model_hash != source.experiment.model_snapshot_hash
                or observed_data_hash
                != source.experiment.data_snapshot_set_hash
            ):
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INTEGRITY_FAILURE",
                    message="committed input snapshot failed integrity checks",
                    details={
                        "subject": "input_snapshot",
                        "expected_hash": source.experiment.canonical_payload_hash,
                        "observed_hash": observed_input_hash,
                    },
                )
            if source.attempt.result is None:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="PRECONDITION_FAILED",
                    message="attempt has no success result",
                    details={
                        "condition": "missing_success_result",
                        "current_state": source.attempt.status.value,
                    },
                )
            result_document = cast(
                JsonObject,
                source.attempt.result.result_payload.model_dump(mode="json"),
            )
            observed_result_hash = sha256_json(result_document)
            if (
                observed_result_hash != source.attempt.result.result_hash
                or request.expected_result_hash
                != source.attempt.result.result_hash
            ):
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INTEGRITY_FAILURE",
                    message="result hash does not match committed evidence",
                    details={
                        "subject": "result_hash",
                        "expected_hash": request.expected_result_hash,
                        "observed_hash": observed_result_hash,
                    },
                )

            try:
                validator = self._registry.resolve_validator(
                    request.validator_id,
                    source.experiment.capability_id,
                    source.experiment.contract_version,
                    request.policy_version,
                )
                capability = self._registry.resolve(
                    source.experiment.capability_id,
                    source.experiment.contract_version,
                )
            except RegistryError as error:
                self._raise_error(
                    correlation_id=correlation_id,
                    code=error.code,
                    message=str(error),
                    details=cast(JsonObject, error.details),
                )
            if request.policy:
                self._raise_error(
                    correlation_id=correlation_id,
                    code="INVALID_REQUEST",
                    message="M1a residual validation policy must be empty",
                    details={
                        "field_path": "/policy",
                        "reason": "unknown_field",
                    },
                )

            canonical = CanonicalInputRecord(
                canonical_input_schema_version=(
                    source.experiment.canonical_input_schema_version
                ),
                canonical_payload=payload_document,
                canonical_payload_hash=source.experiment.canonical_payload_hash,
                model_snapshot_hash=source.experiment.model_snapshot_hash,
                data_snapshot_references=tuple(data_documents),
                data_snapshot_set_hash=source.experiment.data_snapshot_set_hash,
            )
            policy_hash = sha256_json(request.policy)
            operation = WriteOperation(
                operation_id=request.operation_id,
                canonical_request_hash=validate_experiment_request_hash(
                    project_id=request.project_id,
                    attempt_id=request.attempt_id,
                    expected_result_hash=request.expected_result_hash,
                    validator_id=request.validator_id,
                    policy_version=request.policy_version,
                    policy=request.policy,
                    timeout_ms=request.timeout_ms,
                ),
            )
            pending = Validation(
                validation_id=self._ids.new_uuid4(),
                attempt_id=request.attempt_id,
                expected_result_hash=request.expected_result_hash,
                result_hash=source.attempt.result.result_hash,
                validator_id=cast(
                    Literal["numerical.root_finding.residual"],
                    validator.descriptor.validator_id,
                ),
                validator_implementation_id=(
                    validator.descriptor.implementation_id
                ),
                validator_implementation_version=(
                    validator.descriptor.implementation_version
                ),
                policy_version=request.policy_version,
                policy=request.policy,
                policy_hash=policy_hash,
                status=ValidationStatus.PENDING,
                created_at=_millisecond_utc(self._clock.utc_now()),
            )
            try:
                begun = self._store.begin_validation(
                    BeginValidationCommand(
                        operation=operation,
                        validation=pending,
                    )
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            if begun.replayed:
                return self._validation_result(
                    common=common,
                    operation_id=request.operation_id,
                    replayed=True,
                    validation=begun.validation,
                )

            started_at = _millisecond_utc(self._clock.utc_now())
            try:
                self._store.mark_validation_running(
                    pending.validation_id, started_at
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            deadline = self._clock.monotonic() + (
                min(
                    request.timeout_ms,
                    capability.descriptor.maximum_limits.timeout_ms,
                    60_000,
                )
                / 1000.0
            )
            outcome: ValidationOutcome | None = None
            metrics = None
            report_hash: str | None = None
            report_payload = None
            operational_error: ErrorResponse | None = None
            terminal_reason: TerminalReason | None = None
            try:
                raw_report_payload = validator.validate(
                    canonical,
                    ResultSnapshotView(
                        result_snapshot_id=(
                            source.attempt.result.result_snapshot_id
                        ),
                        capability_id=source.experiment.capability_id,
                        contract_version=source.experiment.contract_version,
                        result_schema_version=(
                            source.attempt.result.result_schema_version
                        ),
                        result_hash=source.attempt.result.result_hash,
                        result_payload=source.attempt.result.result_payload,
                    ),
                    request.policy,
                    ValidationContext(
                        deadline=deadline,
                        clock=self._clock,
                        cancellation=self._cancellation,
                    ),
                )
                report_payload = ValidationReportPayload.model_validate(
                    raw_report_payload.model_dump(
                        mode="python", warnings="none"
                    ),
                    strict=True,
                )
                outcome = ValidationOutcome(report_payload.outcome)
                metrics = report_payload.metrics
                report_hash = sha256_json(
                    cast(
                        JsonObject,
                        report_payload.model_dump(mode="json"),
                    )
                )
                final_status = ValidationStatus.SUCCEEDED
            except ExecutionDeadlineExceeded:
                final_status = ValidationStatus.TIMED_OUT
                terminal_reason = TerminalReason.DEADLINE_EXCEEDED
            except ExecutionCancelled:
                final_status = ValidationStatus.ABANDONED
                terminal_reason = TerminalReason.HOST_CANCELLED
            except ExecutionResourceLimitExceeded as error:
                final_status = ValidationStatus.ERRORED
                operational_error = self._error_response(
                    correlation_id=correlation_id,
                    code="RESOURCE_LIMIT_EXCEEDED",
                    message=str(error),
                    details={
                        "resource": error.resource,
                        "limit": error.limit,
                        "observed": error.observed,
                    },
                )
            except Exception:
                final_status = ValidationStatus.ERRORED
                operational_error = self._error_response(
                    correlation_id=correlation_id,
                    code="INTERNAL_ERROR",
                    message="validator execution failed",
                    details={"event_id": self._ids.new_uuid4()},
                )

            final_validation = Validation(
                validation_id=pending.validation_id,
                attempt_id=pending.attempt_id,
                expected_result_hash=pending.expected_result_hash,
                result_hash=pending.result_hash,
                validator_id=pending.validator_id,
                validator_implementation_id=(
                    pending.validator_implementation_id
                ),
                validator_implementation_version=(
                    pending.validator_implementation_version
                ),
                policy_version=pending.policy_version,
                policy=pending.policy,
                policy_hash=pending.policy_hash,
                status=final_status,
                created_at=pending.created_at,
                started_at=started_at,
                finished_at=_millisecond_utc(self._clock.utc_now()),
                outcome=outcome,
                metrics=metrics,
                validation_report_hash=report_hash,
                report_payload=report_payload,
                operational_error=operational_error,
                terminal_reason=terminal_reason,
            )
            try:
                stored = self._store.complete_validation(
                    CompleteValidationCommand(
                        operation=operation,
                        validation=final_validation,
                    )
                )
            except ProjectStoreError as error:
                self._raise_store(error, correlation_id)
            return self._validation_result(
                common=common,
                operation_id=request.operation_id,
                replayed=False,
                validation=stored.validation,
            )
        finally:
            self._release_write()


__all__ = ["ModelingApplication"]
