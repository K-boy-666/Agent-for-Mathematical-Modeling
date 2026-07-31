from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from pydantic import ValidationError

from modeling_core.contracts.tools import (
    AttemptStatusCounts,
    CanonicalRootFindingInput,
    EnvironmentSummary,
    ExecutionOptions,
    ExperimentSummary,
    ResultSuccessData,
    SuccessResultPayload,
    ValidationStatusCounts,
    VariableNode,
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
    ValidationStatus,
)
from modeling_core.ports.project_store import (
    BeginRunCommand,
    BeginRunResult,
    BeginValidationCommand,
    BeginValidationResult,
    CompleteAttemptCommand,
    CompleteValidationCommand,
    CreateProjectCommand,
    ExperimentTrace,
    ExperimentTraceQuery,
    ProjectStatusSnapshot,
    ProjectStoreError,
    ProjectWriteResult,
    StoredRunResult,
    StoredValidationResult,
    ValidationSource,
    WriteOperation,
)
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import bootstrap_storage


EXPECTED_TABLES = {
    "metadata",
    "projects",
    "experiments",
    "attempts",
    "result_snapshots",
    "validations",
    "idempotency_records",
}

REQUIRED_COLUMNS = {
    "metadata": {"key", "value"},
    "projects": {
        "project_id",
        "storage_instance_id",
        "project_format_version",
        "display_name",
        "created_at",
    },
    "experiments": {
        "experiment_id",
        "project_id",
        "capability_id",
        "contract_version",
        "canonical_input_schema_version",
        "canonical_payload",
        "canonical_payload_hash",
        "model_snapshot_hash",
        "data_snapshot_references",
        "data_snapshot_set_hash",
        "execution_policy",
        "created_at",
    },
    "attempts": {
        "attempt_id",
        "experiment_id",
        "implementation_id",
        "implementation_version",
        "environment_summary",
        "randomness",
        "seed",
        "session_id",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "warnings",
        "system_error",
        "numerical_failure",
        "terminal_reason",
    },
    "result_snapshots": {
        "result_snapshot_id",
        "attempt_id",
        "result_kind",
        "result_schema_version",
        "result_hash",
        "result_payload_json",
    },
    "validations": {
        "validation_id",
        "attempt_id",
        "expected_result_hash",
        "result_hash",
        "validator_id",
        "validator_implementation_id",
        "validator_implementation_version",
        "policy_version",
        "policy",
        "policy_hash",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "outcome",
        "metrics",
        "validation_report_hash",
        "report_payload_json",
        "operational_error",
        "terminal_reason",
    },
    "idempotency_records": {
        "scope_id",
        "tool_name",
        "operation_id",
        "canonical_request_hash",
        "status",
        "result_entity_references",
    },
}

NOW = datetime(2026, 7, 17, tzinfo=UTC)
PROJECT_ID = "00000000-0000-4000-8000-000000000001"
STORAGE_ID = "00000000-0000-4000-8000-000000000002"
EXPERIMENT_ID = "00000000-0000-4000-8000-000000000003"
ATTEMPT_ID = "00000000-0000-4000-8000-000000000004"
RESULT_ID = "00000000-0000-4000-8000-000000000005"
VALIDATION_ID = "00000000-0000-4000-8000-000000000006"
SESSION_ID = "00000000-0000-4000-8000-000000000007"
OPERATION_ID = "00000000-0000-4000-8000-000000000008"
OTHER_ID = "00000000-0000-4000-8000-000000000009"
HASH = "sha256:" + "0" * 64


def _project() -> Project:
    return Project(
        project_id=PROJECT_ID,
        storage_instance_id=STORAGE_ID,
        project_format_version="modeling-project/0.1.0",
        display_name="example",
        created_at=NOW,
    )


def _experiment(
    *, project_id: str = PROJECT_ID, experiment_id: str = EXPERIMENT_ID
) -> Experiment:
    return Experiment(
        experiment_id=experiment_id,
        project_id=project_id,
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        canonical_input_schema_version=(
            "numerical.root_finding.canonical-input/0.1.0"
        ),
        canonical_payload=CanonicalRootFindingInput(
            canonical_input_schema_version=(
                "numerical.root_finding.canonical-input/0.1.0"
            ),
            expression_ast=VariableNode(kind="variable", name="x"),
            lower=-1.0,
            upper=1.0,
            absolute_tolerance=1e-10,
            relative_tolerance=1e-10,
            function_tolerance=1e-10,
            max_iterations=100,
        ),
        canonical_payload_hash=HASH,
        model_snapshot_hash=HASH,
        data_snapshot_references=(),
        data_snapshot_set_hash=HASH,
        execution_policy=ExecutionOptions(timeout_ms=10_000, seed=None),
        created_at=NOW,
    )


def _result(*, attempt_id: str = ATTEMPT_ID) -> ResultSnapshot:
    payload = SuccessResultPayload(
        result_schema_version="modeling-result/0.1.0",
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        result_kind="success",
        data=ResultSuccessData(
            root=0.0,
            function_value=0.0,
            iterations=1,
            evaluations=3,
            termination_reason="residual_tolerance",
        ),
    )
    return ResultSnapshot(
        result_snapshot_id=RESULT_ID,
        attempt_id=attempt_id,
        result_kind=ResultKind.SUCCESS,
        result_schema_version="modeling-result/0.1.0",
        result_hash=HASH,
        result_payload=payload,
    )


def _attempt(
    *,
    attempt_id: str = ATTEMPT_ID,
    experiment_id: str = EXPERIMENT_ID,
    status: AttemptStatus = AttemptStatus.PENDING,
    result_attempt_id: str = ATTEMPT_ID,
) -> Attempt:
    fields: dict[str, object] = {
        "attempt_id": attempt_id,
        "experiment_id": experiment_id,
        "implementation_id": "root-finding",
        "implementation_version": "0.1.0",
        "environment_summary": EnvironmentSummary(
            python_version="3.11.14",
            application_version="0.1.0",
            lock_hash=HASH,
        ),
        "randomness": "not_used",
        "seed": None,
        "session_id": SESSION_ID,
        "status": status,
        "created_at": NOW,
    }
    if status is AttemptStatus.SUCCEEDED:
        fields.update(
            started_at=NOW,
            finished_at=NOW,
            result=_result(attempt_id=result_attempt_id),
        )
    elif status is AttemptStatus.ABANDONED:
        fields.update(
            finished_at=NOW,
            terminal_reason=TerminalReason.HOST_CANCELLED,
        )
    return Attempt(**fields)


def _validation(
    *,
    validation_id: str = VALIDATION_ID,
    attempt_id: str = ATTEMPT_ID,
    status: ValidationStatus = ValidationStatus.PENDING,
) -> Validation:
    fields: dict[str, object] = {
        "validation_id": validation_id,
        "attempt_id": attempt_id,
        "expected_result_hash": HASH,
        "result_hash": HASH,
        "validator_id": "numerical.root_finding.residual",
        "validator_implementation_id": "residual",
        "validator_implementation_version": "0.1.0",
        "policy_version": "0.1.0",
        "policy": {},
        "policy_hash": HASH,
        "status": status,
        "created_at": NOW,
    }
    if status is ValidationStatus.ABANDONED:
        fields.update(
            finished_at=NOW,
            terminal_reason=TerminalReason.HOST_CANCELLED,
        )
    return Validation(**fields)


def _operation() -> WriteOperation:
    return WriteOperation(
        operation_id=OPERATION_ID,
        canonical_request_hash=HASH,
    )


def _counts() -> tuple[AttemptStatusCounts, ValidationStatusCounts]:
    return (
        AttemptStatusCounts(
            pending=0,
            running=0,
            succeeded=0,
            numerical_failure=0,
            errored=0,
            timed_out=0,
            abandoned=0,
        ),
        ValidationStatusCounts(
            pending=0,
            running=0,
            succeeded=0,
            errored=0,
            timed_out=0,
            abandoned=0,
        ),
    )


def _summary(
    experiment_id: str = EXPERIMENT_ID,
    created_at: str = "2026-07-17T00:00:00.000Z",
) -> ExperimentSummary:
    return ExperimentSummary(
        experiment_id=experiment_id,
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        created_at=created_at,
        attempt_count=1,
        latest_attempt_id=ATTEMPT_ID,
        latest_attempt_status="PENDING",
        latest_attempt_at=created_at,
        validation_count=0,
    )


def _database(project_root: Path) -> Path:
    return project_root / ".modeling" / "state.sqlite3"


def test_schema_one_has_required_tables_columns_foreign_keys_and_unique_key(
    tmp_path: Path,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())

    with closing(sqlite3.connect(_database(tmp_path))) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert tables == EXPECTED_TABLES

        for table, expected_columns in REQUIRED_COLUMNS.items():
            actual_columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            assert expected_columns <= actual_columns

        foreign_keys = {
            table: {
                (row[2], row[3], row[4])
                for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            }
            for table in (
                "experiments",
                "attempts",
                "result_snapshots",
                "validations",
            )
        }
        assert foreign_keys == {
            "experiments": {("projects", "project_id", "project_id")},
            "attempts": {("experiments", "experiment_id", "experiment_id")},
            "result_snapshots": {("attempts", "attempt_id", "attempt_id")},
            "validations": {("attempts", "attempt_id", "attempt_id")},
        }

        indexes = connection.execute("PRAGMA index_list(idempotency_records)").fetchall()
        unique_columns = {
            tuple(
                row[2]
                for row in connection.execute(f"PRAGMA index_info({index[1]})")
            )
            for index in indexes
            if index[2] == 1
        }
        assert ("scope_id", "tool_name", "operation_id") in unique_columns


def test_schema_constraints_reject_invalid_entity_ids_and_hashes(
    tmp_path: Path,
) -> None:
    metadata = bootstrap_storage(tmp_path, VersionSet.m1a())

    with closing(sqlite3.connect(_database(tmp_path))) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO projects (
                    project_id, storage_instance_id, project_format_version,
                    display_name, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "invalid",
                    metadata.storage_instance_id,
                    "modeling-project/0.1.0",
                    "bad id",
                    "2026-07-17T00:00:00.000Z",
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO idempotency_records (
                    scope_id, tool_name, operation_id, canonical_request_hash,
                    status, result_entity_references
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    metadata.storage_instance_id,
                    "create_project",
                    "00000000-0000-4000-8000-000000000001",
                    "not-a-hash",
                    "COMPLETED",
                    "{}",
                ),
            )


def test_storage_ready_has_no_project_domain_row(tmp_path: Path) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    store = SQLiteProjectStore(tmp_path, VersionSet.m1a())

    inspection = store.inspect_project_state()

    assert inspection.state is ProjectState.STORAGE_READY
    assert inspection.project is None
    with closing(sqlite3.connect(_database(tmp_path))) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (0,)


def test_project_metadata_matches_the_shipped_draft_2020_12_schema(
    tmp_path: Path,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    schema_path = (
        Path(__file__).parents[2]
        / "src"
        / "modeling_core"
        / "contracts"
        / "schemas"
        / "common"
        / "0.1.0"
        / "modeling-project.schema.json"
    )
    instance_path = tmp_path / ".modeling" / "project.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    instance = json.loads(instance_path.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(instance)


def test_write_operation_and_create_project_contracts_are_strict_and_frozen() -> None:
    operation = _operation()
    command = CreateProjectCommand(
        operation=operation,
        display_name="Café",
    )
    result = ProjectWriteResult(
        project=_project(),
        created=True,
        replayed=False,
    )

    assert command.operation == operation
    assert result.project == _project()
    with pytest.raises(FrozenInstanceError):
        command.display_name = "other"  # type: ignore[misc]
    with pytest.raises((ValidationError, ValueError)):
        WriteOperation(operation_id="invalid", canonical_request_hash=HASH)
    with pytest.raises((ValidationError, ValueError)):
        WriteOperation(
            operation_id=OPERATION_ID,
            canonical_request_hash="not-a-hash",
        )
    for display_name in ("", "x" * 129, "Cafe\u0301"):
        with pytest.raises((ValidationError, ValueError)):
            CreateProjectCommand(
                operation=operation,
                display_name=display_name,
            )


@pytest.mark.parametrize(
    "timestamp",
    [
        datetime(2026, 7, 17),
        datetime(2026, 7, 17, tzinfo=UTC) + timedelta(microseconds=1),
        datetime(2026, 7, 17, tzinfo=timezone(timedelta(hours=8))),
    ],
)
def test_project_status_requires_utc_millisecond_datetime(
    timestamp: datetime,
) -> None:
    attempts, validations = _counts()
    with pytest.raises(ValueError, match="timestamp"):
        ProjectStatusSnapshot(
            project=_project(),
            attempt_status_counts=attempts,
            validation_status_counts=validations,
            last_activity_at=timestamp,
            experiments=(),
            truncated=False,
        )


def test_project_status_limits_and_orders_immutable_experiment_summaries() -> None:
    attempts, validations = _counts()
    newest = _summary(
        "00000000-0000-4000-8000-000000000011",
        "2026-07-18T00:00:00.000Z",
    )
    high_id = _summary(
        "00000000-0000-4000-8000-000000000012",
        "2026-07-17T00:00:00.000Z",
    )
    low_id = _summary(
        "00000000-0000-4000-8000-000000000010",
        "2026-07-17T00:00:00.000Z",
    )
    snapshot = ProjectStatusSnapshot(
        project=_project(),
        attempt_status_counts=attempts,
        validation_status_counts=validations,
        last_activity_at=NOW,
        experiments=(newest, high_id, low_id),
        truncated=False,
    )
    assert snapshot.experiments == (newest, high_id, low_id)
    with pytest.raises((ValidationError, ValueError)):
        ProjectStatusSnapshot(
            project=_project(),
            attempt_status_counts=attempts,
            validation_status_counts=validations,
            last_activity_at=NOW,
            experiments=(low_id, newest),
            truncated=False,
        )
    with pytest.raises((ValidationError, ValueError)):
        ProjectStatusSnapshot(
            project=_project(),
            attempt_status_counts=attempts,
            validation_status_counts=validations,
            last_activity_at=NOW,
            experiments=tuple(
                _summary(
                    f"00000000-0000-4000-8000-{index:012d}",
                    f"2026-07-{index + 1:02d}T00:00:00.000Z",
                )
                for index in range(21)
            ),
            truncated=True,
        )


def test_run_commands_require_parent_consistency_pending_and_terminal_states() -> None:
    experiment = _experiment()
    pending = _attempt()
    terminal = _attempt(status=AttemptStatus.ABANDONED)

    assert BeginRunCommand(
        operation=_operation(), experiment=experiment, attempt=pending
    ).attempt is pending
    assert BeginRunResult(
        experiment=experiment, attempt=pending, replayed=False
    ).replayed is False
    assert BeginRunResult(
        experiment=experiment, attempt=terminal, replayed=True
    ).replayed is True
    assert CompleteAttemptCommand(
        operation=_operation(), attempt=terminal
    ).attempt is terminal
    assert StoredRunResult(attempt=terminal).attempt is terminal

    with pytest.raises(ValueError):
        BeginRunCommand(
            operation=_operation(),
            experiment=experiment,
            attempt=_attempt(experiment_id=OTHER_ID),
        )
    with pytest.raises(ValueError):
        BeginRunCommand(
            operation=_operation(),
            experiment=experiment,
            attempt=terminal,
        )
    with pytest.raises(ValueError):
        BeginRunResult(
            experiment=experiment,
            attempt=terminal,
            replayed=False,
        )
    with pytest.raises(ValueError):
        BeginRunResult(
            experiment=experiment,
            attempt=pending,
            replayed=True,
        )
    with pytest.raises(ValueError):
        CompleteAttemptCommand(
            operation=_operation(),
            attempt=pending,
        )
    with pytest.raises(ValueError):
        StoredRunResult(attempt=pending)


def test_validation_source_requires_owned_success_result() -> None:
    experiment = _experiment()
    succeeded = _attempt(status=AttemptStatus.SUCCEEDED)
    source = ValidationSource(experiment=experiment, attempt=succeeded)
    assert source.attempt is succeeded

    for invalid in (
        _attempt(),
        _attempt(status=AttemptStatus.ABANDONED),
        _attempt(
            experiment_id=OTHER_ID,
            status=AttemptStatus.SUCCEEDED,
        ),
        _attempt(
            status=AttemptStatus.SUCCEEDED,
            result_attempt_id=OTHER_ID,
        ),
    ):
        with pytest.raises(ValueError):
            ValidationSource(experiment=experiment, attempt=invalid)


def test_validation_commands_enforce_pending_replay_and_terminal_states() -> None:
    pending = _validation()
    terminal = _validation(status=ValidationStatus.ABANDONED)

    assert BeginValidationCommand(
        operation=_operation(), validation=pending
    ).validation is pending
    assert BeginValidationResult(
        validation=pending, replayed=False
    ).replayed is False
    assert BeginValidationResult(
        validation=terminal, replayed=True
    ).replayed is True
    assert CompleteValidationCommand(
        operation=_operation(), validation=terminal
    ).validation is terminal
    assert StoredValidationResult(validation=terminal).validation is terminal

    with pytest.raises(ValueError):
        BeginValidationCommand(
            operation=_operation(), validation=terminal
        )
    with pytest.raises(ValueError):
        BeginValidationResult(validation=terminal, replayed=False)
    with pytest.raises(ValueError):
        BeginValidationResult(validation=pending, replayed=True)
    with pytest.raises(ValueError):
        CompleteValidationCommand(
            operation=_operation(), validation=pending
        )
    with pytest.raises(ValueError):
        StoredValidationResult(validation=pending)


@pytest.mark.parametrize(
    "factory",
    [
        lambda experiment, attempt: BeginRunResult(
            experiment=experiment, attempt=attempt, replayed=True
        ),
        lambda _experiment, attempt: CompleteAttemptCommand(
            operation=_operation(), attempt=attempt
        ),
        lambda _experiment, attempt: StoredRunResult(attempt=attempt),
        lambda experiment, attempt: ValidationSource(
            experiment=experiment, attempt=attempt
        ),
        lambda experiment, attempt: ExperimentTrace(
            project=_project(),
            experiment=experiment,
            attempts=(attempt,),
            validations=(),
        ),
    ],
)
def test_every_attempt_dto_rejects_mismatched_embedded_result_owner(
    factory: object,
) -> None:
    experiment = _experiment()
    mismatched = _attempt(
        status=AttemptStatus.SUCCEEDED,
        result_attempt_id=OTHER_ID,
    )
    with pytest.raises(ValueError, match="result"):
        factory(experiment, mismatched)  # type: ignore[operator]


def test_trace_query_and_trace_enforce_all_parent_and_uniqueness_relations() -> None:
    project = _project()
    experiment = _experiment()
    attempt = _attempt()
    validation = _validation()
    query = ExperimentTraceQuery(
        project_id=PROJECT_ID,
        experiment_id=EXPERIMENT_ID,
    )
    trace = ExperimentTrace(
        project=project,
        experiment=experiment,
        attempts=(attempt,),
        validations=(validation,),
    )
    assert query.project_id == project.project_id
    assert trace.attempts == (attempt,)
    assert trace.validations == (validation,)

    invalid_arguments = (
        {
            "project": project,
            "experiment": _experiment(project_id=OTHER_ID),
            "attempts": (),
            "validations": (),
        },
        {
            "project": project,
            "experiment": experiment,
            "attempts": (_attempt(experiment_id=OTHER_ID),),
            "validations": (),
        },
        {
            "project": project,
            "experiment": experiment,
            "attempts": (attempt, attempt),
            "validations": (),
        },
        {
            "project": project,
            "experiment": experiment,
            "attempts": (attempt,),
            "validations": (_validation(attempt_id=OTHER_ID),),
        },
        {
            "project": project,
            "experiment": experiment,
            "attempts": (attempt,),
            "validations": (validation, validation),
        },
    )
    for arguments in invalid_arguments:
        with pytest.raises(ValueError):
            ExperimentTrace(**arguments)


def test_project_store_error_is_validated_deep_immutable_and_retryable_only_for_transients() -> None:
    source_details = {
        "conflict_type": "operation_in_progress",
        "nested": {"items": [1]},
    }
    error = ProjectStoreError(
        code="CONFLICT",
        message="operation still running",
        retryable=True,
        details=source_details,
    )
    source_details["nested"]["items"].append(2)  # type: ignore[index,union-attr]
    exposed = error.details
    exposed["conflict_type"] = "changed"

    assert isinstance(error, Exception)
    assert str(error) == "operation still running"
    assert error.code == "CONFLICT"
    assert error.retryable is True
    assert error.details == {
        "conflict_type": "operation_in_progress",
        "nested": {"items": [1]},
    }
    with pytest.raises((AttributeError, FrozenInstanceError)):
        error.code = "INTERNAL_ERROR"  # type: ignore[misc]

    invalid_arguments = (
        {"code": "UNKNOWN", "message": "x", "retryable": False, "details": {}},
        {"code": "CONFLICT", "message": "", "retryable": False, "details": {}},
        {"code": "CONFLICT", "message": "x", "retryable": 1, "details": {}},
        {"code": "CONFLICT", "message": "x", "retryable": False, "details": []},
        {
            "code": "CONFLICT",
            "message": "x",
            "retryable": False,
            "details": {"value": float("inf")},
        },
        {
            "code": "CONFLICT",
            "message": "x",
            "retryable": True,
            "details": {"conflict_type": "idempotency_mismatch"},
        },
        {
            "code": "INTERNAL_ERROR",
            "message": "x",
            "retryable": True,
            "details": {},
        },
    )
    for arguments in invalid_arguments:
        with pytest.raises((TypeError, ValueError, ValidationError)):
            ProjectStoreError(**arguments)
