"""Use-case-shaped, typed persistence boundary for one project."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Protocol, cast

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
    Experiment,
    Project,
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

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _validate(self.operation, WriteOperation))
        experiment = _validate(self.experiment, Experiment)
        attempt = _validate(self.attempt, Attempt)
        _validate_attempt_result_owner(attempt)
        if attempt.status is not AttemptStatus.PENDING:
            raise ValueError("begin-run attempt must be PENDING")
        if attempt.experiment_id != experiment.experiment_id:
            raise ValueError("attempt must belong to experiment")
        object.__setattr__(self, "experiment", experiment)
        object.__setattr__(self, "attempt", attempt)


@dataclass(frozen=True)
class BeginRunResult:
    experiment: Experiment
    attempt: Attempt
    replayed: bool

    def __post_init__(self) -> None:
        experiment = _validate(self.experiment, Experiment)
        attempt = _validate(self.attempt, Attempt)
        replayed = _BOOL.validate_python(self.replayed, strict=True)
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


@dataclass(frozen=True)
class CompleteAttemptCommand:
    operation: WriteOperation
    attempt: Attempt

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _validate(self.operation, WriteOperation))
        attempt = _validate(self.attempt, Attempt)
        _require_terminal_attempt(attempt)
        object.__setattr__(self, "attempt", attempt)


@dataclass(frozen=True)
class StoredRunResult:
    attempt: Attempt

    def __post_init__(self) -> None:
        attempt = _validate(self.attempt, Attempt)
        _require_terminal_attempt(attempt)
        object.__setattr__(self, "attempt", attempt)


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

    def __post_init__(self) -> None:
        validation = _validate(self.validation, Validation)
        replayed = _BOOL.validate_python(self.replayed, strict=True)
        if replayed and validation.status not in _TERMINAL_VALIDATIONS:
            raise ValueError("replayed begin-validation result must be terminal")
        if not replayed and validation.status is not ValidationStatus.PENDING:
            raise ValueError("new begin-validation result must be PENDING")
        object.__setattr__(self, "validation", validation)
        object.__setattr__(self, "replayed", replayed)


@dataclass(frozen=True)
class CompleteValidationCommand:
    operation: WriteOperation
    validation: Validation

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation", _validate(self.operation, WriteOperation))
        validation = _validate(self.validation, Validation)
        _require_terminal_validation(validation)
        object.__setattr__(self, "validation", validation)


@dataclass(frozen=True)
class StoredValidationResult:
    validation: Validation

    def __post_init__(self) -> None:
        validation = _validate(self.validation, Validation)
        _require_terminal_validation(validation)
        object.__setattr__(self, "validation", validation)


@dataclass(frozen=True)
class StoreIntegrityReport:
    state: ProjectState
    issues: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "state", _validate(self.state, ProjectState))
        object.__setattr__(self, "issues", _validate(self.issues, tuple[str, ...]))


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
    def inspect_project_state(self) -> ProjectStateInspection: ...

    def create_or_replay_project(
        self, command: CreateProjectCommand
    ) -> ProjectWriteResult: ...

    def get_project_status(self, project_id: str) -> ProjectStatusSnapshot: ...

    def get_experiment_trace(self, query: ExperimentTraceQuery) -> ExperimentTrace: ...

    def get_validation_source(
        self, project_id: str, attempt_id: str
    ) -> ValidationSource: ...

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
    "ProjectStateInspection",
    "ProjectStatusSnapshot",
    "ProjectStore",
    "ProjectStoreError",
    "ProjectWriteResult",
    "StoreIntegrityReport",
    "StoredRunResult",
    "StoredValidationResult",
    "ValidationSource",
    "WriteOperation",
]
