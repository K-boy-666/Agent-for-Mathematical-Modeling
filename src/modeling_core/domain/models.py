"""Frozen domain records with executable terminal-state invariants."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from modeling_core.contracts.common import EntityId, Hash, JsonObject, Warning
from modeling_core.contracts.errors import ErrorResponse
from modeling_core.contracts.tools import (
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


@dataclass(frozen=True)
class Project:
    project_id: EntityId
    storage_instance_id: EntityId
    project_format_version: str
    display_name: str
    created_at: datetime


@dataclass(frozen=True)
class Experiment:
    experiment_id: EntityId
    project_id: EntityId
    capability_id: str
    contract_version: str
    canonical_input_schema_version: str
    canonical_payload: JsonObject
    canonical_payload_hash: Hash
    model_snapshot_hash: Hash
    data_snapshot_references: tuple[JsonObject, ...]
    data_snapshot_set_hash: Hash
    execution_policy: ExecutionOptions
    created_at: datetime


@dataclass(frozen=True)
class ResultSnapshot:
    result_snapshot_id: EntityId
    attempt_id: EntityId
    result_kind: ResultKind
    result_schema_version: str
    result_hash: Hash
    result_payload: ResultPayload


@dataclass(frozen=True)
class Attempt:
    attempt_id: EntityId
    experiment_id: EntityId
    implementation_id: str
    implementation_version: str
    environment_summary: EnvironmentSummary
    randomness: str
    seed: int | None
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
        if self.randomness == "not_used" and self.seed is not None:
            raise ValueError("randomness=not_used requires seed is None")

        no_outputs = (
            self.result is None
            and self.system_error is None
            and self.numerical_failure is None
            and self.terminal_reason is None
        )
        if self.status is AttemptStatus.PENDING:
            if self.started_at is not None or self.finished_at is not None or not no_outputs:
                raise ValueError("PENDING attempt has no timestamps or outputs")
        elif self.status is AttemptStatus.RUNNING:
            if self.started_at is None or self.finished_at is not None or not no_outputs:
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
                or self.system_error is not None
                or self.terminal_reason is not None
            ):
                raise ValueError(
                    "NUMERICAL_FAILURE attempt requires one numerical failure result"
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
    validator_id: str
    validator_implementation_id: str
    validator_implementation_version: str
    policy_version: str
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
        no_outputs = (
            self.outcome is None
            and self.metrics is None
            and self.validation_report_hash is None
            and self.report_payload is None
            and self.operational_error is None
            and self.terminal_reason is None
        )
        if self.status is ValidationStatus.PENDING:
            if self.started_at is not None or self.finished_at is not None or not no_outputs:
                raise ValueError("PENDING validation has no timestamps or outputs")
        elif self.status is ValidationStatus.RUNNING:
            if self.started_at is None or self.finished_at is not None or not no_outputs:
                raise ValueError("RUNNING validation requires only started_at")
        elif self.status is ValidationStatus.SUCCEEDED:
            if (
                self.started_at is None
                or self.finished_at is None
                or self.outcome is None
                or self.validation_report_hash is None
                or self.report_payload is None
                or self.operational_error is not None
                or self.terminal_reason is not None
            ):
                raise ValueError("SUCCEEDED validation requires an outcome and report")
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
