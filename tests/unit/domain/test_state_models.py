from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from modeling_core.contracts.common import Warning
from modeling_core.contracts.errors import ErrorResponse, InternalErrorDetails
from modeling_core.contracts.tools import (
    EnvironmentSummary,
    ExecutionOptions,
    NumericalFailureData,
    ResultSuccessData,
    SuccessResultPayload,
    ValidationMetrics,
    ValidationReportPayload,
)
from modeling_core.domain.models import (
    Attempt,
    Experiment,
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
PROJECT_ID = "00000000-0000-4000-8000-000000000001"
STORAGE_ID = "00000000-0000-4000-8000-000000000002"
EXPERIMENT_ID = "00000000-0000-4000-8000-000000000003"
ATTEMPT_ID = "00000000-0000-4000-8000-000000000004"
RESULT_ID = "00000000-0000-4000-8000-000000000005"
VALIDATION_ID = "00000000-0000-4000-8000-000000000006"
SESSION_ID = "00000000-0000-4000-8000-000000000007"
CORRELATION_ID = "00000000-0000-4000-8000-000000000008"
HASH = "sha256:" + "0" * 64


def environment() -> EnvironmentSummary:
    return EnvironmentSummary(
        python_version="3.11.9",
        application_version="0.1.0",
        lock_hash=HASH,
    )


def warning() -> Warning:
    return Warning(code="notice", message="valid warning")


def operational_error() -> ErrorResponse:
    return ErrorResponse(
        error_schema_version="modeling-error/0.1.0",
        code="INTERNAL_ERROR",
        message="operation failed",
        retryable=False,
        correlation_id=CORRELATION_ID,
        details=InternalErrorDetails(event_id=CORRELATION_ID),
    )


def success_payload() -> SuccessResultPayload:
    return SuccessResultPayload(
        result_schema_version="modeling-result/0.1.0",
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        result_kind="success",
        data=ResultSuccessData(
            root=1.0,
            function_value=0.0,
            iterations=1,
            evaluations=1,
            termination_reason="endpoint_root",
        ),
    )


def failure_data() -> NumericalFailureData:
    return NumericalFailureData(
        failure_code="no_sign_change", iterations=0, evaluations=0
    )


def result(kind: ResultKind = ResultKind.SUCCESS) -> ResultSnapshot:
    payload = success_payload()
    if kind is ResultKind.NUMERICAL_FAILURE:
        from modeling_core.contracts.tools import FailureResultPayload

        payload = FailureResultPayload(
            result_schema_version="modeling-result/0.1.0",
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
            result_kind="numerical_failure",
            data=failure_data(),
        )
    return ResultSnapshot(
        result_snapshot_id=RESULT_ID,
        attempt_id=ATTEMPT_ID,
        result_kind=kind,
        result_schema_version="modeling-result/0.1.0",
        result_hash=HASH,
        result_payload=payload,
    )


def metrics() -> ValidationMetrics:
    return ValidationMetrics(
        root_within_interval=True,
        reported_function_value=0.0,
        recomputed_function_value=0.0,
        absolute_reported_delta=0.0,
        absolute_residual=0.0,
        function_tolerance=1e-10,
        failed_checks=(),
    )


def report(outcome: ValidationOutcome = ValidationOutcome.PASSED) -> ValidationReportPayload:
    return ValidationReportPayload(
        report_schema_version="modeling-validation-report/0.1.0",
        validator_id="numerical.root_finding.residual",
        validator_implementation_id="residual-validator",
        validator_implementation_version="0.1.0",
        policy_version="0.1.0",
        policy={},
        policy_hash=HASH,
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        canonical_payload_hash=HASH,
        model_snapshot_hash=HASH,
        data_snapshot_set_hash=HASH,
        result_hash=HASH,
        outcome=outcome.value,
        metrics=metrics(),
    )


def attempt(**changes: object) -> Attempt:
    fields = {
        "attempt_id": ATTEMPT_ID,
        "experiment_id": EXPERIMENT_ID,
        "implementation_id": "root-finding",
        "implementation_version": "0.1.0",
        "environment_summary": environment(),
        "randomness": "not_used",
        "seed": None,
        "session_id": SESSION_ID,
        "status": AttemptStatus.PENDING,
        "created_at": NOW,
        "warnings": (warning(),),
    }
    fields.update(changes)
    return Attempt(**fields)


def validation(**changes: object) -> Validation:
    fields = {
        "validation_id": VALIDATION_ID,
        "attempt_id": ATTEMPT_ID,
        "expected_result_hash": HASH,
        "result_hash": HASH,
        "validator_id": "numerical.root_finding.residual",
        "validator_implementation_id": "residual-validator",
        "validator_implementation_version": "0.1.0",
        "policy_version": "0.1.0",
        "policy": {},
        "policy_hash": HASH,
        "status": ValidationStatus.PENDING,
        "created_at": NOW,
    }
    fields.update(changes)
    return Validation(**fields)


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


def test_result_snapshot_requires_a_valid_matching_payload() -> None:
    with pytest.raises(ValueError, match="match"):
        ResultSnapshot(
            result_snapshot_id=RESULT_ID,
            attempt_id=ATTEMPT_ID,
            result_kind=ResultKind.NUMERICAL_FAILURE,
            result_schema_version="modeling-result/0.1.0",
            result_hash=HASH,
            result_payload=success_payload(),
        )
    with pytest.raises(ValidationError):
        ResultSnapshot(
            result_snapshot_id=RESULT_ID,
            attempt_id=ATTEMPT_ID,
            result_kind=ResultKind.SUCCESS,
            result_schema_version="modeling-result/0.1.0",
            result_hash=HASH,
            result_payload=object(),
        )


def test_attempt_succeeded_requires_one_success_result() -> None:
    with pytest.raises(ValueError, match="SUCCEEDED"):
        attempt(status=AttemptStatus.SUCCEEDED, started_at=NOW, finished_at=NOW)
    attempt(
        status=AttemptStatus.SUCCEEDED,
        started_at=NOW,
        finished_at=NOW,
        result=result(),
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
        numerical_failure=failure_data(),
    )


def test_attempt_errored_requires_error_and_forbids_result() -> None:
    with pytest.raises(ValueError, match="ERRORED"):
        attempt(status=AttemptStatus.ERRORED, started_at=NOW, finished_at=NOW)
    with pytest.raises(ValueError, match="ERRORED"):
        attempt(
            status=AttemptStatus.ERRORED,
            started_at=NOW,
            finished_at=NOW,
            system_error=operational_error(),
            result=result(),
        )
    attempt(
        status=AttemptStatus.ERRORED,
        started_at=NOW,
        finished_at=NOW,
        system_error=operational_error(),
    )


def test_attempt_rejects_invalid_contract_values() -> None:
    with pytest.raises(ValidationError):
        attempt(attempt_id="not-a-uuid")
    with pytest.raises(ValidationError):
        attempt(environment_summary={})
    with pytest.raises(ValidationError):
        attempt(warnings=("not-a-warning",))
    with pytest.raises(ValidationError):
        attempt(
            status=AttemptStatus.ERRORED,
            started_at=NOW,
            finished_at=NOW,
            system_error="not-an-error",
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


def test_validation_success_requires_matching_outcome_metrics_and_report() -> None:
    with pytest.raises(ValueError, match="SUCCEEDED"):
        validation(
            status=ValidationStatus.SUCCEEDED,
            started_at=NOW,
            finished_at=NOW,
            outcome=ValidationOutcome.PASSED,
            report_payload=report(),
            validation_report_hash=HASH,
        )
    with pytest.raises(ValueError, match="match"):
        validation(
            status=ValidationStatus.SUCCEEDED,
            started_at=NOW,
            finished_at=NOW,
            outcome=ValidationOutcome.FAILED,
            metrics=metrics(),
            report_payload=report(),
            validation_report_hash=HASH,
        )
    validation(
        status=ValidationStatus.SUCCEEDED,
        started_at=NOW,
        finished_at=NOW,
        outcome=ValidationOutcome.PASSED,
        metrics=metrics(),
        report_payload=report(),
        validation_report_hash=HASH,
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
        extra["operational_error"] = operational_error()
    if status is ValidationStatus.TIMED_OUT:
        extra["terminal_reason"] = TerminalReason.DEADLINE_EXCEEDED
    if status is ValidationStatus.ABANDONED:
        extra["terminal_reason"] = TerminalReason.HOST_CANCELLED
    extra["outcome"] = ValidationOutcome.FAILED
    with pytest.raises(ValueError):
        validation(**extra)


def test_validation_rejects_invalid_contract_values() -> None:
    with pytest.raises(ValidationError):
        validation(expected_result_hash="not-a-hash")
    with pytest.raises(ValidationError):
        validation(policy=[])
    with pytest.raises(ValidationError):
        validation(
            status=ValidationStatus.ERRORED,
            started_at=NOW,
            finished_at=NOW,
            operational_error="not-an-error",
        )


def test_randomness_not_used_requires_null_seed() -> None:
    with pytest.raises(ValueError, match="not_used"):
        attempt(seed=7)


def test_project_and_experiment_validate_contract_values() -> None:
    with pytest.raises(ValidationError):
        Project(
            project_id="not-a-uuid",
            storage_instance_id=STORAGE_ID,
            project_format_version="modeling-project/0.1.0",
            display_name="example",
            created_at=NOW,
        )
    with pytest.raises(ValidationError):
        Experiment(
            experiment_id=EXPERIMENT_ID,
            project_id=PROJECT_ID,
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
            canonical_input_schema_version=(
                "numerical.root_finding.canonical-input/0.1.0"
            ),
            canonical_payload={},
            canonical_payload_hash=HASH,
            model_snapshot_hash=HASH,
            data_snapshot_references=(),
            data_snapshot_set_hash=HASH,
            execution_policy=ExecutionOptions(timeout_ms=10, seed=None),
            created_at=NOW,
        )


def test_domain_records_are_frozen() -> None:
    project = Project(
        project_id=PROJECT_ID,
        storage_instance_id=STORAGE_ID,
        project_format_version="modeling-project/0.1.0",
        display_name="example",
        created_at=NOW,
    )
    with pytest.raises(FrozenInstanceError):
        setattr(project, "display_name", "other")
