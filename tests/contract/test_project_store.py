from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import closing, contextmanager
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
    LegacyAttempt,
    LegacyIdempotencyRecord,
    LegacyValidation,
    ProjectStatusSnapshot,
    ProjectStoreError,
    ProjectStateInspection,
    ProjectWriteResult,
    StoreIntegrityCheck,
    StoreIntegrityReport,
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
        canonical_input_schema_version=("numerical.root_finding.canonical-input/0.1.0"),
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

        indexes = connection.execute(
            "PRAGMA index_list(idempotency_records)"
        ).fetchall()
        unique_columns = {
            tuple(
                row[2] for row in connection.execute(f"PRAGMA index_info({index[1]})")
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

    assert (
        BeginRunCommand(
            operation=_operation(), experiment=experiment, attempt=pending
        ).attempt
        is pending
    )
    assert (
        BeginRunResult(experiment=experiment, attempt=pending, replayed=False).replayed
        is False
    )
    assert (
        BeginRunResult(experiment=experiment, attempt=terminal, replayed=True).replayed
        is True
    )
    assert (
        CompleteAttemptCommand(operation=_operation(), attempt=terminal).attempt
        is terminal
    )
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

    assert (
        BeginValidationCommand(operation=_operation(), validation=pending).validation
        is pending
    )
    assert BeginValidationResult(validation=pending, replayed=False).replayed is False
    assert BeginValidationResult(validation=terminal, replayed=True).replayed is True
    assert (
        CompleteValidationCommand(
            operation=_operation(), validation=terminal
        ).validation
        is terminal
    )
    assert StoredValidationResult(validation=terminal).validation is terminal

    with pytest.raises(ValueError):
        BeginValidationCommand(operation=_operation(), validation=terminal)
    with pytest.raises(ValueError):
        BeginValidationResult(validation=terminal, replayed=False)
    with pytest.raises(ValueError):
        BeginValidationResult(validation=pending, replayed=True)
    with pytest.raises(ValueError):
        CompleteValidationCommand(operation=_operation(), validation=pending)
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


def test_project_store_error_is_validated_deep_immutable_and_retryable_only_for_transients() -> (
    None
):
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


def _entity_id(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012d}"


class _Rows:
    def __init__(
        self,
        rows: Sequence[object],
        *,
        forbid_fetchall: bool = False,
    ) -> None:
        self._rows = tuple(rows)
        self._forbid_fetchall = forbid_fetchall

    def fetchall(self) -> list[object]:
        if self._forbid_fetchall:
            raise AssertionError("foreign-key inspection must use bounded fetchone")
        return list(self._rows)

    def fetchone(self) -> object | None:
        return self._rows[0] if self._rows else None


class _IntegrityConnection:
    def __init__(
        self,
        *,
        check_rows: Sequence[object] | BaseException = (("ok",),),
        attempts: Sequence[object] | BaseException = (),
        validations: Sequence[object] | BaseException = (),
        operations: Sequence[object] | BaseException = (),
        foreign_keys: Sequence[object] | BaseException = (),
        forbid_foreign_key_fetchall: bool = False,
    ) -> None:
        self._check_rows = check_rows
        self._attempts = attempts
        self._validations = validations
        self._operations = operations
        self._foreign_keys = foreign_keys
        self._forbid_foreign_key_fetchall = forbid_foreign_key_fetchall
        self.statements: list[str] = []

    def execute(self, statement: str) -> _Rows:
        normalized = " ".join(statement.split())
        self.statements.append(normalized)
        if normalized in {"PRAGMA quick_check", "PRAGMA integrity_check"}:
            rows = self._check_rows
        elif normalized == "PRAGMA foreign_key_check":
            rows = self._foreign_keys
        elif "FROM attempts" in normalized:
            rows = self._attempts
        elif "FROM validations" in normalized:
            rows = self._validations
        elif "FROM idempotency_records" in normalized:
            rows = self._operations
        else:
            raise AssertionError(f"unexpected integrity SQL: {normalized}")
        if isinstance(rows, BaseException):
            raise rows
        return _Rows(
            rows,
            forbid_fetchall=(
                normalized == "PRAGMA foreign_key_check"
                and self._forbid_foreign_key_fetchall
            ),
        )


class _CloseFailingIntegrityConnection(_IntegrityConnection):
    def close(self) -> None:
        raise sqlite3.DatabaseError("sensitive close failure")


def _inspection_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    connection: _IntegrityConnection,
) -> SQLiteProjectStore:
    store = SQLiteProjectStore(tmp_path, VersionSet.m1a())
    monkeypatch.setattr(
        store,
        "inspect_project_state",
        lambda: ProjectStateInspection(state=ProjectState.STORAGE_READY),
    )

    @contextmanager
    def fake_read() -> Iterator[_IntegrityConnection]:
        yield connection

    monkeypatch.setattr(store, "_read", fake_read)
    return store


def test_integrity_report_dtos_are_finite_unique_bounded_and_utf8_ordered() -> None:
    attempts = tuple(
        LegacyAttempt(
            attempt_id=_entity_id(index),
            status="PENDING" if index <= 50 else "RUNNING",
        )
        for index in range(1, 101)
    )
    validations = tuple(
        LegacyValidation(
            validation_id=_entity_id(index + 200),
            status="PENDING" if index <= 50 else "RUNNING",
        )
        for index in range(1, 101)
    )
    operations = tuple(
        LegacyIdempotencyRecord(
            scope_id=_entity_id(index + 400),
            tool_name=("run_experiment" if index % 2 == 0 else "validate_experiment"),
            operation_id=_entity_id(index + 600),
            status="IN_PROGRESS",
        )
        for index in range(1, 101)
    )
    report = StoreIntegrityReport(
        state=ProjectState.DEGRADED,
        issues=("database_relation", "stale_attempt"),
        check=StoreIntegrityCheck(mode="quick", outcome="PASS"),
        legacy_attempts=attempts,
        legacy_validations=validations,
        legacy_idempotency_records=operations,
    )

    assert report.legacy_attempts == attempts
    assert report.legacy_validations == validations
    assert report.legacy_idempotency_records == operations
    with pytest.raises(FrozenInstanceError):
        report.state = ProjectState.READY  # type: ignore[misc]
    frozen_children = (
        (report.check, "outcome", "FAIL"),
        (attempts[0], "status", "RUNNING"),
        (validations[0], "status", "RUNNING"),
        (operations[0], "status", "COMPLETED"),
    )
    for child, attribute, replacement in frozen_children:
        with pytest.raises(FrozenInstanceError):
            setattr(child, attribute, replacement)

    invalid_factories = (
        lambda: StoreIntegrityCheck(mode="fast", outcome="PASS"),
        lambda: StoreIntegrityCheck(mode="quick", outcome="UNKNOWN"),
        lambda: LegacyAttempt(
            attempt_id="AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
            status="PENDING",
        ),
        lambda: LegacyAttempt(
            attempt_id="00000000-0000-1000-8000-000000000001",
            status="PENDING",
        ),
        lambda: LegacyAttempt(attempt_id=PROJECT_ID, status="SUCCEEDED"),
        lambda: LegacyValidation(validation_id="invalid", status="RUNNING"),
        lambda: LegacyValidation(validation_id=PROJECT_ID, status="SUCCEEDED"),
        lambda: LegacyIdempotencyRecord(
            scope_id="AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
            tool_name="run_experiment",
            operation_id=OPERATION_ID,
            status="IN_PROGRESS",
        ),
        lambda: LegacyIdempotencyRecord(
            scope_id="00000000-0000-1000-8000-000000000001",
            tool_name="run_experiment",
            operation_id=OPERATION_ID,
            status="IN_PROGRESS",
        ),
        lambda: LegacyIdempotencyRecord(
            scope_id=PROJECT_ID,
            tool_name="run_experiment",
            operation_id="AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA",
            status="IN_PROGRESS",
        ),
        lambda: LegacyIdempotencyRecord(
            scope_id=PROJECT_ID,
            tool_name="run_experiment",
            operation_id="00000000-0000-1000-8000-000000000001",
            status="IN_PROGRESS",
        ),
        lambda: LegacyIdempotencyRecord(
            scope_id=PROJECT_ID,
            tool_name="run_experiment",
            operation_id=OPERATION_ID,
            status="COMPLETED",
        ),
        lambda: LegacyIdempotencyRecord(
            scope_id=PROJECT_ID,
            tool_name="create_project",
            operation_id=OPERATION_ID,
            status="IN_PROGRESS",
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=["database_relation"],  # type: ignore[arg-type]
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=("stale_attempt", "database_relation"),
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=("database_relation", "database_relation"),
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_attempts=[attempts[0]],  # type: ignore[arg-type]
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_attempts=(attempts[1], attempts[0]),
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_attempts=(attempts[0], attempts[0]),
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_attempts=(
                attempts[0],
                LegacyAttempt(attempts[0].attempt_id, "RUNNING"),
            ),
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_attempts=attempts + (LegacyAttempt(_entity_id(101), "RUNNING"),),
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_validations=[validations[0]],  # type: ignore[arg-type]
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_validations=(validations[1], validations[0]),
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_validations=(validations[0], validations[0]),
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_validations=validations
            + (LegacyValidation(_entity_id(301), "RUNNING"),),
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_idempotency_records=[operations[0]],  # type: ignore[arg-type]
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_idempotency_records=(operations[1], operations[0]),
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_idempotency_records=(operations[0], operations[0]),
        ),
        lambda: StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=(),
            legacy_idempotency_records=operations
            + (
                LegacyIdempotencyRecord(
                    _entity_id(501),
                    "run_experiment",
                    _entity_id(701),
                    "IN_PROGRESS",
                ),
            ),
        ),
    )
    for factory in invalid_factories:
        with pytest.raises((TypeError, ValueError, ValidationError)):
            factory()


def test_inspect_integrity_selects_exact_check_and_reports_legacy_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @contextmanager
    def forbidden_read() -> Iterator[_IntegrityConnection]:
        raise AssertionError("terminal preflight state must not open SQLite")
        yield _IntegrityConnection()

    for state, expected_issues in (
        (ProjectState.UNINITIALIZED, ()),
        (ProjectState.DEGRADED, ("project_state",)),
    ):
        terminal_store = SQLiteProjectStore(tmp_path, VersionSet.m1a())
        monkeypatch.setattr(
            terminal_store,
            "inspect_project_state",
            lambda state=state: ProjectStateInspection(state=state),
        )
        monkeypatch.setattr(terminal_store, "_read", forbidden_read)
        terminal_report = terminal_store.inspect_integrity(deep=True)
        assert terminal_report.state is state
        assert terminal_report.issues == expected_issues
        assert terminal_report.check is None
        assert terminal_report.legacy_attempts == ()
        assert terminal_report.legacy_validations == ()
        assert terminal_report.legacy_idempotency_records == ()

    attempt_rows = [(_entity_id(1), "PENDING"), (_entity_id(2), "RUNNING")]
    validation_rows = [(_entity_id(3), "PENDING"), (_entity_id(4), "RUNNING")]
    operation_rows = [
        (_entity_id(5), "run_experiment", _entity_id(6), "IN_PROGRESS"),
        (_entity_id(7), "validate_experiment", _entity_id(8), "IN_PROGRESS"),
    ]
    quick_connection = _IntegrityConnection(
        attempts=attempt_rows,
        validations=validation_rows,
        operations=operation_rows,
        foreign_keys=[("validations", 1, "attempts", 0)],
    )
    quick_store = _inspection_store(tmp_path, monkeypatch, quick_connection)

    quick = quick_store.inspect_integrity(deep=False)

    assert quick.check == StoreIntegrityCheck(mode="quick", outcome="PASS")
    assert quick.issues == (
        "foreign_key",
        "stale_attempt",
        "stale_operation",
        "stale_validation",
    )
    assert quick.legacy_attempts == tuple(LegacyAttempt(*row) for row in attempt_rows)
    assert quick.legacy_validations == tuple(
        LegacyValidation(*row) for row in validation_rows
    )
    assert quick.legacy_idempotency_records == tuple(
        LegacyIdempotencyRecord(*row) for row in operation_rows
    )
    assert quick_connection.statements[0] == "PRAGMA quick_check"
    assert "PRAGMA integrity_check" not in quick_connection.statements

    deep_connection = _IntegrityConnection()
    deep_store = _inspection_store(tmp_path, monkeypatch, deep_connection)
    deep = deep_store.inspect_integrity(deep=True)
    assert deep.check == StoreIntegrityCheck(mode="integrity", outcome="PASS")
    assert deep_connection.statements[0] == "PRAGMA integrity_check"
    assert "PRAGMA quick_check" not in deep_connection.statements

    malformed_results = (
        [],
        [()],
        [7],
        [("ok",), ("ok",)],
        [("OK",)],
        [("ok", "extra")],
    )
    for deep, expected_mode, expected_issue in (
        (False, "quick", "sqlite_quick_check"),
        (True, "integrity", "sqlite_integrity_check"),
    ):
        for rows in malformed_results:
            connection = _IntegrityConnection(check_rows=rows)
            store = _inspection_store(tmp_path, monkeypatch, connection)
            report = store.inspect_integrity(deep=deep)
            assert report.check == StoreIntegrityCheck(
                mode=expected_mode, outcome="FAIL"
            )
            assert report.issues == (expected_issue,)

    error_connection = _IntegrityConnection(
        check_rows=sqlite3.DatabaseError("sensitive database text")
    )
    error_store = _inspection_store(tmp_path, monkeypatch, error_connection)
    error_report = error_store.inspect_integrity(deep=True)
    assert error_report.check == StoreIntegrityCheck(mode="integrity", outcome="ERROR")
    assert error_report.issues == ("database_relation",)

    bounded_fk_connection = _IntegrityConnection(
        foreign_keys=[("validations", 1, "attempts", 0)],
        forbid_foreign_key_fetchall=True,
    )
    bounded_fk_store = _inspection_store(tmp_path, monkeypatch, bounded_fk_connection)
    bounded_fk_report = bounded_fk_store.inspect_integrity(deep=False)
    assert bounded_fk_report.issues == ("foreign_key",)

    closing_connection = _CloseFailingIntegrityConnection(
        attempts=attempt_rows,
        validations=validation_rows,
        operations=operation_rows,
    )
    closing_store = SQLiteProjectStore(tmp_path, VersionSet.m1a())
    monkeypatch.setattr(
        closing_store,
        "inspect_project_state",
        lambda: ProjectStateInspection(state=ProjectState.STORAGE_READY),
    )
    monkeypatch.setattr(
        closing_store,
        "_connect",
        lambda *, named_rows=False: closing_connection,
    )
    closing_report = closing_store.inspect_integrity(deep=False)
    assert closing_report.check == StoreIntegrityCheck(mode="quick", outcome="ERROR")
    assert closing_report.issues == ("database_relation",)
    assert closing_report.legacy_attempts == ()
    assert closing_report.legacy_validations == ()
    assert closing_report.legacy_idempotency_records == ()

    foreign_key_root = tmp_path / "foreign-key"
    foreign_key_root.mkdir()
    bootstrap_storage(foreign_key_root, VersionSet.m1a())
    with closing(sqlite3.connect(_database(foreign_key_root))) as connection:
        connection.execute(
            """
            INSERT INTO attempts (
                attempt_id, experiment_id, implementation_id,
                implementation_version, environment_summary, randomness,
                seed, session_id, status, created_at, started_at, finished_at,
                warnings, system_error, numerical_failure, terminal_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _entity_id(900),
                _entity_id(901),
                "fixture",
                "0.1.0",
                "{}",
                "not_used",
                None,
                SESSION_ID,
                "SUCCEEDED",
                "2026-07-17T00:00:00.000Z",
                None,
                None,
                "[]",
                None,
                None,
                None,
            ),
        )
        connection.commit()
    foreign_key_report = SQLiteProjectStore(
        foreign_key_root, VersionSet.m1a()
    ).inspect_integrity(deep=False)
    assert foreign_key_report.check == StoreIntegrityCheck(mode="quick", outcome="PASS")
    assert foreign_key_report.issues == ("foreign_key",)


def test_legacy_overflow_empties_only_affected_relation_and_continues_others(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = [(_entity_id(index), "PENDING") for index in range(1, 102)]
    validations = [(_entity_id(index + 200), "RUNNING") for index in range(1, 101)]
    operations = [
        (
            _entity_id(index + 400),
            "run_experiment",
            _entity_id(index + 600),
            "IN_PROGRESS",
        )
        for index in range(1, 101)
    ]
    overflow_cases = (
        (
            _IntegrityConnection(
                attempts=attempts,
                validations=validations,
                operations=operations,
            ),
            ("database_relation", "stale_operation", "stale_validation"),
            (0, 100, 100),
        ),
        (
            _IntegrityConnection(
                attempts=attempts[:100],
                validations=validations + [(_entity_id(301), "RUNNING")],
                operations=operations,
            ),
            ("database_relation", "stale_attempt", "stale_operation"),
            (100, 0, 100),
        ),
        (
            _IntegrityConnection(
                attempts=attempts[:100],
                validations=validations,
                operations=operations
                + [
                    (
                        _entity_id(501),
                        "run_experiment",
                        _entity_id(701),
                        "IN_PROGRESS",
                    )
                ],
            ),
            ("database_relation", "stale_attempt", "stale_validation"),
            (100, 100, 0),
        ),
    )
    for connection, expected_issues, expected_lengths in overflow_cases:
        store = _inspection_store(tmp_path, monkeypatch, connection)
        overflow = store.inspect_integrity(deep=False)
        assert overflow.issues == expected_issues
        assert (
            len(overflow.legacy_attempts),
            len(overflow.legacy_validations),
            len(overflow.legacy_idempotency_records),
        ) == expected_lengths

    connection = overflow_cases[0][0]
    legacy_statements = [
        statement
        for statement in connection.statements
        if "FROM attempts" in statement
        or "FROM validations" in statement
        or "FROM idempotency_records" in statement
    ]
    assert all("COLLATE BINARY" in statement for statement in legacy_statements)
    assert all(statement.endswith("LIMIT 101") for statement in legacy_statements)

    bad_attempt = _IntegrityConnection(
        attempts=[("not-a-uuid", "PENDING")],
        validations=validations[:1],
        operations=[(_entity_id(700), "unknown_tool", _entity_id(701), "IN_PROGRESS")],
    )
    bad_store = _inspection_store(tmp_path, monkeypatch, bad_attempt)
    bad_report = bad_store.inspect_integrity(deep=True)
    assert bad_report.issues == ("database_relation", "stale_validation")
    assert bad_report.legacy_attempts == ()
    assert bad_report.legacy_validations == (LegacyValidation(*validations[0]),)
    assert bad_report.legacy_idempotency_records == ()
