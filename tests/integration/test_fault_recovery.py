"""Real process-death evidence for the five B7 persistence windows."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from modeling_bootstrap.composition import build_composition
from modeling_core.contracts.tools import (
    CapabilitySelection,
    CreateProjectRequest,
    RootFindingInput,
    RunExperimentRequest,
)
from modeling_core.ports.faults import FaultPoint
from modeling_infrastructure.artifacts.store import ContentAddressedArtifactStore
from modeling_infrastructure.project_paths import ProjectPaths


def _uuid(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012x}"


def _initialize_project(project_root: Path) -> str:
    composition = build_composition(project_root)
    with composition:
        return composition.application.create_project(
            CreateProjectRequest(operation_id=_uuid(1))
        ).project_id


def _request(project_id: str) -> RunExperimentRequest:
    return RunExperimentRequest(
        operation_id=_uuid(2),
        project_id=project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="1.0.0",
        ),
        payload=RootFindingInput(
            expression="x*x - 2",
            lower=0.0,
            upper=2.0,
        ),
    )


def _crash(
    project_root: Path, point: FaultPoint, request: RunExperimentRequest
) -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "fault_server.py"
    process = subprocess.Popen(
        [sys.executable, str(fixture), str(project_root), point.value],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr = process.communicate(
        request.model_dump_json(exclude_none=True).encode("utf-8") + b"\n",
        timeout=20,
    )
    assert process.returncode == 91, stderr.decode("utf-8", errors="replace")
    assert stdout == b""


def _restart_and_replay(
    project_root: Path, request: RunExperimentRequest
) -> dict[str, Any]:
    composition = build_composition(project_root)
    with composition:
        result = composition.application.run_experiment(request)
        return result.model_dump(mode="json", exclude_none=True)


def _database_snapshot(project_root: Path) -> tuple[object, ...]:
    database = project_root / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        attempts = tuple(
            connection.execute(
                "SELECT attempt_id, session_id, status, terminal_reason "
                "FROM attempts ORDER BY attempt_id"
            ).fetchall()
        )
        return (
            attempts,
            connection.execute("SELECT COUNT(*) FROM result_snapshots").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],
            tuple(
                connection.execute(
                    "SELECT status FROM idempotency_records "
                    "WHERE tool_name='run_experiment' ORDER BY operation_id"
                ).fetchall()
            ),
        )


def _artifact_files(project_root: Path) -> tuple[Path, ...]:
    root = project_root / ".modeling" / "artifacts" / "sha256"
    return tuple(sorted(root.rglob("*.json"))) if root.exists() else ()


def _artifact_filesystem_snapshot(project_root: Path) -> tuple[tuple[str, bytes], ...]:
    modeling = project_root / ".modeling"
    files = tuple((modeling / "staging").glob("*.json")) + _artifact_files(project_root)
    return tuple(
        (path.relative_to(modeling).as_posix(), path.read_bytes())
        for path in sorted(files)
    )


@pytest.mark.parametrize(
    "point",
    [
        FaultPoint.AFTER_ATTEMPT_CREATED,
        FaultPoint.AFTER_ATTEMPT_RUNNING,
        FaultPoint.DURING_ARTIFACT_STAGING,
        FaultPoint.AFTER_ARTIFACT_PUBLISHED,
        FaultPoint.AFTER_DATABASE_COMMIT,
    ],
)
def test_process_death_recovers_exactly_once_at_each_persistence_window(
    tmp_path: Path,
    point: FaultPoint,
) -> None:
    """Catches files/rows being committed in the wrong order or replay duplication."""
    project_id = _initialize_project(tmp_path)
    request = _request(project_id)

    _crash(tmp_path, point, request)
    crashed = _database_snapshot(tmp_path)
    crashed_attempts = crashed[0]
    assert isinstance(crashed_attempts, tuple)
    assert len(crashed_attempts) == 1
    dead_session_id = crashed_attempts[0][1]

    if point is FaultPoint.AFTER_ATTEMPT_CREATED:
        assert crashed_attempts[0][2] == "PENDING"
    else:
        assert crashed_attempts[0][2] == (
            "SUCCEEDED" if point is FaultPoint.AFTER_DATABASE_COMMIT else "RUNNING"
        )

    artifact_files = _artifact_files(tmp_path)
    crashed_filesystem = _artifact_filesystem_snapshot(tmp_path)
    staging_files = tuple((tmp_path / ".modeling" / "staging").glob("*.json"))
    if point in {
        FaultPoint.AFTER_ATTEMPT_CREATED,
        FaultPoint.AFTER_ATTEMPT_RUNNING,
        FaultPoint.DURING_ARTIFACT_STAGING,
        FaultPoint.AFTER_ARTIFACT_PUBLISHED,
    }:
        assert crashed[1:3] == (0, 0)
    if point is FaultPoint.DURING_ARTIFACT_STAGING:
        assert len(staging_files) == 1
        assert staging_files[0].name.startswith(f"{dead_session_id}.")
        report = ContentAddressedArtifactStore(ProjectPaths.bind(tmp_path)).inspect(
            frozenset()
        )
        assert report.staging_files == (staging_files[0].name,)
    else:
        assert staging_files == ()
    if point is FaultPoint.AFTER_ARTIFACT_PUBLISHED:
        assert len(artifact_files) == 1
        report = ContentAddressedArtifactStore(ProjectPaths.bind(tmp_path)).inspect(
            frozenset()
        )
        assert len(report.orphan_artifacts) == 1
        assert report.orphan_artifacts[0].artifact_id == (
            "sha256:" + artifact_files[0].stem
        )
    elif point is FaultPoint.AFTER_DATABASE_COMMIT:
        assert crashed[1:3] == (1, 1)
        assert len(artifact_files) == 1
    else:
        assert artifact_files == ()

    first_replay = _restart_and_replay(tmp_path, request)
    first_snapshot = _database_snapshot(tmp_path)
    first_filesystem = _artifact_filesystem_snapshot(tmp_path)
    second_replay = _restart_and_replay(tmp_path, request)
    second_snapshot = _database_snapshot(tmp_path)
    second_filesystem = _artifact_filesystem_snapshot(tmp_path)

    assert first_replay["replayed"] is True
    assert second_replay["replayed"] is True
    assert first_replay["attempt_id"] == second_replay["attempt_id"]
    assert first_snapshot == second_snapshot
    assert crashed_filesystem == first_filesystem == second_filesystem
    assert len(first_snapshot[0]) == 1
    assert first_snapshot[3] == (("COMPLETED",),)
    if point is FaultPoint.AFTER_DATABASE_COMMIT:
        assert first_replay["attempt_status"] == "SUCCEEDED"
        assert first_replay["artifacts"] == second_replay["artifacts"]
        assert first_snapshot[1:3] == (1, 1)
        assert len(_artifact_files(tmp_path)) == 1
    else:
        assert first_replay["attempt_status"] == "ABANDONED"
        assert first_replay["terminal_reason"] == "server_recovery"
        assert first_snapshot[1:3] == (0, 0)


class _AdvancingClock:
    def __init__(self) -> None:
        self._now = datetime(2026, 8, 20, tzinfo=UTC)
        self._monotonic = 0.0

    def utc_now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds


class _AdvanceAfterPublish:
    def __init__(self, clock: _AdvancingClock) -> None:
        self._clock = clock

    def check(self, point: FaultPoint, context: object) -> None:
        del context
        if point is FaultPoint.AFTER_ARTIFACT_PUBLISHED:
            self._clock.advance(60.0)


def test_post_publish_deadline_records_timeout_and_leaves_one_verified_orphan(
    tmp_path: Path,
) -> None:
    """Catches a deadline crossing after publication committing a result reference."""
    clock = _AdvancingClock()
    composition = build_composition(
        tmp_path,
        fault_injector=_AdvanceAfterPublish(clock),
    )
    with composition:
        project_id = composition.application.create_project(
            CreateProjectRequest(operation_id=_uuid(20))
        ).project_id
        composition.application._clock = clock
        result = composition.application.run_experiment(_request(project_id))

    assert result.attempt_status == "TIMED_OUT"
    assert result.terminal_reason == "deadline_exceeded"
    snapshot = _database_snapshot(tmp_path)
    assert snapshot[1:3] == (0, 0)
    files = _artifact_files(tmp_path)
    assert len(files) == 1
    store = ContentAddressedArtifactStore(ProjectPaths.bind(tmp_path))
    report = store.inspect(frozenset())
    assert len(report.orphan_artifacts) == 1
    orphan = report.orphan_artifacts[0]
    assert orphan.artifact_id == "sha256:" + files[0].stem
    store.read_verified(orphan.artifact_id, orphan.byte_size, orphan.sha256)
