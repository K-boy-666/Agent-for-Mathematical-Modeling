from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from modeling_core.domain.models import (
    Attempt,
    Project,
    ResultSnapshot,
    Validation,
)
from modeling_core.domain.states import (
    AttemptStatus,
    ResultKind,
    TerminalReason,
    ValidationOutcome,
    ValidationStatus,
)
from modeling_core.domain.transitions import (
    validate_attempt_transition,
    validate_validation_transition,
)


NOW = datetime(2026, 7, 17, tzinfo=UTC)


def result(kind: ResultKind = ResultKind.SUCCESS) -> ResultSnapshot:
    return ResultSnapshot(
        result_snapshot_id="result-1",
        attempt_id="attempt-1",
        result_kind=kind,
        result_schema_version="modeling-result/0.1.0",
        result_hash="sha256:" + "0" * 64,
        result_payload=object(),
    )


def attempt(**changes: object) -> Attempt:
    fields: dict[str, object] = {
        "attempt_id": "attempt-1",
        "experiment_id": "experiment-1",
        "implementation_id": "implementation-1",
        "implementation_version": "0.1.0",
        "environment_summary": {},
        "randomness": "not_used",
        "seed": None,
        "session_id": "session-1",
        "status": AttemptStatus.PENDING,
        "created_at": NOW,
    }
    fields.update(changes)
    return Attempt(**fields)  # type: ignore[arg-type]


def validation(**changes: object) -> Validation:
    fields: dict[str, object] = {
        "validation_id": "validation-1",
        "attempt_id": "attempt-1",
        "expected_result_hash": "sha256:" + "0" * 64,
        "result_hash": "sha256:" + "0" * 64,
        "validator_id": "validator-1",
        "validator_implementation_id": "validator-implementation-1",
        "validator_implementation_version": "0.1.0",
        "policy_version": "0.1.0",
        "policy": {},
        "policy_hash": "sha256:" + "0" * 64,
        "status": ValidationStatus.PENDING,
        "created_at": NOW,
    }
    fields.update(changes)
    return Validation(**fields)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (AttemptStatus.PENDING, AttemptStatus.RUNNING),
        (AttemptStatus.PENDING, AttemptStatus.ABANDONED),
        (AttemptStatus.RUNNING, AttemptStatus.SUCCEEDED),
        (AttemptStatus.RUNNING, AttemptStatus.NUMERICAL_FAILURE),
        (AttemptStatus.RUNNING, AttemptStatus.ERRORED),
        (AttemptStatus.RUNNING, AttemptStatus.TIMED_OUT),
        (AttemptStatus.RUNNING, AttemptStatus.ABANDONED),
    ],
)
def test_attempt_transition_accepts_every_legal_edge(
    before: AttemptStatus, after: AttemptStatus
) -> None:
    validate_attempt_transition(before, after)


@pytest.mark.parametrize(
    "before, after",
    [
        (before, after)
        for before in AttemptStatus
        for after in AttemptStatus
        if (before, after)
        not in {
            (AttemptStatus.PENDING, AttemptStatus.RUNNING),
            (AttemptStatus.PENDING, AttemptStatus.ABANDONED),
            (AttemptStatus.RUNNING, AttemptStatus.SUCCEEDED),
            (AttemptStatus.RUNNING, AttemptStatus.NUMERICAL_FAILURE),
            (AttemptStatus.RUNNING, AttemptStatus.ERRORED),
            (AttemptStatus.RUNNING, AttemptStatus.TIMED_OUT),
            (AttemptStatus.RUNNING, AttemptStatus.ABANDONED),
        }
    ],
)
def test_attempt_transition_rejects_every_unspecified_edge(
    before: AttemptStatus, after: AttemptStatus
) -> None:
    with pytest.raises(ValueError):
        validate_attempt_transition(before, after)


@pytest.mark.parametrize(
    ("before", "after"),
    [
        (ValidationStatus.PENDING, ValidationStatus.RUNNING),
        (ValidationStatus.PENDING, ValidationStatus.ABANDONED),
        (ValidationStatus.RUNNING, ValidationStatus.SUCCEEDED),
        (ValidationStatus.RUNNING, ValidationStatus.ERRORED),
        (ValidationStatus.RUNNING, ValidationStatus.TIMED_OUT),
        (ValidationStatus.RUNNING, ValidationStatus.ABANDONED),
    ],
)
def test_validation_transition_accepts_every_legal_edge(
    before: ValidationStatus, after: ValidationStatus
) -> None:
    validate_validation_transition(before, after)


@pytest.mark.parametrize(
    "before, after",
    [
        (before, after)
        for before in ValidationStatus
        for after in ValidationStatus
        if (before, after)
        not in {
            (ValidationStatus.PENDING, ValidationStatus.RUNNING),
            (ValidationStatus.PENDING, ValidationStatus.ABANDONED),
            (ValidationStatus.RUNNING, ValidationStatus.SUCCEEDED),
            (ValidationStatus.RUNNING, ValidationStatus.ERRORED),
            (ValidationStatus.RUNNING, ValidationStatus.TIMED_OUT),
            (ValidationStatus.RUNNING, ValidationStatus.ABANDONED),
        }
    ],
)
def test_validation_transition_rejects_every_unspecified_edge(
    before: ValidationStatus, after: ValidationStatus
) -> None:
    with pytest.raises(ValueError):
        validate_validation_transition(before, after)


def test_attempt_succeeded_requires_one_success_result() -> None:
    with pytest.raises(ValueError, match="SUCCEEDED"):
        attempt(
            status=AttemptStatus.SUCCEEDED,
            started_at=NOW,
            finished_at=NOW,
        )

    attempt(
        status=AttemptStatus.SUCCEEDED,
        started_at=NOW,
        finished_at=NOW,
        result=result(ResultKind.SUCCESS),
    )


def test_attempt_numerical_failure_requires_one_matching_failure_result() -> None:
    with pytest.raises(ValueError, match="NUMERICAL_FAILURE"):
        attempt(
            status=AttemptStatus.NUMERICAL_FAILURE,
            started_at=NOW,
            finished_at=NOW,
        )

    attempt(
        status=AttemptStatus.NUMERICAL_FAILURE,
        started_at=NOW,
        finished_at=NOW,
        result=result(ResultKind.NUMERICAL_FAILURE),
        numerical_failure=object(),
    )


def test_attempt_errored_requires_error_and_forbids_result() -> None:
    with pytest.raises(ValueError, match="ERRORED"):
        attempt(status=AttemptStatus.ERRORED, started_at=NOW, finished_at=NOW)
    with pytest.raises(ValueError, match="ERRORED"):
        attempt(
            status=AttemptStatus.ERRORED,
            started_at=NOW,
            finished_at=NOW,
            system_error=object(),
            result=result(),
        )

    attempt(
        status=AttemptStatus.ERRORED,
        started_at=NOW,
        finished_at=NOW,
        system_error=object(),
    )


def test_attempt_timed_out_requires_deadline_reason() -> None:
    with pytest.raises(ValueError, match="TIMED_OUT"):
        attempt(
            status=AttemptStatus.TIMED_OUT,
            started_at=NOW,
            finished_at=NOW,
            terminal_reason=TerminalReason.HOST_CANCELLED,
        )

    attempt(
        status=AttemptStatus.TIMED_OUT,
        started_at=NOW,
        finished_at=NOW,
        terminal_reason=TerminalReason.DEADLINE_EXCEEDED,
    )


@pytest.mark.parametrize(
    "reason",
    [TerminalReason.HOST_CANCELLED, TerminalReason.SERVER_RECOVERY],
)
def test_attempt_abandoned_requires_permitted_reason(reason: TerminalReason) -> None:
    attempt(
        status=AttemptStatus.ABANDONED,
        finished_at=NOW,
        terminal_reason=reason,
    )


def test_validation_success_requires_outcome_and_report() -> None:
    with pytest.raises(ValueError, match="SUCCEEDED"):
        validation(
            status=ValidationStatus.SUCCEEDED,
            started_at=NOW,
            finished_at=NOW,
        )

    validation(
        status=ValidationStatus.SUCCEEDED,
        started_at=NOW,
        finished_at=NOW,
        outcome=ValidationOutcome.PASSED,
        report_payload=object(),
        validation_report_hash="sha256:" + "0" * 64,
    )


@pytest.mark.parametrize(
    "status",
    [
        ValidationStatus.PENDING,
        ValidationStatus.RUNNING,
        ValidationStatus.ERRORED,
        ValidationStatus.TIMED_OUT,
        ValidationStatus.ABANDONED,
    ],
)
def test_validation_outcome_and_report_exist_only_for_succeeded(
    status: ValidationStatus,
) -> None:
    extra: dict[str, object] = {}
    if status is not ValidationStatus.PENDING:
        extra["started_at"] = NOW
    if status not in {ValidationStatus.PENDING, ValidationStatus.RUNNING}:
        extra["finished_at"] = NOW
    if status is ValidationStatus.ERRORED:
        extra["operational_error"] = object()
    if status is ValidationStatus.TIMED_OUT:
        extra["terminal_reason"] = TerminalReason.DEADLINE_EXCEEDED
    if status is ValidationStatus.ABANDONED:
        extra["terminal_reason"] = TerminalReason.HOST_CANCELLED
    extra["outcome"] = ValidationOutcome.FAILED
    with pytest.raises(ValueError):
        validation(**extra)


def test_randomness_not_used_requires_null_seed() -> None:
    with pytest.raises(ValueError, match="not_used"):
        attempt(seed=7)


def test_domain_records_are_frozen() -> None:
    project = Project(
        project_id="project-1",
        storage_instance_id="storage-1",
        project_format_version="modeling-project/0.1.0",
        display_name="example",
        created_at=NOW,
    )
    with pytest.raises(FrozenInstanceError):
        project.display_name = "other"  # type: ignore[misc]
