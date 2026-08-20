"""Use-case-shaped, typed persistence boundary for one project."""

from __future__ import annotations

import unicodedata
from pathlib import Path
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol, cast

from pydantic import Field, TypeAdapter

from modeling_core.contracts.canonical_json import (
    canonical_json_bytes,
    strict_json_loads,
)
from modeling_core.contracts.common import EntityId, Hash, JsonObject
from modeling_core.contracts.errors import ErrorCode
from modeling_core.contracts.tools import (
    AttemptStatusCounts,
    ExperimentSummary,
    ValidationStatusCounts,
)
from modeling_core.domain.models import (
    Attempt,
    Artifact,
    EnvironmentSnapshot,
    Experiment,
    InputSnapshot,
    Project,
    ResultSnapshot,
    Validation,
)
from modeling_core.domain.states import (
    AttemptStatus,
    ProjectState,
    ResultKind,
    ValidationStatus,
)

_DISPLAY_NAME = Annotated[str, Field(min_length=1, max_length=128)]
_ENTITY_ID = TypeAdapter(EntityId)
_HASH = TypeAdapter(Hash)
_ERROR_CODE: TypeAdapter[ErrorCode] = TypeAdapter(ErrorCode)
_MESSAGE: TypeAdapter[str] = TypeAdapter(
    Annotated[str, Field(min_length=1, max_length=1024)]
)
_BOOL: TypeAdapter[bool] = TypeAdapter(bool)
_TERMINAL_ATTEMPTS = frozenset(
    {
        AttemptStatus.SUCCEEDED,
        AttemptStatus.NUMERICAL_FAILURE,
        AttemptStatus.ERRORED,
        AttemptStatus.TIMED_OUT,
        AttemptStatus.ABANDONED,
    }
)
_TERMINAL_VALIDATIONS = frozenset(
    {
        ValidationStatus.SUCCEEDED,
        ValidationStatus.ERRORED,
        ValidationStatus.TIMED_OUT,
        ValidationStatus.ABANDONED,
    }
)
_RETRYABLE_CONFLICTS = frozenset({"operation_in_progress", "project_busy"})

IntegrityCheckMode = Literal["quick", "integrity"]
IntegrityCheckOutcome = Literal["PASS", "FAIL", "ERROR"]
StoreIntegrityIssue = Literal[
    "sqlite_quick_check",
    "sqlite_integrity_check",
    "foreign_key",
    "stale_attempt",
    "stale_validation",
    "stale_operation",
    "database_relation",
    "project_state",
]
LegacyOperationTool = Literal["run_experiment", "validate_experiment"]

_INTEGRITY_CHECK_MODE: TypeAdapter[IntegrityCheckMode] = TypeAdapter(IntegrityCheckMode)
_INTEGRITY_CHECK_OUTCOME: TypeAdapter[IntegrityCheckOutcome] = TypeAdapter(
    IntegrityCheckOutcome
)
_STORE_INTEGRITY_ISSUES = TypeAdapter(tuple[StoreIntegrityIssue, ...])
_LEGACY_ATTEMPT_STATUS: TypeAdapter[Literal["PENDING", "RUNNING"]] = TypeAdapter(
    Literal["PENDING", "RUNNING"]
)
_LEGACY_VALIDATION_STATUS: TypeAdapter[Literal["PENDING", "RUNNING"]] = TypeAdapter(
    Literal["PENDING", "RUNNING"]
)
_LEGACY_OPERATION_TOOL: TypeAdapter[LegacyOperationTool] = TypeAdapter(
    LegacyOperationTool
)
_LEGACY_OPERATION_STATUS: TypeAdapter[Literal["IN_PROGRESS"]] = TypeAdapter(
    Literal["IN_PROGRESS"]
)


def _validate(value: object, annotation: Any) -> Any:
    return cast(Any, TypeAdapter(annotation).validate_python(value, strict=True))


def _validate_timestamp(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("timestamp must be a datetime")
    if value.tzinfo is None or value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must be UTC")
    if value.microsecond % 1000 != 0:
        raise ValueError("timestamp must have millisecond precision")
    return value


def _validate_attempt_result_owner(attempt: Attempt) -> None:
    if attempt.result is not None and attempt.result.attempt_id != attempt.attempt_id:
        raise ValueError("embedded result snapshot must belong to its owning attempt")


def _require_terminal_attempt(attempt: Attempt) -> None:
    _validate_attempt_result_owner(attempt)
    if attempt.status not in _TERMINAL_ATTEMPTS:
        raise ValueError("attempt must be terminal")


def _require_terminal_validation(validation: Validation) -> None:
    if validation.status not in _TERMINAL_VALIDATIONS:
        raise ValueError("validation must be terminal")


@dataclass(frozen=True)
class ProjectStateInspection:
    state: ProjectState
    project: Project | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", _validate(self.state, ProjectState))
        if self.project is not None:
            object.__setattr__(self, "project", _validate(self.project, Project))


@dataclass(frozen=True)
class WriteOperation:
    operation_id: EntityId
    canonical_request_hash: Hash

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "operation_id",
            _ENTITY_ID.validate_python(self.operation_id, strict=True),
        )
        object.__setattr__(
            self,
            "canonical_request_hash",
            _HASH.validate_python(self.canonical_request_hash, strict=True),
        )


@dataclass(frozen=True)
class CreateProjectCommand:
    operation: WriteOperation
    display_name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _validate(self.operation, WriteOperation))
        display_name = _validate(self.display_name, _DISPLAY_NAME)
        if unicodedata.normalize("NFC", display_name) != display_name:
            raise ValueError("display_name must be Unicode NFC")
        object.__setattr__(self, "display_name", display_name)


@dataclass(frozen=True)
class ProjectWriteResult:
    project: Project
    created: bool
    replayed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "project", _validate(self.project, Project))
        object.__setattr__(
            self, "created", _BOOL.validate_python(self.created, strict=True)
        )
        object.__setattr__(
            self,
            "replayed",
            _BOOL.validate_python(self.replayed, strict=True),
        )


@dataclass(frozen=True)
class ProjectStatusSnapshot:
    project: Project
    attempt_status_counts: AttemptStatusCounts
    validation_status_counts: ValidationStatusCounts
    last_activity_at: datetime
    experiments: tuple[ExperimentSummary, ...]
    truncated: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "project", _validate(self.project, Project))
        object.__setattr__(
            self,
            "attempt_status_counts",
            _validate(self.attempt_status_counts, AttemptStatusCounts),
        )
        object.__setattr__(
            self,
            "validation_status_counts",
            _validate(self.validation_status_counts, ValidationStatusCounts),
        )
        object.__setattr__(
            self,
            "last_activity_at",
            _validate_timestamp(self.last_activity_at),
        )
        experiments = _validate(self.experiments, tuple[ExperimentSummary, ...])
        if len(experiments) > 20:
            raise ValueError("project status accepts at most 20 experiments")
        ordered = tuple(
            sorted(
                experiments,
                key=lambda item: (item.created_at, item.experiment_id),
                reverse=True,
            )
        )
        if experiments != ordered:
            raise ValueError(
                "experiments must be ordered descending by creation and ID"
            )
        object.__setattr__(self, "experiments", experiments)
        object.__setattr__(
            self,
            "truncated",
            _BOOL.validate_python(self.truncated, strict=True),
        )


@dataclass(frozen=True)
class ExperimentTraceQuery:
    project_id: EntityId
    experiment_id: EntityId

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "project_id",
            _ENTITY_ID.validate_python(self.project_id, strict=True),
        )
        object.__setattr__(
            self,
            "experiment_id",
            _ENTITY_ID.validate_python(self.experiment_id, strict=True),
        )


@dataclass(frozen=True)
class ExperimentTrace:
    project: Project
    experiment: Experiment
    attempts: tuple[Attempt, ...]
    validations: tuple[Validation, ...]

    def __post_init__(self) -> None:
        project = _validate(self.project, Project)
        experiment = _validate(self.experiment, Experiment)
        attempts = _validate(self.attempts, tuple[Attempt, ...])
        validations = _validate(self.validations, tuple[Validation, ...])
        if experiment.project_id != project.project_id:
            raise ValueError("experiment must belong to project")
        if any(item.experiment_id != experiment.experiment_id for item in attempts):
            raise ValueError("every attempt must belong to experiment")
        for item in attempts:
            _validate_attempt_result_owner(item)
        attempt_ids = tuple(item.attempt_id for item in attempts)
        if len(set(attempt_ids)) != len(attempt_ids):
            raise ValueError("attempt IDs must be unique")
        if any(item.attempt_id not in set(attempt_ids) for item in validations):
            raise ValueError("every validation must belong to a trace attempt")
        validation_ids = tuple(item.validation_id for item in validations)
        if len(set(validation_ids)) != len(validation_ids):
            raise ValueError("validation IDs must be unique")
        object.__setattr__(self, "project", project)
        object.__setattr__(self, "experiment", experiment)
        object.__setattr__(self, "attempts", attempts)
        object.__setattr__(self, "validations", validations)


@dataclass(frozen=True)
class BeginRunCommand:
    operation: WriteOperation
    experiment: Experiment
    attempt: Attempt
    input_snapshot: InputSnapshot | None = None
    environment_snapshot: EnvironmentSnapshot | None = None
    mode: Literal["new", "rerun"] = "new"

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _validate(self.operation, WriteOperation))
        experiment = _validate(self.experiment, Experiment)
        attempt = _validate(self.attempt, Attempt)
        _validate_attempt_result_owner(attempt)
        if attempt.status is not AttemptStatus.PENDING:
            raise ValueError("begin-run attempt must be PENDING")
        if attempt.experiment_id != experiment.experiment_id:
            raise ValueError("attempt must belong to experiment")
        input_snapshot = self.input_snapshot
        if input_snapshot is not None:
            input_snapshot = _validate(input_snapshot, InputSnapshot)
            if input_snapshot.canonical_payload_hash != (
                experiment.canonical_payload_hash
            ):
                raise ValueError(
                    "input snapshot must match the experiment canonical payload hash"
                )
            if input_snapshot.model_snapshot_hash != experiment.model_snapshot_hash:
                raise ValueError(
                    "input snapshot must match the experiment model snapshot hash"
                )
            if input_snapshot.data_snapshot_set_hash != (
                experiment.data_snapshot_set_hash
            ):
                raise ValueError(
                    "input snapshot must match the experiment data snapshot set hash"
                )
        environment_snapshot = self.environment_snapshot
        if environment_snapshot is not None:
            environment_snapshot = _validate(environment_snapshot, EnvironmentSnapshot)
        object.__setattr__(self, "experiment", experiment)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "input_snapshot", input_snapshot)
        object.__setattr__(self, "environment_snapshot", environment_snapshot)
        object.__setattr__(self, "mode", _validate(self.mode, Literal["new", "rerun"]))
        if self.mode == "rerun" and input_snapshot is not None:
            raise ValueError("rerun begin-run reuses the stored input snapshot")


@dataclass(frozen=True)
class BeginRunResult:
    experiment: Experiment
    attempt: Attempt
    replayed: bool
    artifact: Artifact | None = None

    def __post_init__(self) -> None:
        experiment = _validate(self.experiment, Experiment)
        attempt = _validate(self.attempt, Attempt)
        replayed = _BOOL.validate_python(self.replayed, strict=True)
        artifact = self.artifact
        if artifact is not None:
            artifact = _validate(artifact, Artifact)
            if (
                attempt.result is None
                or artifact.artifact_id != attempt.result.result_hash
            ):
                raise ValueError("run artifact must identify the attempt result")
        _validate_attempt_result_owner(attempt)
        if attempt.experiment_id != experiment.experiment_id:
            raise ValueError("attempt must belong to experiment")
        if replayed and attempt.status not in _TERMINAL_ATTEMPTS:
            raise ValueError("replayed begin-run result must be terminal")
        if not replayed and attempt.status is not AttemptStatus.PENDING:
            raise ValueError("new begin-run result must be PENDING")
        object.__setattr__(self, "experiment", experiment)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "replayed", replayed)
        object.__setattr__(self, "artifact", artifact)


@dataclass(frozen=True)
class CompleteAttemptCommand:
    operation: WriteOperation
    attempt: Attempt
    result_artifact: Artifact | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _validate(self.operation, WriteOperation))
        attempt = _validate(self.attempt, Attempt)
        _require_terminal_attempt(attempt)
        result_artifact = self.result_artifact
        if result_artifact is not None:
            result_artifact = _validate(result_artifact, Artifact)
            if result_artifact.role != "result":
                raise ValueError("result artifact must declare the result role")
            if attempt.result is None:
                raise ValueError(
                    "a result artifact requires an embedded result snapshot"
                )
            if result_artifact.artifact_id != attempt.result.result_hash:
                raise ValueError("result artifact identity must equal the result hash")
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "result_artifact", result_artifact)


@dataclass(frozen=True)
class StoredRunResult:
    attempt: Attempt
    artifact: Artifact | None = None

    def __post_init__(self) -> None:
        attempt = _validate(self.attempt, Attempt)
        _require_terminal_attempt(attempt)
        artifact = self.artifact
        if artifact is not None:
            artifact = _validate(artifact, Artifact)
            if (
                attempt.result is None
                or artifact.artifact_id != attempt.result.result_hash
            ):
                raise ValueError("run artifact must identify the attempt result")
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "artifact", artifact)


@dataclass(frozen=True)
class ValidationSource:
    experiment: Experiment
    attempt: Attempt

    def __post_init__(self) -> None:
        experiment = _validate(self.experiment, Experiment)
        attempt = _validate(self.attempt, Attempt)
        _validate_attempt_result_owner(attempt)
        if attempt.experiment_id != experiment.experiment_id:
            raise ValueError("attempt must belong to experiment")
        if (
            attempt.status is not AttemptStatus.SUCCEEDED
            or attempt.result is None
            or attempt.result.result_kind is not ResultKind.SUCCESS
        ):
            raise ValueError("validation source requires a successful attempt result")
        object.__setattr__(self, "experiment", experiment)
        object.__setattr__(self, "attempt", attempt)


@dataclass(frozen=True)
class BeginValidationCommand:
    operation: WriteOperation
    validation: Validation

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _validate(self.operation, WriteOperation))
        validation = _validate(self.validation, Validation)
        if validation.status is not ValidationStatus.PENDING:
            raise ValueError("begin-validation record must be PENDING")
        object.__setattr__(self, "validation", validation)


@dataclass(frozen=True)
class BeginValidationResult:
    validation: Validation
    replayed: bool
    report_artifact: Artifact | None = None

    def __post_init__(self) -> None:
        validation = _validate(self.validation, Validation)
        replayed = _BOOL.validate_python(self.replayed, strict=True)
        report_artifact = self.report_artifact
        if report_artifact is not None:
            report_artifact = _validate(report_artifact, Artifact)
            if report_artifact.artifact_id != validation.validation_report_hash:
                raise ValueError("report artifact must identify the validation report")
        if replayed and validation.status not in _TERMINAL_VALIDATIONS:
            raise ValueError("replayed begin-validation result must be terminal")
        if not replayed and validation.status is not ValidationStatus.PENDING:
            raise ValueError("new begin-validation result must be PENDING")
        object.__setattr__(self, "validation", validation)
        object.__setattr__(self, "replayed", replayed)
        object.__setattr__(self, "report_artifact", report_artifact)


@dataclass(frozen=True)
class CompleteValidationCommand:
    operation: WriteOperation
    validation: Validation
    report_artifact: Artifact | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _validate(self.operation, WriteOperation))
        validation = _validate(self.validation, Validation)
        _require_terminal_validation(validation)
        report_artifact = self.report_artifact
        if report_artifact is not None:
            report_artifact = _validate(report_artifact, Artifact)
            if report_artifact.role != "validation_report":
                raise ValueError("report artifact must declare the report role")
            if validation.report_payload is None:
                raise ValueError(
                    "a report artifact requires an embedded report payload"
                )
            if validation.validation_report_hash is None:
                raise ValueError("a report artifact requires a report hash")
            if report_artifact.artifact_id != validation.validation_report_hash:
                raise ValueError("report artifact identity must equal the report hash")
        object.__setattr__(self, "validation", validation)
        object.__setattr__(self, "report_artifact", report_artifact)


@dataclass(frozen=True)
class StoredValidationResult:
    validation: Validation
    report_artifact: Artifact | None = None

    def __post_init__(self) -> None:
        validation = _validate(self.validation, Validation)
        _require_terminal_validation(validation)
        report_artifact = self.report_artifact
        if report_artifact is not None:
            report_artifact = _validate(report_artifact, Artifact)
            if report_artifact.artifact_id != validation.validation_report_hash:
                raise ValueError("report artifact must identify the validation report")
        object.__setattr__(self, "validation", validation)
        object.__setattr__(self, "report_artifact", report_artifact)


@dataclass(frozen=True)
class VerifiedResult:
    """A committed result reread through verified storage."""

    result_snapshot: ResultSnapshot
    artifact: Artifact | None
    payload_bytes: bytes

    def __post_init__(self) -> None:
        result_snapshot = _validate(self.result_snapshot, ResultSnapshot)
        artifact = self.artifact
        if artifact is not None:
            artifact = _validate(artifact, Artifact)
            if artifact.role != "result":
                raise ValueError("verified result artifact must declare the role")
            if artifact.artifact_id != result_snapshot.result_hash:
                raise ValueError(
                    "verified artifact identity must equal the result hash"
                )
        if not isinstance(self.payload_bytes, (bytes, bytearray)):
            raise ValueError("payload_bytes must be bytes")
        object.__setattr__(self, "result_snapshot", result_snapshot)
        object.__setattr__(self, "artifact", artifact)
        object.__setattr__(self, "payload_bytes", bytes(self.payload_bytes))


@dataclass(frozen=True)
class RecoveryReport:
    """Finite startup-recovery outcome safe to expose to composition."""

    recovered_attempt_ids: tuple[EntityId, ...]
    recovered_validation_ids: tuple[EntityId, ...]
    integrity_failure_ids: tuple[EntityId, ...]

    def __post_init__(self) -> None:
        for field_name in (
            "recovered_attempt_ids",
            "recovered_validation_ids",
            "integrity_failure_ids",
        ):
            values = _validate(getattr(self, field_name), tuple[EntityId, ...])
            if len(values) > 100:
                raise ValueError("recovery report relation accepts at most 100 IDs")
            if len(set(values)) != len(values):
                raise ValueError("recovery report IDs must be unique")
            if values != tuple(sorted(values, key=lambda item: item.encode("utf-8"))):
                raise ValueError("recovery report IDs must use UTF-8 byte order")
            object.__setattr__(self, field_name, values)


@dataclass(frozen=True)
class StoreIntegrityCheck:
    mode: IntegrityCheckMode
    outcome: IntegrityCheckOutcome

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "mode",
            _INTEGRITY_CHECK_MODE.validate_python(self.mode, strict=True),
        )
        object.__setattr__(
            self,
            "outcome",
            _INTEGRITY_CHECK_OUTCOME.validate_python(self.outcome, strict=True),
        )


@dataclass(frozen=True)
class LegacyAttempt:
    attempt_id: EntityId
    status: Literal["PENDING", "RUNNING"]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "attempt_id",
            _ENTITY_ID.validate_python(self.attempt_id, strict=True),
        )
        object.__setattr__(
            self,
            "status",
            _LEGACY_ATTEMPT_STATUS.validate_python(self.status, strict=True),
        )


@dataclass(frozen=True)
class LegacyValidation:
    validation_id: EntityId
    status: Literal["PENDING", "RUNNING"]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "validation_id",
            _ENTITY_ID.validate_python(self.validation_id, strict=True),
        )
        object.__setattr__(
            self,
            "status",
            _LEGACY_VALIDATION_STATUS.validate_python(self.status, strict=True),
        )


@dataclass(frozen=True)
class LegacyIdempotencyRecord:
    scope_id: EntityId
    tool_name: LegacyOperationTool
    operation_id: EntityId
    status: Literal["IN_PROGRESS"]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "scope_id",
            _ENTITY_ID.validate_python(self.scope_id, strict=True),
        )
        object.__setattr__(
            self,
            "tool_name",
            _LEGACY_OPERATION_TOOL.validate_python(self.tool_name, strict=True),
        )
        object.__setattr__(
            self,
            "operation_id",
            _ENTITY_ID.validate_python(self.operation_id, strict=True),
        )
        object.__setattr__(
            self,
            "status",
            _LEGACY_OPERATION_STATUS.validate_python(self.status, strict=True),
        )


def _require_legacy_row_count(count: int) -> None:
    if count > 100:
        raise ValueError("legacy relation accepts at most 100 rows")


def _require_sorted_unique_attempts(rows: tuple[LegacyAttempt, ...]) -> None:
    _require_legacy_row_count(len(rows))
    identities = tuple(item.attempt_id for item in rows)
    ordering = tuple(
        (item.status.encode("utf-8"), item.attempt_id.encode("utf-8")) for item in rows
    )
    if len(set(identities)) != len(identities):
        raise ValueError("legacy relation identities must be unique")
    if ordering != tuple(sorted(ordering)):
        raise ValueError("legacy relation rows must use UTF-8 byte order")


def _require_sorted_unique_validations(rows: tuple[LegacyValidation, ...]) -> None:
    _require_legacy_row_count(len(rows))
    identities = tuple(item.validation_id for item in rows)
    ordering = tuple(
        (item.status.encode("utf-8"), item.validation_id.encode("utf-8"))
        for item in rows
    )
    if len(set(identities)) != len(identities):
        raise ValueError("legacy relation identities must be unique")
    if ordering != tuple(sorted(ordering)):
        raise ValueError("legacy relation rows must use UTF-8 byte order")


def _require_sorted_unique_operations(
    rows: tuple[LegacyIdempotencyRecord, ...],
) -> None:
    _require_legacy_row_count(len(rows))
    identities = tuple(
        (item.scope_id, item.tool_name, item.operation_id) for item in rows
    )
    ordering = tuple(
        (
            item.scope_id.encode("utf-8"),
            item.tool_name.encode("utf-8"),
            item.operation_id.encode("utf-8"),
        )
        for item in rows
    )
    if len(set(identities)) != len(identities):
        raise ValueError("legacy relation identities must be unique")
    if ordering != tuple(sorted(ordering)):
        raise ValueError("legacy relation rows must use UTF-8 byte order")


@dataclass(frozen=True)
class StoreIntegrityReport:
    state: ProjectState
    issues: tuple[StoreIntegrityIssue, ...]
    check: StoreIntegrityCheck | None = None
    legacy_attempts: tuple[LegacyAttempt, ...] = ()
    legacy_validations: tuple[LegacyValidation, ...] = ()
    legacy_idempotency_records: tuple[LegacyIdempotencyRecord, ...] = ()

    def __post_init__(self) -> None:
        state = _validate(self.state, ProjectState)
        issues = _STORE_INTEGRITY_ISSUES.validate_python(self.issues, strict=True)
        if len(set(issues)) != len(issues):
            raise ValueError("integrity issues must be unique")
        if issues != tuple(sorted(issues, key=lambda item: item.encode("utf-8"))):
            raise ValueError("integrity issues must use UTF-8 byte order")
        if self.check is not None and type(self.check) is not StoreIntegrityCheck:
            raise TypeError("check must be StoreIntegrityCheck or None")
        attempts = _validate(self.legacy_attempts, tuple[LegacyAttempt, ...])
        validations = _validate(self.legacy_validations, tuple[LegacyValidation, ...])
        operations = _validate(
            self.legacy_idempotency_records,
            tuple[LegacyIdempotencyRecord, ...],
        )
        _require_sorted_unique_attempts(attempts)
        _require_sorted_unique_validations(validations)
        _require_sorted_unique_operations(operations)
        object.__setattr__(self, "state", state)
        object.__setattr__(self, "issues", issues)
        object.__setattr__(self, "legacy_attempts", attempts)
        object.__setattr__(self, "legacy_validations", validations)
        object.__setattr__(self, "legacy_idempotency_records", operations)


class ProjectStoreError(Exception):
    """Validated deep-immutable persistence error for the application."""

    def __init__(
        self,
        code: ErrorCode,
        message: str,
        retryable: bool,
        details: JsonObject,
    ) -> None:
        validated_code = _ERROR_CODE.validate_python(code, strict=True)
        validated_message = _MESSAGE.validate_python(message, strict=True)
        validated_retryable = _BOOL.validate_python(retryable, strict=True)
        if type(details) is not dict:
            raise ValueError("details must be a JSON object")
        details_bytes = canonical_json_bytes(details)
        decoded = cast(JsonObject, strict_json_loads(details_bytes))
        if validated_retryable and (
            validated_code != "CONFLICT"
            or decoded.get("conflict_type") not in _RETRYABLE_CONFLICTS
        ):
            raise ValueError("only transient persistence conflicts can be retryable")
        super().__init__(validated_message)
        self._code = validated_code
        self._message = validated_message
        self._retryable = validated_retryable
        self._details_bytes = details_bytes

    @property
    def code(self) -> ErrorCode:
        return self._code

    @property
    def message(self) -> str:
        return self._message

    @property
    def retryable(self) -> bool:
        return self._retryable

    @property
    def details(self) -> JsonObject:
        return cast(JsonObject, strict_json_loads(self._details_bytes))


class ProjectStore(Protocol):
    @property
    def project_root(self) -> Path: ...

    def inspect_project_state(self) -> ProjectStateInspection: ...

    def create_or_replay_project(
        self, command: CreateProjectCommand
    ) -> ProjectWriteResult: ...

    def get_project_status(self, project_id: str) -> ProjectStatusSnapshot: ...

    def get_experiment_trace(self, query: ExperimentTraceQuery) -> ExperimentTrace: ...

    def get_validation_source(
        self, project_id: str, attempt_id: str
    ) -> ValidationSource: ...

    def load_verified_result(self, attempt_id: str) -> VerifiedResult: ...

    def begin_run(self, command: BeginRunCommand) -> BeginRunResult: ...

    def mark_attempt_running(
        self, attempt_id: str, started_at: datetime, session_id: str
    ) -> None: ...

    def complete_attempt(self, command: CompleteAttemptCommand) -> StoredRunResult: ...

    def begin_validation(
        self, command: BeginValidationCommand
    ) -> BeginValidationResult: ...

    def mark_validation_running(
        self, validation_id: str, started_at: datetime
    ) -> None: ...

    def complete_validation(
        self, command: CompleteValidationCommand
    ) -> StoredValidationResult: ...

    def recover_previous_session(
        self, current_session_id: str, recovered_at: datetime
    ) -> RecoveryReport: ...

    def inspect_integrity(self, deep: bool) -> StoreIntegrityReport: ...


__all__ = [
    "BeginRunCommand",
    "BeginRunResult",
    "BeginValidationCommand",
    "BeginValidationResult",
    "CompleteAttemptCommand",
    "CompleteValidationCommand",
    "CreateProjectCommand",
    "ExperimentTrace",
    "ExperimentTraceQuery",
    "IntegrityCheckMode",
    "IntegrityCheckOutcome",
    "LegacyAttempt",
    "LegacyIdempotencyRecord",
    "LegacyOperationTool",
    "LegacyValidation",
    "ProjectStateInspection",
    "ProjectStatusSnapshot",
    "ProjectStore",
    "ProjectStoreError",
    "ProjectWriteResult",
    "RecoveryReport",
    "StoreIntegrityReport",
    "StoreIntegrityCheck",
    "StoreIntegrityIssue",
    "StoredRunResult",
    "StoredValidationResult",
    "ValidationSource",
    "VerifiedResult",
    "WriteOperation",
]
