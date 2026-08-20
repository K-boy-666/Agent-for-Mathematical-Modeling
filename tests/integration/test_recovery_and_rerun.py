from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Iterable
import sqlite3

import pytest

from modeling_capabilities.root_finding.solver import BisectionRootFindingCapability
from modeling_capabilities.root_finding.validator import ResidualRootFindingValidator
from modeling_core.application.recovery import RecoveryService
from modeling_core.application.service import ModelingApplication
from modeling_core.contracts.tools import (
    CapabilitySelection,
    CreateProjectRequest,
    EnvironmentSummary,
    RootFindingInput,
    RunExperimentRequest,
    ValidateExperimentRequest,
)
from modeling_core.contracts.errors import ModelingError
from modeling_core.contracts.versions import VersionSet
from modeling_core.ports.project_store import RecoveryReport
from modeling_core.registry import CapabilityRegistry
from modeling_core.version import APPLICATION_VERSION
from modeling_bootstrap.composition import build_composition
from modeling_infrastructure.artifacts.store import ContentAddressedArtifactStore
from modeling_infrastructure.environment import capture_environment_snapshot
from modeling_infrastructure.project_paths import ProjectPaths
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import bootstrap_storage


def _uuid(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012x}"


class _FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 8, 20, tzinfo=UTC)
        self.elapsed = 0.0

    def utc_now(self) -> datetime:
        return self.now

    def monotonic(self) -> float:
        return self.elapsed


class _FixedIds:
    def __init__(self, values: Iterable[str]) -> None:
        self._values = iter(values)

    def new_uuid4(self) -> str:
        return next(self._values)


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


def _build_application(
    project_root: Path, *, session_index: int = 90, id_start: int = 100
) -> tuple[ModelingApplication, SQLiteProjectStore]:
    versions = VersionSet.m1a().model_copy(update={"database_schema_version": 2})
    lock_file = project_root / "uv.lock"
    lock_file.write_bytes(b"recovery-test-lock")
    bootstrap_storage(project_root, versions)
    capability = BisectionRootFindingCapability()
    validator = ResidualRootFindingValidator()
    registry = CapabilityRegistry(versions)
    registry.register_capability(capability)
    registry.register_validator(validator)
    summary = registry.seal(frozenset())
    clock = _FakeClock()
    artifact_store = ContentAddressedArtifactStore(ProjectPaths.bind(project_root))
    store = SQLiteProjectStore(
        project_root,
        versions,
        clock,
        _FixedIds(_uuid(index) for index in range(800, 900)),
        session_id=_uuid(session_index),
        artifact_store=artifact_store,
    )
    store.start_writer_session()
    application = ModelingApplication(
        store=store,
        registry=registry,
        registry_summary=summary,
        versions=versions,
        clock=clock,
        id_generator=_FixedIds(
            _uuid(index) for index in range(id_start, id_start + 500)
        ),
        session_id=_uuid(session_index),
        environment_summary=EnvironmentSummary(
            python_version="3.11.15",
            application_version="0.1.0",
            lock_hash="sha256:" + ("1" * 64),
        ),
        cancellation=_NeverCancelled(),
        default_display_name="recovery test",
        artifact_store=artifact_store,
        environment_document=capture_environment_snapshot(
            lock_file=lock_file,
            capability_descriptor=capability.descriptor,
            validator_descriptor=validator.descriptor,
        ),
    )
    return application, store


def _run_request(project_id: str, operation_index: int) -> RunExperimentRequest:
    return RunExperimentRequest(
        operation_id=_uuid(operation_index),
        project_id=project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding", contract_version="0.1.0"
        ),
        payload=RootFindingInput(expression="x*x-2", lower=0.0, upper=2.0),
    )


def test_recovery_service_delegates_one_timestamped_previous_session_pass(
    tmp_path: Path,
) -> None:
    """Catches startup recovery being omitted or invoked with a drifting timestamp."""
    del tmp_path
    recovered_at = datetime(2026, 8, 20, 1, 2, 3, 456000, tzinfo=UTC)
    calls: list[tuple[str, datetime]] = []

    class RecordingStore:
        def recover_previous_session(
            self, current_session_id: str, timestamp: datetime
        ) -> RecoveryReport:
            calls.append((current_session_id, timestamp))
            return RecoveryReport(
                recovered_attempt_ids=(),
                recovered_validation_ids=(),
                integrity_failure_ids=(),
            )

    store = RecordingStore()
    service = RecoveryService(store)  # type: ignore[arg-type]

    report = service.recover_previous_session(_uuid(1), recovered_at)

    assert calls == [(_uuid(1), recovered_at)]
    assert report == RecoveryReport(
        recovered_attempt_ids=(),
        recovered_validation_ids=(),
        integrity_failure_ids=(),
    )


def test_stable_run_request_requires_experiment_identity_only_for_rerun() -> None:
    """Catches the stable runtime DTO rejecting or ambiguously shaping reruns."""
    common = {
        "operation_id": _uuid(2),
        "project_id": _uuid(3),
        "capability": {
            "capability_id": "numerical.root_finding",
            "contract_version": "1.0.0",
        },
        "payload": {"expression": "x*x-2", "lower": 0.0, "upper": 2.0},
    }

    rerun = RunExperimentRequest.model_validate(
        {**common, "mode": "rerun", "experiment_id": _uuid(4)}
    )
    assert rerun.mode == "rerun"
    assert rerun.experiment_id == _uuid(4)

    with pytest.raises(ValueError):
        RunExperimentRequest.model_validate({**common, "mode": "rerun"})
    with pytest.raises(ValueError):
        RunExperimentRequest.model_validate(
            {**common, "mode": "new", "experiment_id": _uuid(4)}
        )


def test_production_version_set_is_coherently_stable() -> None:
    """Catches B6 switching only the database while leaving public axes on preview."""
    versions = VersionSet.m1b()
    assert versions.application_release == "0.2.0"
    assert versions.tool_contract_version == "modeling-tools/1.0.0"
    assert versions.database_schema_version == 2


@pytest.mark.parametrize("active_status", ["PENDING", "RUNNING"])
def test_previous_session_attempt_converges_once_and_replays_abandoned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    active_status: str,
) -> None:
    """Catches restart recovery duplicating or re-executing an active attempt."""
    application, store = _build_application(tmp_path)
    try:
        project = application.create_project(
            CreateProjectRequest(operation_id=_uuid(5))
        )
        request = _run_request(project.project_id, 6)
        if active_status == "PENDING":
            original = store.mark_attempt_running

            def stop_pending(*_args: object, **_kwargs: object) -> None:
                raise KeyboardInterrupt

            monkeypatch.setattr(store, "mark_attempt_running", stop_pending)
        else:
            original = BisectionRootFindingCapability.execute

            def stop_running(*_args: object, **_kwargs: object) -> object:
                raise KeyboardInterrupt

            monkeypatch.setattr(BisectionRootFindingCapability, "execute", stop_running)
        with pytest.raises(KeyboardInterrupt):
            application.run_experiment(request)
        if active_status == "PENDING":
            monkeypatch.setattr(store, "mark_attempt_running", original)
        else:
            monkeypatch.setattr(BisectionRootFindingCapability, "execute", original)

        recovered_at = datetime(2026, 8, 20, 0, 0, 1, tzinfo=UTC)
        report = RecoveryService(store).recover_previous_session(
            _uuid(91), recovered_at
        )
        assert len(report.recovered_attempt_ids) == 1
        assert report.recovered_validation_ids == ()
        assert report.integrity_failure_ids == ()

        replay = application.run_experiment(request)
        assert replay.replayed is True
        assert replay.attempt_id == report.recovered_attempt_ids[0]
        assert replay.attempt_status == "ABANDONED"
        assert replay.terminal_reason == "server_recovery"

        second = RecoveryService(store).recover_previous_session(
            _uuid(91), recovered_at
        )
        assert second == RecoveryReport((), (), ())
    finally:
        store.close()


@pytest.mark.parametrize("active_status", ["PENDING", "RUNNING"])
def test_previous_session_validation_converges_once_and_replays_abandoned(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    active_status: str,
) -> None:
    """Catches restart recovery losing or re-running an active validation."""
    application, store = _build_application(tmp_path)
    try:
        project = application.create_project(
            CreateProjectRequest(operation_id=_uuid(7))
        )
        run = application.run_experiment(_run_request(project.project_id, 8))
        request = ValidateExperimentRequest(
            operation_id=_uuid(9),
            project_id=project.project_id,
            attempt_id=run.attempt_id,
            expected_result_hash=run.result_hash,
            validator_id="numerical.root_finding.residual",
            policy_version="0.1.0",
            policy={},
        )
        if active_status == "PENDING":
            original = store.mark_validation_running

            def stop_pending(*_args: object, **_kwargs: object) -> None:
                raise KeyboardInterrupt

            monkeypatch.setattr(store, "mark_validation_running", stop_pending)
        else:
            original = ResidualRootFindingValidator.validate

            def stop_running(*_args: object, **_kwargs: object) -> object:
                raise KeyboardInterrupt

            monkeypatch.setattr(ResidualRootFindingValidator, "validate", stop_running)
        with pytest.raises(KeyboardInterrupt):
            application.validate_experiment(request)
        if active_status == "PENDING":
            monkeypatch.setattr(store, "mark_validation_running", original)
        else:
            monkeypatch.setattr(ResidualRootFindingValidator, "validate", original)

        recovered_at = datetime(2026, 8, 20, 0, 0, 2, tzinfo=UTC)
        report = RecoveryService(store).recover_previous_session(
            _uuid(91), recovered_at
        )
        assert report.recovered_attempt_ids == ()
        assert len(report.recovered_validation_ids) == 1
        assert report.integrity_failure_ids == ()

        replay = application.validate_experiment(request)
        assert replay.replayed is True
        assert replay.validation_id == report.recovered_validation_ids[0]
        assert replay.validation_status == "ABANDONED"
        assert replay.terminal_reason == "server_recovery"
    finally:
        store.close()


def test_rerun_reuses_immutable_intent_and_creates_only_execution_state(
    tmp_path: Path,
) -> None:
    """Catches rerun cloning Experiment/InputSnapshot or using caller intent."""
    application, store = _build_application(tmp_path)
    try:
        project = application.create_project(
            CreateProjectRequest(operation_id=_uuid(10))
        )
        first = application.run_experiment(_run_request(project.project_id, 11))
        rerun = application.run_experiment(
            RunExperimentRequest(
                operation_id=_uuid(12),
                project_id=project.project_id,
                mode="rerun",
                experiment_id=first.experiment_id,
                capability=CapabilitySelection(
                    capability_id="numerical.root_finding",
                    contract_version="0.1.0",
                ),
                payload=RootFindingInput(expression="x*x-2", lower=0.0, upper=2.0),
            )
        )

        assert rerun.experiment_id == first.experiment_id
        assert rerun.attempt_id != first.attempt_id
        assert rerun.implementation_id == first.implementation_id
        assert rerun.implementation_version == first.implementation_version
        with sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3") as connection:
            assert connection.execute(
                "SELECT COUNT(*) FROM experiments"
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT COUNT(*) FROM input_snapshots"
            ).fetchone() == (1,)
            assert connection.execute(
                "SELECT COUNT(*) FROM environment_snapshots"
            ).fetchone() == (2,)
            assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone() == (
                2,
            )
            assert connection.execute(
                "SELECT COUNT(DISTINCT input_snapshot_id) FROM attempts"
            ).fetchone() == (1,)
    finally:
        store.close()


def test_impossible_terminal_in_progress_graph_degrades_without_mutating_evidence(
    tmp_path: Path,
) -> None:
    """Catches recovery rewriting a graph forbidden by atomic finalization."""
    application, store = _build_application(tmp_path)
    try:
        project = application.create_project(
            CreateProjectRequest(operation_id=_uuid(13))
        )
        terminal = application.run_experiment(_run_request(project.project_id, 14))
        database = tmp_path / ".modeling" / "state.sqlite3"
        with sqlite3.connect(database) as connection:
            connection.execute(
                "UPDATE idempotency_records SET status='IN_PROGRESS' "
                "WHERE tool_name='run_experiment' AND operation_id=?",
                (_uuid(14),),
            )
            connection.commit()

        report = RecoveryService(store).recover_previous_session(
            _uuid(91), datetime(2026, 8, 20, 0, 0, 3, tzinfo=UTC)
        )

        assert report.recovered_attempt_ids == ()
        assert report.integrity_failure_ids == (_uuid(14),)
        assert store.inspect_project_state().state.value == "DEGRADED"
        with sqlite3.connect(database) as connection:
            assert connection.execute(
                "SELECT status, terminal_reason FROM attempts WHERE attempt_id=?",
                (terminal.attempt_id,),
            ).fetchone() == ("SUCCEEDED", None)
            assert connection.execute(
                "SELECT status FROM idempotency_records "
                "WHERE tool_name='run_experiment' AND operation_id=?",
                (_uuid(14),),
            ).fetchone() == ("IN_PROGRESS",)
    finally:
        store.close()


def test_rerun_rejects_an_unavailable_recorded_implementation_before_new_rows(
    tmp_path: Path,
) -> None:
    """Catches rerun silently substituting the currently registered implementation."""
    application, store = _build_application(tmp_path)
    try:
        project = application.create_project(
            CreateProjectRequest(operation_id=_uuid(15))
        )
        first = application.run_experiment(_run_request(project.project_id, 16))
        database = tmp_path / ".modeling" / "state.sqlite3"
        registration = application._registry.resolve("numerical.root_finding", "0.1.0")
        object.__setattr__(
            registration,
            "descriptor",
            registration.descriptor.model_copy(
                update={"implementation_version": "replacement/0.1.0"}
            ),
        )

        with pytest.raises(ModelingError) as captured:
            application.run_experiment(
                RunExperimentRequest(
                    operation_id=_uuid(17),
                    project_id=project.project_id,
                    mode="rerun",
                    experiment_id=first.experiment_id,
                    capability=CapabilitySelection(
                        capability_id="numerical.root_finding",
                        contract_version="0.1.0",
                    ),
                    payload=RootFindingInput(expression="x*x-2", lower=0.0, upper=2.0),
                )
            )
        assert captured.value.response.code == "UNSUPPORTED_VERSION"
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT COUNT(*) FROM attempts").fetchone() == (
                1,
            )
            assert connection.execute(
                "SELECT COUNT(*) FROM environment_snapshots"
            ).fetchone() == (1,)
    finally:
        store.close()


def test_production_composition_starts_schema_two_recovery_before_serving(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches a partial version switch or recovery running before the writer lock."""
    (tmp_path / "uv.lock").write_bytes(b"production-recovery-lock")
    bootstrap_storage(tmp_path, VersionSet.m1b())
    calls: list[tuple[str, datetime, bool]] = []
    original = RecoveryService.recover_previous_session

    def observe(
        service: RecoveryService,
        current_session_id: str,
        recovered_at: datetime,
    ) -> RecoveryReport:
        store = service._store
        calls.append((current_session_id, recovered_at, store._project_lock.held))
        return original(service, current_session_id, recovered_at)

    monkeypatch.setattr(RecoveryService, "recover_previous_session", observe)
    composition = build_composition(tmp_path)
    try:
        composition.start()
        assert APPLICATION_VERSION == "0.2.0"
        assert composition.store._versions == VersionSet.m1b()
        assert len(calls) == 1
        assert calls[0][0] == composition.session_id
        assert calls[0][1].tzinfo is UTC
        assert calls[0][2] is True
    finally:
        composition.close()
