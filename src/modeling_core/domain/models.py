"""Frozen domain records with executable contract and terminal-state invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, Literal, cast

from pydantic import Field, TypeAdapter

from modeling_core.contracts.common import (
    EntityId,
    Hash,
    JsonObject,
    Version,
    Warning,
)
from modeling_core.contracts.errors import ErrorResponse
from modeling_core.contracts.tools import (
    CanonicalRootFindingInput,
    DataSnapshotReference,
    EnvironmentSummary,
    ExecutionOptions,
    NumericalFailureData,
    ResultPayload,
    ValidationMetrics,
    ValidationReportPayload,
)
from modeling_core.domain.states import (
    AttemptStatus,
    ResultKind,
    TerminalReason,
    ValidationOutcome,
    ValidationStatus,
)


DisplayName = Annotated[str, Field(min_length=1, max_length=128)]
Seed = Annotated[int | None, Field(ge=-9007199254740991, le=9007199254740991)]


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


@dataclass(frozen=True)
class Project:
    project_id: EntityId
    storage_instance_id: EntityId
    project_format_version: Literal["modeling-project/0.1.0"]
    display_name: DisplayName
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "project_id", _validate(self.project_id, EntityId))
        object.__setattr__(
            self, "storage_instance_id", _validate(self.storage_instance_id, EntityId)
        )
        object.__setattr__(
            self,
            "project_format_version",
            _validate(self.project_format_version, Literal["modeling-project/0.1.0"]),
        )
        object.__setattr__(
            self, "display_name", _validate(self.display_name, DisplayName)
        )
        object.__setattr__(self, "created_at", _validate_timestamp(self.created_at))


@dataclass(frozen=True)
class Experiment:
    experiment_id: EntityId
    project_id: EntityId
    capability_id: str
    contract_version: Version
    canonical_input_schema_version: Literal[
        "numerical.root_finding.canonical-input/0.1.0"
    ]
    canonical_payload: CanonicalRootFindingInput
    canonical_payload_hash: Hash
    model_snapshot_hash: Hash
    data_snapshot_references: tuple[DataSnapshotReference, ...]
    data_snapshot_set_hash: Hash
    execution_policy: ExecutionOptions
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "experiment_id", _validate(self.experiment_id, EntityId)
        )
        object.__setattr__(self, "project_id", _validate(self.project_id, EntityId))
        object.__setattr__(self, "capability_id", _validate(self.capability_id, str))
        object.__setattr__(
            self, "contract_version", _validate(self.contract_version, Version)
        )
        object.__setattr__(
            self,
            "canonical_input_schema_version",
            _validate(
                self.canonical_input_schema_version,
                Literal["numerical.root_finding.canonical-input/0.1.0"],
            ),
        )
        object.__setattr__(
            self,
            "canonical_payload",
            _validate(self.canonical_payload, CanonicalRootFindingInput),
        )
        object.__setattr__(
            self, "canonical_payload_hash", _validate(self.canonical_payload_hash, Hash)
        )
        object.__setattr__(
            self, "model_snapshot_hash", _validate(self.model_snapshot_hash, Hash)
        )
        object.__setattr__(
            self,
            "data_snapshot_references",
            _validate(self.data_snapshot_references, tuple[DataSnapshotReference, ...]),
        )
        object.__setattr__(
            self, "data_snapshot_set_hash", _validate(self.data_snapshot_set_hash, Hash)
        )
        object.__setattr__(
            self, "execution_policy", _validate(self.execution_policy, ExecutionOptions)
        )
        object.__setattr__(self, "created_at", _validate_timestamp(self.created_at))


@dataclass(frozen=True)
class ResultSnapshot:
    result_snapshot_id: EntityId
    attempt_id: EntityId
    result_kind: ResultKind
    result_schema_version: Literal["modeling-result/0.1.0"]
    result_hash: Hash
    result_payload: ResultPayload

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "result_snapshot_id", _validate(self.result_snapshot_id, EntityId)
        )
        object.__setattr__(self, "attempt_id", _validate(self.attempt_id, EntityId))
        object.__setattr__(self, "result_kind", _validate(self.result_kind, ResultKind))
        object.__setattr__(
            self,
            "result_schema_version",
            _validate(self.result_schema_version, Literal["modeling-result/0.1.0"]),
        )
        object.__setattr__(self, "result_hash", _validate(self.result_hash, Hash))
        object.__setattr__(
            self, "result_payload", _validate(self.result_payload, ResultPayload)
        )
        if self.result_payload.result_kind != self.result_kind.value:
            raise ValueError("result snapshot kind must match its payload kind")


@dataclass(frozen=True)
class Attempt:
    attempt_id: EntityId
    experiment_id: EntityId
    implementation_id: str
    implementation_version: Version
    environment_summary: EnvironmentSummary
    randomness: str
    seed: Seed
    session_id: EntityId
    status: AttemptStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    warnings: tuple[Warning, ...] = ()
    result: ResultSnapshot | None = None
    system_error: ErrorResponse | None = None
    numerical_failure: NumericalFailureData | None = None
    terminal_reason: TerminalReason | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "attempt_id", _validate(self.attempt_id, EntityId))
        object.__setattr__(
            self, "experiment_id", _validate(self.experiment_id, EntityId)
        )
        object.__setattr__(
            self, "implementation_id", _validate(self.implementation_id, str)
        )
        object.__setattr__(
            self,
            "implementation_version",
            _validate(self.implementation_version, Version),
        )
        object.__setattr__(
            self,
            "environment_summary",
            _validate(self.environment_summary, EnvironmentSummary),
        )
        object.__setattr__(self, "randomness", _validate(self.randomness, str))
        object.__setattr__(self, "seed", _validate(self.seed, Seed))
        object.__setattr__(self, "session_id", _validate(self.session_id, EntityId))
        object.__setattr__(self, "status", _validate(self.status, AttemptStatus))
        object.__setattr__(self, "created_at", _validate_timestamp(self.created_at))
        if self.started_at is not None:
            object.__setattr__(self, "started_at", _validate_timestamp(self.started_at))
        if self.finished_at is not None:
            object.__setattr__(
                self, "finished_at", _validate_timestamp(self.finished_at)
            )
        object.__setattr__(
            self, "warnings", _validate(self.warnings, tuple[Warning, ...])
        )
        if self.result is not None:
            object.__setattr__(self, "result", _validate(self.result, ResultSnapshot))
        if self.system_error is not None:
            object.__setattr__(
                self, "system_error", _validate(self.system_error, ErrorResponse)
            )
        if self.numerical_failure is not None:
            object.__setattr__(
                self,
                "numerical_failure",
                _validate(self.numerical_failure, NumericalFailureData),
            )
        if self.terminal_reason is not None:
            object.__setattr__(
                self,
                "terminal_reason",
                _validate(self.terminal_reason, TerminalReason),
            )
        if self.randomness == "not_used" and self.seed is not None:
            raise ValueError("randomness=not_used requires seed is None")

        no_outputs = (
            self.result is None
            and self.system_error is None
            and self.numerical_failure is None
            and self.terminal_reason is None
        )
        if self.status is AttemptStatus.PENDING:
            if (
                self.started_at is not None
                or self.finished_at is not None
                or not no_outputs
            ):
                raise ValueError("PENDING attempt has no timestamps or outputs")
        elif self.status is AttemptStatus.RUNNING:
            if (
                self.started_at is None
                or self.finished_at is not None
                or not no_outputs
            ):
                raise ValueError("RUNNING attempt requires only started_at")
        elif self.status is AttemptStatus.SUCCEEDED:
            if (
                self.started_at is None
                or self.finished_at is None
                or self.result is None
                or self.result.result_kind is not ResultKind.SUCCESS
                or self.system_error is not None
                or self.numerical_failure is not None
                or self.terminal_reason is not None
            ):
                raise ValueError("SUCCEEDED attempt requires one success result")
        elif self.status is AttemptStatus.NUMERICAL_FAILURE:
            if (
                self.started_at is None
                or self.finished_at is None
                or self.result is None
                or self.result.result_kind is not ResultKind.NUMERICAL_FAILURE
                or self.numerical_failure is None
                or self.result.result_payload.data != self.numerical_failure
                or self.system_error is not None
                or self.terminal_reason is not None
            ):
                raise ValueError(
                    "NUMERICAL_FAILURE attempt requires one matching failure result"
                )
        elif self.status is AttemptStatus.ERRORED:
            if (
                self.started_at is None
                or self.finished_at is None
                or self.result is not None
                or self.system_error is None
                or self.numerical_failure is not None
                or self.terminal_reason is not None
            ):
                raise ValueError("ERRORED attempt requires only system_error")
        elif self.status is AttemptStatus.TIMED_OUT:
            if (
                self.started_at is None
                or self.finished_at is None
                or self.result is not None
                or self.system_error is not None
                or self.numerical_failure is not None
                or self.terminal_reason is not TerminalReason.DEADLINE_EXCEEDED
            ):
                raise ValueError("TIMED_OUT attempt requires deadline_exceeded")
        elif (
            self.finished_at is None
            or self.result is not None
            or self.system_error is not None
            or self.numerical_failure is not None
            or self.terminal_reason
            not in {TerminalReason.HOST_CANCELLED, TerminalReason.SERVER_RECOVERY}
        ):
            raise ValueError("ABANDONED attempt requires an allowed terminal reason")


@dataclass(frozen=True)
class Validation:
    validation_id: EntityId
    attempt_id: EntityId
    expected_result_hash: Hash
    result_hash: Hash
    validator_id: Literal["numerical.root_finding.residual"]
    validator_implementation_id: str
    validator_implementation_version: Version
    policy_version: Literal["0.1.0"]
    policy: JsonObject
    policy_hash: Hash
    status: ValidationStatus
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    outcome: ValidationOutcome | None = None
    metrics: ValidationMetrics | None = None
    validation_report_hash: Hash | None = None
    report_payload: ValidationReportPayload | None = None
    operational_error: ErrorResponse | None = None
    terminal_reason: TerminalReason | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "validation_id", _validate(self.validation_id, EntityId)
        )
        object.__setattr__(self, "attempt_id", _validate(self.attempt_id, EntityId))
        object.__setattr__(
            self, "expected_result_hash", _validate(self.expected_result_hash, Hash)
        )
        object.__setattr__(self, "result_hash", _validate(self.result_hash, Hash))
        object.__setattr__(
            self,
            "validator_id",
            _validate(self.validator_id, Literal["numerical.root_finding.residual"]),
        )
        object.__setattr__(
            self,
            "validator_implementation_id",
            _validate(self.validator_implementation_id, str),
        )
        object.__setattr__(
            self,
            "validator_implementation_version",
            _validate(self.validator_implementation_version, Version),
        )
        object.__setattr__(
            self, "policy_version", _validate(self.policy_version, Literal["0.1.0"])
        )
        object.__setattr__(self, "policy", _validate(self.policy, JsonObject))
        object.__setattr__(self, "policy_hash", _validate(self.policy_hash, Hash))
        object.__setattr__(self, "status", _validate(self.status, ValidationStatus))
        object.__setattr__(self, "created_at", _validate_timestamp(self.created_at))
        if self.started_at is not None:
            object.__setattr__(self, "started_at", _validate_timestamp(self.started_at))
        if self.finished_at is not None:
            object.__setattr__(
                self, "finished_at", _validate_timestamp(self.finished_at)
            )
        if self.outcome is not None:
            object.__setattr__(
                self, "outcome", _validate(self.outcome, ValidationOutcome)
            )
        if self.metrics is not None:
            object.__setattr__(
                self, "metrics", _validate(self.metrics, ValidationMetrics)
            )
        if self.validation_report_hash is not None:
            object.__setattr__(
                self,
                "validation_report_hash",
                _validate(self.validation_report_hash, Hash),
            )
        if self.report_payload is not None:
            object.__setattr__(
                self,
                "report_payload",
                _validate(self.report_payload, ValidationReportPayload),
            )
        if self.operational_error is not None:
            object.__setattr__(
                self,
                "operational_error",
                _validate(self.operational_error, ErrorResponse),
            )
        if self.terminal_reason is not None:
            object.__setattr__(
                self,
                "terminal_reason",
                _validate(self.terminal_reason, TerminalReason),
            )

        no_outputs = (
            self.outcome is None
            and self.metrics is None
            and self.validation_report_hash is None
            and self.report_payload is None
            and self.operational_error is None
            and self.terminal_reason is None
        )
        if self.status is ValidationStatus.PENDING:
            if (
                self.started_at is not None
                or self.finished_at is not None
                or not no_outputs
            ):
                raise ValueError("PENDING validation has no timestamps or outputs")
        elif self.status is ValidationStatus.RUNNING:
            if (
                self.started_at is None
                or self.finished_at is not None
                or not no_outputs
            ):
                raise ValueError("RUNNING validation requires only started_at")
        elif self.status is ValidationStatus.SUCCEEDED:
            if (
                self.started_at is None
                or self.finished_at is None
                or self.outcome is None
                or self.metrics is None
                or self.validation_report_hash is None
                or self.report_payload is None
                or self.report_payload.outcome != self.outcome.value
                or self.report_payload.metrics != self.metrics
                or self.report_payload.result_hash != self.result_hash
                or self.operational_error is not None
                or self.terminal_reason is not None
            ):
                raise ValueError(
                    "SUCCEEDED validation requires matching outcome, metrics, and report"
                )
        elif self.status is ValidationStatus.ERRORED:
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
        elif self.status is ValidationStatus.TIMED_OUT:
            if (
                self.started_at is None
                or self.finished_at is None
                or self.outcome is not None
                or self.metrics is not None
                or self.validation_report_hash is not None
                or self.report_payload is not None
                or self.operational_error is not None
                or self.terminal_reason is not TerminalReason.DEADLINE_EXCEEDED
            ):
                raise ValueError("TIMED_OUT validation requires deadline_exceeded")
        elif (
            self.finished_at is None
            or self.outcome is not None
            or self.metrics is not None
            or self.validation_report_hash is not None
            or self.report_payload is not None
            or self.operational_error is not None
            or self.terminal_reason
            not in {TerminalReason.HOST_CANCELLED, TerminalReason.SERVER_RECOVERY}
        ):
            raise ValueError("ABANDONED validation requires an allowed terminal reason")


@dataclass(frozen=True)
class InputSnapshot:
    """Immutable independently referenced canonical input provenance."""

    input_snapshot_id: EntityId
    canonical_input_schema_version: str
    canonical_payload_hash: Hash
    model_snapshot_hash: Hash
    data_snapshot_references: tuple[DataSnapshotReference, ...]
    data_snapshot_set_hash: Hash
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "input_snapshot_id",
            _validate(self.input_snapshot_id, EntityId),
        )
        object.__setattr__(
            self,
            "canonical_input_schema_version",
            _validate(self.canonical_input_schema_version, str),
        )
        if not self.canonical_input_schema_version:
            raise ValueError("canonical_input_schema_version must not be empty")
        object.__setattr__(
            self,
            "canonical_payload_hash",
            _validate(self.canonical_payload_hash, Hash),
        )
        object.__setattr__(
            self, "model_snapshot_hash", _validate(self.model_snapshot_hash, Hash)
        )
        object.__setattr__(
            self,
            "data_snapshot_references",
            _validate(self.data_snapshot_references, tuple[DataSnapshotReference, ...]),
        )
        object.__setattr__(
            self, "data_snapshot_set_hash", _validate(self.data_snapshot_set_hash, Hash)
        )
        object.__setattr__(self, "created_at", _validate_timestamp(self.created_at))


@dataclass(frozen=True)
class EnvironmentSnapshot:
    """Immutable allowlisted environment evidence captured per attempt."""

    environment_snapshot_id: EntityId
    environment_document: JsonObject
    environment_hash: Hash
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "environment_snapshot_id",
            _validate(self.environment_snapshot_id, EntityId),
        )
        object.__setattr__(
            self,
            "environment_document",
            _validate(self.environment_document, JsonObject),
        )
        object.__setattr__(
            self, "environment_hash", _validate(self.environment_hash, Hash)
        )
        object.__setattr__(self, "created_at", _validate_timestamp(self.created_at))


@dataclass(frozen=True)
class Artifact:
    """One immutable content-addressed JSON artifact reference."""

    artifact_id: Hash
    role: str
    media_type: str
    byte_size: int
    sha256: Hash
    schema_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _validate(self.artifact_id, Hash))
        object.__setattr__(self, "role", _validate(self.role, str))
        if not self.role:
            raise ValueError("role must not be empty")
        object.__setattr__(self, "media_type", _validate(self.media_type, str))
        if not self.media_type:
            raise ValueError("media_type must not be empty")
        if isinstance(self.byte_size, bool) or not isinstance(self.byte_size, int):
            raise ValueError("byte_size must be an integer")
        if self.byte_size < 0:
            raise ValueError("byte_size must be non-negative")
        object.__setattr__(self, "sha256", _validate(self.sha256, Hash))
        if self.artifact_id != self.sha256:
            raise ValueError("artifact_id must equal its content sha256")
        object.__setattr__(self, "schema_id", _validate(self.schema_id, str))
        if not self.schema_id:
            raise ValueError("schema_id must not be empty")
        object.__setattr__(self, "created_at", _validate_timestamp(self.created_at))
