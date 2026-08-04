from __future__ import annotations

import math
import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator

import pytest

from modeling_capabilities.root_finding.solver import (
    BisectionRootFindingCapability,
)
from modeling_capabilities.root_finding.validator import (
    ResidualRootFindingValidator,
)
from modeling_core.application import ModelingApplication
from modeling_core.contracts.capability import (
    ExecutionOutcome,
    ExecutionCancelled,
    ExecutionDeadlineExceeded,
    ExecutionResourceLimitExceeded,
)
from modeling_core.contracts.errors import ModelingError
from modeling_core.contracts.tools import (
    CapabilitySelection,
    CreateProjectRequest,
    EnvironmentSummary,
    ExecutionOptions,
    GetProjectStatusExperimentRequest,
    GetProjectStatusSummaryRequest,
    HealthCheckRequest,
    ListCapabilitiesContractRequest,
    ListCapabilitiesSummaryRequest,
    RootFindingInput,
    ResultSuccessData,
    SuccessResultPayload,
    RunExperimentErroredResult,
    RunExperimentNumericalFailureResult,
    RunExperimentRequest,
    RunExperimentStoppedResult,
    RunExperimentSucceededResult,
    ValidateExperimentRequest,
    ValidateExperimentErroredResult,
    ValidateExperimentSucceededResult,
    ValidationMetrics,
    ValidationReportPayload,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.ports.project_store import (
    CompleteAttemptCommand,
    CompleteValidationCommand,
    ProjectStoreError,
)
from modeling_core.registry import CapabilityRegistry
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import bootstrap_storage


class FakeClock:
    def __init__(self, start: datetime, monotonic_start: float = 0.0) -> None:
        self._now = start
        self._monotonic = monotonic_start

    def utc_now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds


class FixedIdGenerator:
    def __init__(self, values: Iterable[str]) -> None:
        self._values: Iterator[str] = iter(values)

    def new_uuid4(self) -> str:
        return next(self._values)


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


class _CommitFailingConnection:
    def __init__(self, connection: sqlite3.Connection) -> None:
        object.__setattr__(self, "_connection", connection)

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._connection, name, value)

    def execute(
        self, sql: str, parameters: object = ()
    ) -> sqlite3.Cursor:
        if sql == "COMMIT":
            raise sqlite3.OperationalError("injected final commit failure")
        return self._connection.execute(sql, parameters)  # type: ignore[arg-type]


class _CommitErrorConnection:
    def __init__(
        self, connection: sqlite3.Connection, error: sqlite3.OperationalError
    ) -> None:
        object.__setattr__(self, "_connection", connection)
        object.__setattr__(self, "_error", error)

    def __getattr__(self, name: str) -> object:
        return getattr(self._connection, name)

    def __setattr__(self, name: str, value: object) -> None:
        setattr(self._connection, name, value)

    def execute(
        self, sql: str, parameters: object = ()
    ) -> sqlite3.Cursor:
        if sql == "COMMIT":
            raise self._error
        return self._connection.execute(sql, parameters)  # type: ignore[arg-type]


def _uuid(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012x}"


def _build_application(
    project_root: Path,
    *,
    store: SQLiteProjectStore | None = None,
    bootstrap: bool = True,
    id_start: int = 100,
    clock_start: datetime | None = None,
) -> ModelingApplication:
    versions = VersionSet.m1a()
    if bootstrap:
        bootstrap_storage(project_root, versions)
    registry = CapabilityRegistry(versions)
    registry.register_capability(BisectionRootFindingCapability())
    registry.register_validator(ResidualRootFindingValidator())
    registry_summary = registry.seal(frozenset())
    return ModelingApplication(
        store=store or SQLiteProjectStore(project_root, versions),
        registry=registry,
        registry_summary=registry_summary,
        versions=versions,
        clock=FakeClock(clock_start or datetime(2026, 7, 17, tzinfo=UTC)),
        id_generator=FixedIdGenerator(
            _uuid(index) for index in range(id_start, id_start + 500)
        ),
        session_id=_uuid(90),
        environment_summary=EnvironmentSummary(
            python_version="3.11.14",
            application_version="0.1.0",
            lock_hash="sha256:" + ("1" * 64),
        ),
        cancellation=_NeverCancelled(),
        default_display_name="2022 A 问题一",
    )


def test_six_use_cases_reconstruct_a_validated_root_finding_trace(
    tmp_path: Path,
) -> None:
    """Catches a facade that skips a use case or loses committed provenance."""
    application = _build_application(tmp_path)

    health = application.health_check(HealthCheckRequest())
    assert health.status == "OK"
    assert health.project_state == "STORAGE_READY"

    created = application.create_project(
        CreateProjectRequest(
            operation_id=_uuid(1),
            display_name="2022 A 问题一",
        )
    )
    assert created.created is True
    assert created.replayed is False

    capabilities = application.list_capabilities(
        ListCapabilitiesSummaryRequest()
    )
    assert [item.capability_id for item in capabilities.capabilities] == [
        "numerical.root_finding"
    ]

    run = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(2),
            project_id=created.project_id,
            mode="new",
            capability=CapabilitySelection(
                capability_id="numerical.root_finding",
                contract_version="0.1.0",
            ),
            payload=RootFindingInput(
                expression="x*x - 2",
                lower=0.0,
                upper=2.0,
            ),
        )
    )
    assert isinstance(run, RunExperimentSucceededResult)
    assert run.replayed is False
    assert math.isclose(run.result_summary.root, math.sqrt(2.0), abs_tol=1e-9)

    validation = application.validate_experiment(
        ValidateExperimentRequest(
            operation_id=_uuid(3),
            project_id=created.project_id,
            attempt_id=run.attempt_id,
            expected_result_hash=run.result_hash,
            validator_id="numerical.root_finding.residual",
            policy_version="0.1.0",
            policy={},
        )
    )
    assert isinstance(validation, ValidateExperimentSucceededResult)
    assert validation.outcome == "PASSED"
    assert validation.replayed is False

    trace = application.get_project_status(
        GetProjectStatusExperimentRequest(
            project_id=created.project_id,
            view="experiment",
            experiment_id=run.experiment_id,
        )
    )
    assert trace.experiment.experiment_id == run.experiment_id
    assert [record.record_type for record in trace.trace] == [
        "attempt",
        "validation",
    ]
    assert trace.trace[0].attempt_id == run.attempt_id
    assert trace.trace[1].validation_id == validation.validation_id


def test_health_degrades_when_project_state_inspection_is_translated(
    tmp_path: Path,
) -> None:
    """Catches translated state-inspection failures escaping health_check."""
    application = _build_application(tmp_path)
    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DROP TABLE projects")
        connection.commit()

    health = application.health_check(HealthCheckRequest())

    assert health.status == "DEGRADED"
    assert health.project_state == "DEGRADED"
    assert health.ready_for_project_creation is False


def test_health_degrades_when_integrity_inspection_is_translated(
    tmp_path: Path,
) -> None:
    """Catches translated integrity-inspection failures escaping health_check."""
    application = _build_application(tmp_path)
    application.create_project(CreateProjectRequest(operation_id=_uuid(9)))
    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("DROP TABLE idempotency_records")
        connection.commit()

    health = application.health_check(HealthCheckRequest())

    assert health.status == "DEGRADED"
    assert health.project_state == "DEGRADED"
    assert health.ready_for_project_creation is False


def test_stale_active_state_degrades_health_and_refuses_new_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches writes that ignore durable stale Attempt/idempotency state."""
    versions = VersionSet.m1a()
    store = SQLiteProjectStore(tmp_path, versions)
    application = _build_application(tmp_path, store=store)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(10))
    )

    def leave_running_attempt(*_args: object, **_kwargs: object) -> object:
        raise ProjectStoreError(
            "INTEGRITY_FAILURE",
            "injected terminal persistence failure",
            False,
            {"subject": "database_relation"},
        )

    monkeypatch.setattr(store, "complete_attempt", leave_running_attempt)
    with pytest.raises(ModelingError):
        application.run_experiment(
            RunExperimentRequest(
                operation_id=_uuid(11),
                project_id=project.project_id,
                mode="new",
                capability=CapabilitySelection(
                    capability_id="numerical.root_finding",
                    contract_version="0.1.0",
                ),
                payload=RootFindingInput(
                    expression="x*x - 2",
                    lower=0.0,
                    upper=2.0,
                ),
            )
        )

    restarted = _build_application(
        tmp_path,
        store=SQLiteProjectStore(tmp_path, versions),
        bootstrap=False,
        id_start=300,
    )
    health = restarted.health_check(HealthCheckRequest())
    assert health.status == "DEGRADED"
    assert health.project_state == "DEGRADED"

    with pytest.raises(ModelingError) as list_error:
        restarted.list_capabilities(ListCapabilitiesSummaryRequest())
    assert list_error.value.response.code == "PRECONDITION_FAILED"

    with pytest.raises(ModelingError) as create_error:
        restarted.create_project(
            CreateProjectRequest(operation_id=_uuid(13))
        )
    assert create_error.value.response.code == "PRECONDITION_FAILED"

    with pytest.raises(ModelingError) as captured:
        restarted.run_experiment(
            RunExperimentRequest(
                operation_id=_uuid(12),
                project_id=project.project_id,
                mode="new",
                capability=CapabilitySelection(
                    capability_id="numerical.root_finding",
                    contract_version="0.1.0",
                ),
                payload=RootFindingInput(
                    expression="x - 1",
                    lower=0.0,
                    upper=2.0,
                ),
            )
        )
    assert captured.value.response.code == "PRECONDITION_FAILED"
    assert captured.value.response.details.model_dump(mode="json") == {
        "condition": "project_degraded",
        "current_state": "DEGRADED",
    }


def test_application_normalizes_realistic_clock_to_utc_milliseconds(
    tmp_path: Path,
) -> None:
    """Catches raw microsecond timestamps entering strict domain records."""
    application = _build_application(
        tmp_path,
        clock_start=datetime(2026, 7, 17, 1, 2, 3, 123456, tzinfo=UTC),
    )
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(20))
    )
    run = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(21),
            project_id=project.project_id,
            mode="new",
            capability=CapabilitySelection(
                capability_id="numerical.root_finding",
                contract_version="0.1.0",
            ),
            payload=RootFindingInput(
                expression="x*x - 2",
                lower=0.0,
                upper=2.0,
            ),
        )
    )
    assert isinstance(run, RunExperimentSucceededResult)
    trace = application.get_project_status(
        GetProjectStatusExperimentRequest(
            project_id=project.project_id,
            view="experiment",
            experiment_id=run.experiment_id,
        )
    )
    assert trace.experiment.created_at == "2026-07-17T01:02:03.123Z"
    assert trace.trace[0].created_at == "2026-07-17T01:02:03.123Z"


def test_create_replay_rejects_malformed_created_reference(
    tmp_path: Path,
) -> None:
    """Catches a corrupted replay flag being silently interpreted as false."""
    application = _build_application(tmp_path)
    request = CreateProjectRequest(
        operation_id=_uuid(30),
        display_name="replay-integrity",
    )
    created = application.create_project(request)
    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE idempotency_records SET result_entity_references=? "
            "WHERE tool_name='create_project' AND operation_id=?",
            (
                '{"created":"yes","project_id":"'
                + created.project_id
                + '"}',
                request.operation_id,
            ),
        )
        connection.commit()

    with pytest.raises(ModelingError) as captured:
        application.create_project(request)
    assert captured.value.response.code == "INTEGRITY_FAILURE", (
        captured.value.response.model_dump(mode="json")
    )
    assert captured.value.response.details.subject == "database_relation"


def test_run_replay_rejects_cross_experiment_references(
    tmp_path: Path,
) -> None:
    """Catches completed run refs that mix two valid provenance chains."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(40))
    )
    selection = CapabilitySelection(
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
    )
    first_request = RunExperimentRequest(
        operation_id=_uuid(41),
        project_id=project.project_id,
        mode="new",
        capability=selection,
        payload=RootFindingInput(
            expression="x*x - 2", lower=0.0, upper=2.0
        ),
    )
    second_request = RunExperimentRequest(
        operation_id=_uuid(42),
        project_id=project.project_id,
        mode="new",
        capability=selection,
        payload=RootFindingInput(
            expression="x - 1", lower=0.0, upper=2.0
        ),
    )
    first = application.run_experiment(first_request)
    second = application.run_experiment(second_request)
    assert isinstance(first, RunExperimentSucceededResult)
    assert isinstance(second, RunExperimentSucceededResult)

    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE idempotency_records SET result_entity_references=? "
            "WHERE tool_name='run_experiment' AND operation_id=?",
            (
                '{"attempt_id":"'
                + second.attempt_id
                + '","experiment_id":"'
                + first.experiment_id
                + '"}',
                first_request.operation_id,
            ),
        )
        connection.commit()

    with pytest.raises(ModelingError) as captured:
        application.run_experiment(first_request)
    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert captured.value.response.details.subject == "database_relation"


def test_run_replay_rejects_extra_response_reference_keys(
    tmp_path: Path,
) -> None:
    """Catches completed run refs accepting an ambiguous expanded shape."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(43))
    )
    request = RunExperimentRequest(
        operation_id=_uuid(44),
        project_id=project.project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        ),
        payload=RootFindingInput(
            expression="x*x - 2", lower=0.0, upper=2.0
        ),
    )
    first = application.run_experiment(request)
    assert isinstance(first, RunExperimentSucceededResult)

    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE idempotency_records SET result_entity_references=? "
            "WHERE tool_name='run_experiment' AND operation_id=?",
            (
                '{"attempt_id":"'
                + first.attempt_id
                + '","experiment_id":"'
                + first.experiment_id
                + '","unexpected":"reference"}',
                request.operation_id,
            ),
        )
        connection.commit()

    with pytest.raises(ModelingError) as captured:
        application.run_experiment(request)
    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert captured.value.response.details.subject == "database_relation"


def test_run_replay_rejects_missing_attempt_reference_as_integrity_failure(
    tmp_path: Path,
) -> None:
    """Catches a dangling COMPLETED reference being reported as user absence."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(45))
    )
    request = RunExperimentRequest(
        operation_id=_uuid(46),
        project_id=project.project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        ),
        payload=RootFindingInput(
            expression="x*x - 2", lower=0.0, upper=2.0
        ),
    )
    first = application.run_experiment(request)
    assert isinstance(first, RunExperimentSucceededResult)

    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "DELETE FROM result_snapshots WHERE attempt_id=?",
            (first.attempt_id,),
        )
        connection.execute(
            "DELETE FROM attempts WHERE attempt_id=?", (first.attempt_id,)
        )
        connection.commit()

    with pytest.raises(ModelingError) as captured:
        application.run_experiment(request)
    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert captured.value.response.details.subject == "database_relation"


def test_validation_replay_rejects_cross_attempt_reference(
    tmp_path: Path,
) -> None:
    """Catches a validation replay returning another Attempt's evidence."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(50))
    )
    selection = CapabilitySelection(
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
    )
    runs = []
    for operation, expression in ((_uuid(51), "x*x - 2"), (_uuid(52), "x - 1")):
        run = application.run_experiment(
            RunExperimentRequest(
                operation_id=operation,
                project_id=project.project_id,
                mode="new",
                capability=selection,
                payload=RootFindingInput(
                    expression=expression,
                    lower=0.0,
                    upper=2.0,
                ),
            )
        )
        assert isinstance(run, RunExperimentSucceededResult)
        runs.append(run)

    requests = []
    validations = []
    for operation, run in zip((_uuid(53), _uuid(54)), runs, strict=True):
        request = ValidateExperimentRequest(
            operation_id=operation,
            project_id=project.project_id,
            attempt_id=run.attempt_id,
            expected_result_hash=run.result_hash,
            validator_id="numerical.root_finding.residual",
            policy_version="0.1.0",
            policy={},
        )
        result = application.validate_experiment(request)
        assert isinstance(result, ValidateExperimentSucceededResult)
        requests.append(request)
        validations.append(result)

    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE idempotency_records SET result_entity_references=? "
            "WHERE tool_name='validate_experiment' AND operation_id=?",
            (
                '{"validation_id":"'
                + validations[1].validation_id
                + '"}',
                requests[0].operation_id,
            ),
        )
        connection.commit()

    with pytest.raises(ModelingError) as captured:
        application.validate_experiment(requests[0])
    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert captured.value.response.details.subject == "database_relation"


def test_run_terminal_commit_failure_rolls_back_and_degrades_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a failed final COMMIT returning or preserving a fake result."""
    versions = VersionSet.m1a()
    store = SQLiteProjectStore(tmp_path, versions)
    application = _build_application(tmp_path, store=store)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(60))
    )
    original_connect = store._connect
    original_complete = store.complete_attempt
    armed = False

    def connect(*, named_rows: bool = False) -> sqlite3.Connection:
        connection = original_connect(named_rows=named_rows)
        if not armed:
            return connection
        return _CommitFailingConnection(connection)  # type: ignore[return-value]

    def complete_with_failed_commit(command: object) -> object:
        nonlocal armed
        armed = True
        try:
            return original_complete(command)  # type: ignore[arg-type]
        finally:
            armed = False

    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr(store, "complete_attempt", complete_with_failed_commit)
    request = RunExperimentRequest(
        operation_id=_uuid(61),
        project_id=project.project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        ),
        payload=RootFindingInput(
            expression="x*x - 2", lower=0.0, upper=2.0
        ),
    )
    with pytest.raises(ModelingError) as captured:
        application.run_experiment(request)
    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert store.inspect_project_state().state.value == "DEGRADED"

    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM result_snapshots"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT status FROM idempotency_records "
            "WHERE tool_name='run_experiment' AND operation_id=?",
            (request.operation_id,),
        ).fetchone() == ("IN_PROGRESS",)


@pytest.mark.parametrize("sqlite_error", [sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED])
def test_terminal_busy_or_locked_commit_failure_degrades_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    sqlite_error: int,
) -> None:
    """A terminal SQLite contention failure must fail closed in memory."""
    versions = VersionSet.m1a()
    store = SQLiteProjectStore(tmp_path, versions)
    application = _build_application(tmp_path, store=store)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(62 + sqlite_error))
    )
    original_connect = store._connect
    original_complete = store.complete_attempt
    armed = False
    error = sqlite3.OperationalError("injected terminal contention")
    error.sqlite_errorcode = sqlite_error

    def connect(*, named_rows: bool = False) -> sqlite3.Connection:
        connection = original_connect(named_rows=named_rows)
        if not armed:
            return connection
        return _CommitErrorConnection(connection, error)  # type: ignore[return-value]

    def complete_with_failed_commit(command: object) -> object:
        nonlocal armed
        armed = True
        try:
            return original_complete(command)  # type: ignore[arg-type]
        finally:
            armed = False

    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr(store, "complete_attempt", complete_with_failed_commit)
    with pytest.raises(ModelingError) as captured:
        application.run_experiment(
            RunExperimentRequest(
                operation_id=_uuid(64 + sqlite_error),
                project_id=project.project_id,
                mode="new",
                capability=CapabilitySelection(
                    capability_id="numerical.root_finding",
                    contract_version="0.1.0",
                ),
                payload=RootFindingInput(
                    expression="x*x - 2", lower=0.0, upper=2.0
                ),
            )
        )

    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert store.inspect_project_state().state.value == "DEGRADED"


def test_terminal_connection_failure_is_translated_and_degrades_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches terminal connection setup errors escaping without fail-close."""
    versions = VersionSet.m1a()
    store = SQLiteProjectStore(tmp_path, versions)
    application = _build_application(tmp_path, store=store)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(66))
    )
    original_connect = store._connect
    original_complete = store.complete_attempt
    armed = False

    def connect(*, named_rows: bool = False) -> sqlite3.Connection:
        if armed:
            raise OSError("injected terminal connect failure")
        return original_connect(named_rows=named_rows)

    def complete_without_connection(command: object) -> object:
        nonlocal armed
        armed = True
        try:
            return original_complete(command)  # type: ignore[arg-type]
        finally:
            armed = False

    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr(store, "complete_attempt", complete_without_connection)
    with pytest.raises(ModelingError) as captured:
        application.run_experiment(
            RunExperimentRequest(
                operation_id=_uuid(67),
                project_id=project.project_id,
                mode="new",
                capability=CapabilitySelection(
                    capability_id="numerical.root_finding",
                    contract_version="0.1.0",
                ),
                payload=RootFindingInput(
                    expression="x*x - 2", lower=0.0, upper=2.0
                ),
            )
        )

    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert captured.value.response.details.subject == "database_relation"
    assert store.inspect_project_state().state.value == "DEGRADED"


def test_create_commit_failure_rolls_back_and_degrades_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches first-project COMMIT failure leaving a writable store."""
    versions = VersionSet.m1a()
    store = SQLiteProjectStore(tmp_path, versions)
    application = _build_application(
        tmp_path,
        store=store,
        bootstrap=False,
    )
    original_connect = store._connect

    def connect(*, named_rows: bool = False) -> sqlite3.Connection:
        return _CommitFailingConnection(
            original_connect(named_rows=named_rows)
        )  # type: ignore[return-value]

    monkeypatch.setattr(store, "_connect", connect)
    with pytest.raises(ModelingError) as captured:
        application.create_project(
            CreateProjectRequest(
                operation_id=_uuid(70),
                display_name="commit-failure",
            )
        )
    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert store.inspect_project_state().state.value == "DEGRADED"

    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM idempotency_records"
        ).fetchone() == (0,)


def test_validation_terminal_commit_failure_rolls_back_and_degrades_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches failed validation COMMIT publishing a fake report."""
    versions = VersionSet.m1a()
    store = SQLiteProjectStore(tmp_path, versions)
    application = _build_application(tmp_path, store=store)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(80))
    )
    run = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(81),
            project_id=project.project_id,
            mode="new",
            capability=CapabilitySelection(
                capability_id="numerical.root_finding",
                contract_version="0.1.0",
            ),
            payload=RootFindingInput(
                expression="x*x - 2", lower=0.0, upper=2.0
            ),
        )
    )
    assert isinstance(run, RunExperimentSucceededResult)
    original_connect = store._connect
    original_complete = store.complete_validation
    armed = False

    def connect(*, named_rows: bool = False) -> sqlite3.Connection:
        connection = original_connect(named_rows=named_rows)
        if not armed:
            return connection
        return _CommitFailingConnection(connection)  # type: ignore[return-value]

    def complete_with_failed_commit(command: object) -> object:
        nonlocal armed
        armed = True
        try:
            return original_complete(command)  # type: ignore[arg-type]
        finally:
            armed = False

    monkeypatch.setattr(store, "_connect", connect)
    monkeypatch.setattr(
        store, "complete_validation", complete_with_failed_commit
    )
    request = ValidateExperimentRequest(
        operation_id=_uuid(82),
        project_id=project.project_id,
        attempt_id=run.attempt_id,
        expected_result_hash=run.result_hash,
        validator_id="numerical.root_finding.residual",
        policy_version="0.1.0",
        policy={},
    )
    with pytest.raises(ModelingError) as captured:
        application.validate_experiment(request)
    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert store.inspect_project_state().state.value == "DEGRADED"

    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute(
            "SELECT status, report_payload_json FROM validations"
        ).fetchone() == ("RUNNING", None)
        assert connection.execute(
            "SELECT status FROM idempotency_records "
            "WHERE tool_name='validate_experiment' AND operation_id=?",
            (request.operation_id,),
        ).fetchone() == ("IN_PROGRESS",)


def test_corrupt_experiment_json_returns_stable_integrity_error(
    tmp_path: Path,
) -> None:
    """Catches raw SQLite/reconstruction errors escaping the store port."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(90))
    )
    run = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(91),
            project_id=project.project_id,
            mode="new",
            capability=CapabilitySelection(
                capability_id="numerical.root_finding",
                contract_version="0.1.0",
            ),
            payload=RootFindingInput(
                expression="x*x - 2", lower=0.0, upper=2.0
            ),
        )
    )
    assert isinstance(run, RunExperimentSucceededResult)
    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE experiments SET canonical_payload='[]' "
            "WHERE experiment_id=?",
            (run.experiment_id,),
        )
        connection.commit()

    with pytest.raises(ModelingError) as captured:
        application.get_project_status(
            GetProjectStatusExperimentRequest(
                project_id=project.project_id,
                view="experiment",
                experiment_id=run.experiment_id,
            )
        )
    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert captured.value.response.details.subject == "database_relation"


def test_corrupt_project_status_reconstruction_returns_stable_integrity_error(
    tmp_path: Path,
) -> None:
    """Catches status reconstruction leaking a stored timestamp error."""
    store = SQLiteProjectStore(tmp_path, VersionSet.m1a())
    application = _build_application(tmp_path, store=store)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(95))
    )
    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE projects SET created_at='2000-00-00T00:00:00.000Z' "
            "WHERE project_id=?",
            (project.project_id,),
        )
        connection.commit()

    with pytest.raises(ProjectStoreError) as captured:
        store.get_project_status(project.project_id)
    assert captured.value.code == "INTEGRITY_FAILURE"
    assert captured.value.details["subject"] == "database_relation"


def test_validation_source_corruption_returns_stable_integrity_error(
    tmp_path: Path,
) -> None:
    """Catches corrupt source provenance masquerading as ineligible validation."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(96))
    )
    run = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(97),
            project_id=project.project_id,
            mode="new",
            capability=CapabilitySelection(
                capability_id="numerical.root_finding",
                contract_version="0.1.0",
            ),
            payload=RootFindingInput(
                expression="x*x - 2", lower=0.0, upper=2.0
            ),
        )
    )
    assert isinstance(run, RunExperimentSucceededResult)
    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE experiments SET canonical_payload='[]' WHERE experiment_id=?",
            (run.experiment_id,),
        )
        connection.commit()

    with pytest.raises(ModelingError) as captured:
        application.validate_experiment(
            ValidateExperimentRequest(
                operation_id=_uuid(98),
                project_id=project.project_id,
                attempt_id=run.attempt_id,
                expected_result_hash=run.result_hash,
                validator_id="numerical.root_finding.residual",
                policy_version="0.1.0",
                policy={},
            )
        )
    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert captured.value.response.details.subject == "database_relation"
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM validations").fetchone() == (0,)


def test_create_project_bootstraps_true_uninitialized_storage_and_replays(
    tmp_path: Path,
) -> None:
    """Catches first-use creation that secretly requires prior bootstrap."""
    application = _build_application(tmp_path, bootstrap=False)
    initial = application.health_check(HealthCheckRequest())
    assert initial.project_state == "UNINITIALIZED"
    request = CreateProjectRequest(operation_id=_uuid(100))

    created = application.create_project(request)
    replayed = application.create_project(request)

    assert created.created is True
    assert created.replayed is False
    assert replayed.project_id == created.project_id
    assert replayed.created is True
    assert replayed.replayed is True
    with closing(sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (1,)


def test_completed_write_replay_is_side_effect_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches completed replay re-running math or duplicating provenance."""
    application = _build_application(tmp_path)
    create_request = CreateProjectRequest(operation_id=_uuid(110))
    project = application.create_project(create_request)
    run_request = RunExperimentRequest(
        operation_id=_uuid(111),
        project_id=project.project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        ),
        payload=RootFindingInput(
            expression="x*x - 2", lower=0.0, upper=2.0
        ),
    )
    run = application.run_experiment(run_request)
    assert isinstance(run, RunExperimentSucceededResult)
    validation_request = ValidateExperimentRequest(
        operation_id=_uuid(112),
        project_id=project.project_id,
        attempt_id=run.attempt_id,
        expected_result_hash=run.result_hash,
        validator_id="numerical.root_finding.residual",
        policy_version="0.1.0",
        policy={},
    )
    validation = application.validate_experiment(validation_request)
    assert isinstance(validation, ValidateExperimentSucceededResult)

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("completed replay executed mathematics")

    monkeypatch.setattr(BisectionRootFindingCapability, "execute", forbidden)
    monkeypatch.setattr(ResidualRootFindingValidator, "validate", forbidden)
    create_replay = application.create_project(create_request)
    run_replay = application.run_experiment(run_request)
    validation_replay = application.validate_experiment(validation_request)

    assert create_replay.replayed is True
    assert isinstance(run_replay, RunExperimentSucceededResult)
    assert run_replay.replayed is True
    assert run_replay.experiment_id == run.experiment_id
    assert run_replay.attempt_id == run.attempt_id
    assert isinstance(validation_replay, ValidateExperimentSucceededResult)
    assert validation_replay.replayed is True
    assert validation_replay.validation_id == validation.validation_id
    with closing(sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")) as connection:
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "projects",
                "experiments",
                "attempts",
                "result_snapshots",
                "validations",
                "idempotency_records",
            )
        )
    assert counts == (1, 1, 1, 1, 1, 3)


def test_write_idempotency_mismatch_fails_without_new_entities(
    tmp_path: Path,
) -> None:
    """Catches reused operation IDs silently accepting changed requests."""
    application = _build_application(tmp_path)
    create_operation = _uuid(120)
    project = application.create_project(
        CreateProjectRequest(
            operation_id=create_operation,
            display_name="idempotency-one",
        )
    )
    with pytest.raises(ModelingError) as create_error:
        application.create_project(
            CreateProjectRequest(
                operation_id=create_operation,
                display_name="idempotency-two",
            )
        )
    assert create_error.value.response.code == "CONFLICT"
    assert create_error.value.response.retryable is False
    assert create_error.value.response.details.conflict_type == "idempotency_mismatch"

    selection = CapabilitySelection(
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
    )
    run_operation = _uuid(121)
    run_request = RunExperimentRequest(
        operation_id=run_operation,
        project_id=project.project_id,
        mode="new",
        capability=selection,
        payload=RootFindingInput(
            expression="x*x - 2", lower=0.0, upper=2.0
        ),
    )
    run = application.run_experiment(run_request)
    assert isinstance(run, RunExperimentSucceededResult)
    with pytest.raises(ModelingError) as run_error:
        application.run_experiment(
            RunExperimentRequest(
                operation_id=run_operation,
                project_id=project.project_id,
                mode="new",
                capability=selection,
                payload=RootFindingInput(
                    expression="x - 1", lower=0.0, upper=2.0
                ),
            )
        )
    assert run_error.value.response.code == "CONFLICT"
    assert run_error.value.response.retryable is False
    assert run_error.value.response.details.conflict_type == "idempotency_mismatch"

    validation_operation = _uuid(122)
    validation_request = ValidateExperimentRequest(
        operation_id=validation_operation,
        project_id=project.project_id,
        attempt_id=run.attempt_id,
        expected_result_hash=run.result_hash,
        validator_id="numerical.root_finding.residual",
        policy_version="0.1.0",
        policy={},
        timeout_ms=10_000,
    )
    validation = application.validate_experiment(validation_request)
    assert isinstance(validation, ValidateExperimentSucceededResult)
    with pytest.raises(ModelingError) as validation_error:
        application.validate_experiment(
            validation_request.model_copy(update={"timeout_ms": 9_999})
        )
    assert validation_error.value.response.code == "CONFLICT"
    assert validation_error.value.response.retryable is False
    assert (
        validation_error.value.response.details.conflict_type
        == "idempotency_mismatch"
    )

    assert application.health_check(HealthCheckRequest()).project_state == "READY"
    with closing(sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")) as connection:
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "experiments",
                "attempts",
                "result_snapshots",
                "validations",
                "idempotency_records",
            )
        )
    assert counts == (1, 1, 1, 1, 3)


@pytest.mark.parametrize(
    ("payload", "execution", "expected_code"),
    [
        (
            RootFindingInput(expression="x", lower=2.0, upper=1.0),
            None,
            "INVALID_REQUEST",
        ),
        (
            RootFindingInput(
                expression="x.__class__", lower=0.0, upper=1.0
            ),
            None,
            "SECURITY_VIOLATION",
        ),
        (
            RootFindingInput(
                expression=(" " * 4096) + "x", lower=0.0, upper=1.0
            ),
            None,
            "RESOURCE_LIMIT_EXCEEDED",
        ),
        (
            RootFindingInput(expression="x", lower=0.0, upper=1.0),
            ExecutionOptions(timeout_ms=10_000, seed=7),
            "INVALID_REQUEST",
        ),
    ],
)
def test_pre_execution_rejections_leave_zero_provenance(
    tmp_path: Path,
    payload: RootFindingInput,
    execution: ExecutionOptions | None,
    expected_code: str,
) -> None:
    """Catches rejected input creating Experiment or Attempt evidence."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(130))
    )
    with pytest.raises(ModelingError) as captured:
        application.run_experiment(
            RunExperimentRequest(
                operation_id=_uuid(131),
                project_id=project.project_id,
                mode="new",
                capability=CapabilitySelection(
                    capability_id="numerical.root_finding",
                    contract_version="0.1.0",
                ),
                payload=payload,
                execution=execution,
            )
        )
    assert captured.value.response.code == expected_code

    with closing(sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")) as connection:
        counts = tuple(
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "experiments",
                "attempts",
                "result_snapshots",
                "validations",
            )
        )
        run_idempotency = connection.execute(
            "SELECT COUNT(*) FROM idempotency_records "
            "WHERE tool_name='run_experiment'"
        ).fetchone()
    assert counts == (0, 0, 0, 0)
    assert run_idempotency == (0,)


def test_expected_result_hash_mismatch_creates_no_validation(
    tmp_path: Path,
) -> None:
    """Catches validation evidence created before result integrity checks."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(140))
    )
    run = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(141),
            project_id=project.project_id,
            mode="new",
            capability=CapabilitySelection(
                capability_id="numerical.root_finding",
                contract_version="0.1.0",
            ),
            payload=RootFindingInput(
                expression="x*x - 2", lower=0.0, upper=2.0
            ),
        )
    )
    assert isinstance(run, RunExperimentSucceededResult)
    with pytest.raises(ModelingError) as captured:
        application.validate_experiment(
            ValidateExperimentRequest(
                operation_id=_uuid(142),
                project_id=project.project_id,
                attempt_id=run.attempt_id,
                expected_result_hash="sha256:" + ("f" * 64),
                validator_id="numerical.root_finding.residual",
                policy_version="0.1.0",
                policy={},
            )
        )
    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert captured.value.response.details.subject == "result_hash"

    with closing(sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM validations").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM idempotency_records "
            "WHERE tool_name='validate_experiment'"
        ).fetchone() == (0,)


def test_numerical_failure_is_durable_and_replayable(
    tmp_path: Path,
) -> None:
    """Catches expected numerical failure being treated as system error."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(150))
    )
    request = RunExperimentRequest(
        operation_id=_uuid(151),
        project_id=project.project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        ),
        payload=RootFindingInput(
            expression="x*x + 1", lower=-1.0, upper=1.0
        ),
    )
    first = application.run_experiment(request)
    second = application.run_experiment(request)
    assert isinstance(first, RunExperimentNumericalFailureResult)
    assert isinstance(second, RunExperimentNumericalFailureResult)
    assert first.attempt_status == "NUMERICAL_FAILURE"
    assert first.result_summary.failure_code == "no_sign_change"
    assert second.replayed is True
    assert second.attempt_id == first.attempt_id
    assert second.result_hash == first.result_hash


@pytest.mark.parametrize(
    ("raised", "expected_status", "expected_detail"),
    [
        (
            ExecutionDeadlineExceeded("deadline"),
            "TIMED_OUT",
            "deadline_exceeded",
        ),
        (
            ExecutionCancelled("cancelled"),
            "ABANDONED",
            "host_cancelled",
        ),
        (
            ExecutionResourceLimitExceeded(
                "function_evaluations", 100, 101
            ),
            "ERRORED",
            "RESOURCE_LIMIT_EXCEEDED",
        ),
        (RuntimeError("unexpected"), "ERRORED", "INTERNAL_ERROR"),
    ],
)
def test_solver_terminal_errors_are_durable_and_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raised: Exception,
    expected_status: str,
    expected_detail: str,
) -> None:
    """Catches terminal classification drift or replay re-execution."""
    calls = 0

    def fail_once(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise raised

    monkeypatch.setattr(BisectionRootFindingCapability, "execute", fail_once)
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(160))
    )
    request = RunExperimentRequest(
        operation_id=_uuid(161),
        project_id=project.project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        ),
        payload=RootFindingInput(expression="x", lower=-1.0, upper=1.0),
    )
    first = application.run_experiment(request)
    second = application.run_experiment(request)

    assert first.attempt_status == expected_status
    assert second.attempt_status == expected_status
    assert second.replayed is True
    assert second.attempt_id == first.attempt_id
    assert calls == 1
    if isinstance(first, RunExperimentStoppedResult):
        assert first.terminal_reason == expected_detail
        assert isinstance(second, RunExperimentStoppedResult)
        assert second.terminal_reason == expected_detail
    else:
        assert isinstance(first, RunExperimentErroredResult)
        assert isinstance(second, RunExperimentErroredResult)
        assert first.system_error.code == expected_detail
        assert second.system_error.code == expected_detail


def test_solver_output_is_strictly_reconstructed_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches model_construct bypasses being hashed as trusted solver output."""
    calls = 0

    def malformed_output(*_args: object, **_kwargs: object) -> ExecutionOutcome:
        nonlocal calls
        calls += 1
        data = ResultSuccessData.model_construct(
            root=0.0,
            function_value=0.0,
            iterations=-1,
            evaluations=0,
            termination_reason="not-a-terminal-reason",
        )
        payload = SuccessResultPayload.model_construct(
            result_schema_version="modeling-result/0.1.0",
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
            result_kind="success",
            data=data,
        )
        return ExecutionOutcome.success(payload)

    monkeypatch.setattr(
        BisectionRootFindingCapability, "execute", malformed_output
    )
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(165))
    )
    request = RunExperimentRequest(
        operation_id=_uuid(166),
        project_id=project.project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        ),
        payload=RootFindingInput(expression="x", lower=-1.0, upper=1.0),
    )

    first = application.run_experiment(request)
    replay = application.run_experiment(request)

    assert isinstance(first, RunExperimentErroredResult)
    assert isinstance(replay, RunExperimentErroredResult)
    assert first.system_error.code == "INTERNAL_ERROR"
    assert replay.system_error.code == "INTERNAL_ERROR"
    assert replay.replayed is True
    assert calls == 1
    with closing(
        sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")
    ) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM result_snapshots"
        ).fetchone() == (0,)


def test_validator_failed_report_round_trips_and_replays(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches FAILED being treated as system error or losing failed_checks."""
    original_validate = ResidualRootFindingValidator.validate
    calls = 0

    def return_failed(
        self: ResidualRootFindingValidator,
        *args: object,
        **kwargs: object,
    ) -> ValidationReportPayload:
        nonlocal calls
        calls += 1
        report = original_validate(self, *args, **kwargs)  # type: ignore[arg-type]
        metrics = ValidationMetrics(
            **{
                **report.metrics.model_dump(mode="python"),
                "absolute_residual": 1.0,
                "failed_checks": ("residual_exceeds_tolerance",),
            }
        )
        return report.model_copy(
            update={"outcome": "FAILED", "metrics": metrics}
        )

    monkeypatch.setattr(
        ResidualRootFindingValidator, "validate", return_failed
    )
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(170))
    )
    run = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(171),
            project_id=project.project_id,
            mode="new",
            capability=CapabilitySelection(
                capability_id="numerical.root_finding",
                contract_version="0.1.0",
            ),
            payload=RootFindingInput(
                expression="x*x - 2", lower=0.0, upper=2.0
            ),
        )
    )
    assert isinstance(run, RunExperimentSucceededResult)
    request = ValidateExperimentRequest(
        operation_id=_uuid(172),
        project_id=project.project_id,
        attempt_id=run.attempt_id,
        expected_result_hash=run.result_hash,
        validator_id="numerical.root_finding.residual",
        policy_version="0.1.0",
        policy={},
    )
    first = application.validate_experiment(request)
    second = application.validate_experiment(request)
    assert isinstance(first, ValidateExperimentSucceededResult)
    assert isinstance(second, ValidateExperimentSucceededResult)
    assert first.outcome == second.outcome == "FAILED"
    assert first.metrics.failed_checks == ("residual_exceeds_tolerance",)
    assert second.replayed is True
    assert calls == 1

    trace = application.get_project_status(
        GetProjectStatusExperimentRequest(
            project_id=project.project_id,
            view="experiment",
            experiment_id=run.experiment_id,
        )
    )
    stored = trace.trace[1]
    assert stored.record_type == "validation"
    assert stored.metrics is not None
    assert stored.report_payload is not None
    assert stored.metrics.failed_checks == ("residual_exceeds_tolerance",)
    assert stored.report_payload.metrics == stored.metrics


def test_validator_exception_is_durable_and_replayable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches validator runtime errors escaping or rerunning on replay."""
    calls = 0

    def fail(*_args: object, **_kwargs: object) -> object:
        nonlocal calls
        calls += 1
        raise RuntimeError("validator failed")

    monkeypatch.setattr(ResidualRootFindingValidator, "validate", fail)
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(180))
    )
    run = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(181),
            project_id=project.project_id,
            mode="new",
            capability=CapabilitySelection(
                capability_id="numerical.root_finding",
                contract_version="0.1.0",
            ),
            payload=RootFindingInput(
                expression="x*x - 2", lower=0.0, upper=2.0
            ),
        )
    )
    assert isinstance(run, RunExperimentSucceededResult)
    request = ValidateExperimentRequest(
        operation_id=_uuid(182),
        project_id=project.project_id,
        attempt_id=run.attempt_id,
        expected_result_hash=run.result_hash,
        validator_id="numerical.root_finding.residual",
        policy_version="0.1.0",
        policy={},
    )
    first = application.validate_experiment(request)
    second = application.validate_experiment(request)
    assert isinstance(first, ValidateExperimentErroredResult)
    assert isinstance(second, ValidateExperimentErroredResult)
    assert first.operational_error.code == "INTERNAL_ERROR"
    assert second.operational_error.code == "INTERNAL_ERROR"
    assert second.replayed is True
    assert calls == 1


def test_validator_output_is_strictly_reconstructed_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches model_construct bypasses being hashed as a trusted report."""
    original_validate = ResidualRootFindingValidator.validate
    calls = 0

    def malformed_report(
        self: ResidualRootFindingValidator,
        *args: object,
        **kwargs: object,
    ) -> ValidationReportPayload:
        nonlocal calls
        calls += 1
        valid = original_validate(self, *args, **kwargs)  # type: ignore[arg-type]
        document = valid.model_dump(mode="python")
        document["metrics"] = "not-validation-metrics"
        return ValidationReportPayload.model_construct(**document)

    monkeypatch.setattr(
        ResidualRootFindingValidator, "validate", malformed_report
    )
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(185))
    )
    run = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(186),
            project_id=project.project_id,
            mode="new",
            capability=CapabilitySelection(
                capability_id="numerical.root_finding",
                contract_version="0.1.0",
            ),
            payload=RootFindingInput(
                expression="x*x - 2", lower=0.0, upper=2.0
            ),
        )
    )
    assert isinstance(run, RunExperimentSucceededResult)
    request = ValidateExperimentRequest(
        operation_id=_uuid(187),
        project_id=project.project_id,
        attempt_id=run.attempt_id,
        expected_result_hash=run.result_hash,
        validator_id="numerical.root_finding.residual",
        policy_version="0.1.0",
        policy={},
    )

    first = application.validate_experiment(request)
    replay = application.validate_experiment(request)

    assert isinstance(first, ValidateExperimentErroredResult)
    assert isinstance(replay, ValidateExperimentErroredResult)
    assert first.operational_error.code == "INTERNAL_ERROR"
    assert replay.operational_error.code == "INTERNAL_ERROR"
    assert replay.replayed is True
    assert calls == 1
    with closing(
        sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")
    ) as connection:
        assert connection.execute(
            "SELECT report_payload_json FROM validations"
        ).fetchone() == (None,)


def test_concurrent_write_gate_always_reports_project_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches concurrent writes blocking or leaving losing entities."""
    entered = threading.Event()
    release = threading.Event()
    original_execute = BisectionRootFindingCapability.execute

    def blocked_execute(
        self: BisectionRootFindingCapability,
        *args: object,
        **kwargs: object,
    ) -> object:
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("test did not release blocked execution")
        return original_execute(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        BisectionRootFindingCapability, "execute", blocked_execute
    )
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(190))
    )
    request = RunExperimentRequest(
        operation_id=_uuid(191),
        project_id=project.project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        ),
        payload=RootFindingInput(
            expression="x*x - 2", lower=0.0, upper=2.0
        ),
    )
    outcome: list[object] = []

    def run_first() -> None:
        try:
            outcome.append(application.run_experiment(request))
        except BaseException as error:
            outcome.append(error)

    worker = threading.Thread(target=run_first)
    worker.start()
    assert entered.wait(timeout=5)
    try:
        with pytest.raises(ModelingError) as same_operation:
            application.run_experiment(request)
        assert same_operation.value.response.code == "CONFLICT"
        assert same_operation.value.response.retryable is True
        assert (
            same_operation.value.response.details.conflict_type
            == "project_busy"
        )

        with pytest.raises(ModelingError) as project_busy:
            application.run_experiment(
                request.model_copy(update={"operation_id": _uuid(192)})
            )
        assert project_busy.value.response.code == "CONFLICT"
        assert project_busy.value.response.retryable is True
        assert project_busy.value.response.details.conflict_type == "project_busy"
    finally:
        release.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], RunExperimentSucceededResult)
    with closing(sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM experiments").fetchone() == (1,)
        assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM idempotency_records "
            "WHERE tool_name='run_experiment'"
        ).fetchone() == (1,)


def test_pre_persistence_gate_loser_defers_idempotency_to_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches gate claiming operation_in_progress before durable admission."""
    entered = threading.Event()
    release = threading.Event()
    original_normalize = BisectionRootFindingCapability.normalize_and_validate

    def blocked_normalize(
        self: BisectionRootFindingCapability,
        *args: object,
        **kwargs: object,
    ) -> object:
        entered.set()
        if not release.wait(timeout=5):
            raise AssertionError("test did not release blocked normalization")
        return original_normalize(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        BisectionRootFindingCapability,
        "normalize_and_validate",
        blocked_normalize,
    )
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(193))
    )
    request = RunExperimentRequest(
        operation_id=_uuid(194),
        project_id=project.project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        ),
        payload=RootFindingInput(
            expression="x*x - 2", lower=0.0, upper=2.0
        ),
    )
    outcome: list[object] = []

    def run_first() -> None:
        try:
            outcome.append(application.run_experiment(request))
        except BaseException as error:
            outcome.append(error)

    worker = threading.Thread(target=run_first)
    worker.start()
    assert entered.wait(timeout=5)
    try:
        with closing(
            sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")
        ) as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM idempotency_records "
                "WHERE tool_name='run_experiment' AND operation_id=?",
                (request.operation_id,),
            ).fetchone() == (0,)
        with pytest.raises(ModelingError) as busy:
            application.run_experiment(request)
        assert busy.value.response.code == "CONFLICT"
        assert busy.value.response.retryable is True
        assert busy.value.response.details.conflict_type == "project_busy"
    finally:
        release.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert len(outcome) == 1
    assert isinstance(outcome[0], RunExperimentSucceededResult)
    with pytest.raises(ModelingError) as mismatch:
        application.run_experiment(
            request.model_copy(
                update={
                    "payload": RootFindingInput(
                        expression="x - 1", lower=0.0, upper=2.0
                    )
                }
            )
        )
    assert mismatch.value.response.code == "CONFLICT"
    assert mismatch.value.response.retryable is False
    assert mismatch.value.response.details.conflict_type == "idempotency_mismatch"


def test_list_capabilities_distinguishes_unknown_id_and_version(
    tmp_path: Path,
) -> None:
    """Catches implicit latest-version selection or collapsed lookup errors."""
    application = _build_application(tmp_path)
    with pytest.raises(ModelingError) as unknown:
        application.list_capabilities(
            ListCapabilitiesContractRequest(
                detail="contract",
                capability_id="numerical.unknown",
                contract_version="0.1.0",
            )
        )
    assert unknown.value.response.code == "NOT_FOUND"

    with pytest.raises(ModelingError) as unsupported:
        application.list_capabilities(
            ListCapabilitiesContractRequest(
                detail="contract",
                capability_id="numerical.root_finding",
                contract_version="9.9.9",
            )
        )
    assert unsupported.value.response.code == "UNSUPPORTED_VERSION"
    assert unsupported.value.response.details.requested_version == "9.9.9"

    contract = application.list_capabilities(
        ListCapabilitiesContractRequest(
            detail="contract",
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        )
    )
    assert contract.capability.capability_id == "numerical.root_finding"
    assert contract.capability.contract_version == "0.1.0"


def test_no_sqlite_transaction_is_open_during_solver_or_validator(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches mathematical execution occurring inside a DB transaction."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(200))
    )
    database = tmp_path / ".modeling" / "state.sqlite3"
    original_execute = BisectionRootFindingCapability.execute
    original_validate = ResidualRootFindingValidator.validate

    def assert_write_available() -> None:
        with closing(sqlite3.connect(database, timeout=0.1)) as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("ROLLBACK")

    def checked_execute(
        self: BisectionRootFindingCapability,
        *args: object,
        **kwargs: object,
    ) -> object:
        assert_write_available()
        return original_execute(self, *args, **kwargs)  # type: ignore[arg-type]

    def checked_validate(
        self: ResidualRootFindingValidator,
        *args: object,
        **kwargs: object,
    ) -> ValidationReportPayload:
        assert_write_available()
        return original_validate(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(
        BisectionRootFindingCapability, "execute", checked_execute
    )
    monkeypatch.setattr(
        ResidualRootFindingValidator, "validate", checked_validate
    )
    run = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(201),
            project_id=project.project_id,
            mode="new",
            capability=CapabilitySelection(
                capability_id="numerical.root_finding",
                contract_version="0.1.0",
            ),
            payload=RootFindingInput(
                expression="x*x - 2", lower=0.0, upper=2.0
            ),
        )
    )
    assert isinstance(run, RunExperimentSucceededResult)
    validation = application.validate_experiment(
        ValidateExperimentRequest(
            operation_id=_uuid(202),
            project_id=project.project_id,
            attempt_id=run.attempt_id,
            expected_result_hash=run.result_hash,
            validator_id="numerical.root_finding.residual",
            policy_version="0.1.0",
            policy={},
        )
    )
    assert isinstance(validation, ValidateExperimentSucceededResult)


def test_summary_is_capped_at_twenty_and_reports_truncation(
    tmp_path: Path,
) -> None:
    """Catches unbounded summaries or a lost truncation marker."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(210))
    )
    for index in range(21):
        result = application.run_experiment(
            RunExperimentRequest(
                operation_id=_uuid(220 + index),
                project_id=project.project_id,
                mode="new",
                capability=CapabilitySelection(
                    capability_id="numerical.root_finding",
                    contract_version="0.1.0",
                ),
                payload=RootFindingInput(
                    expression="x*x - 2",
                    lower=0.0,
                    upper=2.0,
                ),
            )
        )
        assert isinstance(result, RunExperimentSucceededResult)

    summary = application.get_project_status(
        GetProjectStatusSummaryRequest(
            project_id=project.project_id,
            view="summary",
        )
    )
    assert len(summary.experiments.items) == 20
    assert summary.experiments.truncated is True
    assert summary.attempt_status_counts.succeeded == 21
    assert summary.validation_status_counts.succeeded == 0
    experiment_ids = [item.experiment_id for item in summary.experiments.items]
    assert experiment_ids == sorted(experiment_ids, reverse=True)


def test_run_replay_materializes_defaults_before_hashing(
    tmp_path: Path,
) -> None:
    """Catches semantically equal requests hashing by raw formatting/defaults."""
    application = _build_application(tmp_path)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(250))
    )
    selection = CapabilitySelection(
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
    )
    first = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(251),
            project_id=project.project_id,
            mode="new",
            capability=selection,
            payload=RootFindingInput(
                expression="x*x-2", lower=0.0, upper=2.0
            ),
        )
    )
    second = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(251),
            project_id=project.project_id,
            mode="new",
            capability=selection,
            payload=RootFindingInput(
                expression="x * x - 2", lower=0.0, upper=2.0
            ),
            execution=ExecutionOptions(
                timeout_ms=10_000,
                seed=None,
            ),
        )
    )
    assert isinstance(first, RunExperimentSucceededResult)
    assert isinstance(second, RunExperimentSucceededResult)
    assert second.replayed is True
    assert second.experiment_id == first.experiment_id
    assert second.attempt_id == first.attempt_id


def test_store_rejects_terminal_attempt_with_changed_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches completion trusting caller-owned immutable Attempt identity."""
    versions = VersionSet.m1a()
    store = SQLiteProjectStore(tmp_path, versions)
    application = _build_application(tmp_path, store=store)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(260))
    )
    original_complete = store.complete_attempt

    def complete_tampered(
        command: CompleteAttemptCommand,
    ) -> object:
        tampered = replace(
            command.attempt,
            experiment_id=_uuid(999),
        )
        return original_complete(replace(command, attempt=tampered))

    monkeypatch.setattr(store, "complete_attempt", complete_tampered)
    request = RunExperimentRequest(
        operation_id=_uuid(261),
        project_id=project.project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        ),
        payload=RootFindingInput(
            expression="x*x - 2", lower=0.0, upper=2.0
        ),
    )
    with pytest.raises(ModelingError) as captured:
        application.run_experiment(request)
    assert captured.value.response.code == "INTEGRITY_FAILURE"

    with closing(sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM result_snapshots"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT status FROM idempotency_records "
            "WHERE tool_name='run_experiment' AND operation_id=?",
            (request.operation_id,),
        ).fetchone() == ("IN_PROGRESS",)


def test_store_rejects_terminal_validation_with_changed_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches completion trusting caller-owned immutable Validation identity."""
    versions = VersionSet.m1a()
    store = SQLiteProjectStore(tmp_path, versions)
    application = _build_application(tmp_path, store=store)
    project = application.create_project(
        CreateProjectRequest(operation_id=_uuid(270))
    )
    run = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(271),
            project_id=project.project_id,
            mode="new",
            capability=CapabilitySelection(
                capability_id="numerical.root_finding",
                contract_version="0.1.0",
            ),
            payload=RootFindingInput(
                expression="x*x - 2", lower=0.0, upper=2.0
            ),
        )
    )
    assert isinstance(run, RunExperimentSucceededResult)
    original_complete = store.complete_validation

    def complete_tampered(
        command: CompleteValidationCommand,
    ) -> object:
        tampered = replace(command.validation, attempt_id=_uuid(999))
        return original_complete(replace(command, validation=tampered))

    monkeypatch.setattr(store, "complete_validation", complete_tampered)
    request = ValidateExperimentRequest(
        operation_id=_uuid(272),
        project_id=project.project_id,
        attempt_id=run.attempt_id,
        expected_result_hash=run.result_hash,
        validator_id="numerical.root_finding.residual",
        policy_version="0.1.0",
        policy={},
    )
    with pytest.raises(ModelingError) as captured:
        application.validate_experiment(request)
    assert captured.value.response.code == "INTEGRITY_FAILURE"

    with closing(sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")) as connection:
        assert connection.execute(
            "SELECT status FROM validations WHERE attempt_id=?", (run.attempt_id,)
        ).fetchone() == ("RUNNING",)
        assert connection.execute(
            "SELECT status FROM idempotency_records "
            "WHERE tool_name='validate_experiment' AND operation_id=?",
            (request.operation_id,),
        ).fetchone() == ("IN_PROGRESS",)
