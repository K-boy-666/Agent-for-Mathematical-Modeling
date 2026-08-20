from __future__ import annotations

import asyncio
import multiprocessing
import sqlite3
import sys
import threading
import urllib.request
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp import types as mcp_types

from modeling_bootstrap.composition import (
    build_composition,
    run_mcp_server as run_composed_mcp_server,
)
from modeling_core.contracts.errors import ModelingError
from modeling_core.contracts.tools import (
    CapabilitySelection,
    CreateProjectRequest,
    CreateProjectResult,
    GetProjectStatusSummaryRequest,
    HealthCheckRequest,
    ListCapabilitiesSummaryRequest,
    RootFindingInput,
    RunExperimentRequest,
    RunExperimentSucceededResult,
    ValidateExperimentRequest,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.ports.project_store import ProjectStoreError
from modeling_infrastructure.project_lock import ProjectLock, StorageConflict
from modeling_infrastructure.storage import (
    StorageMetadata,
    bootstrap_storage,
    load_storage_metadata,
)


def test_official_client_validates_advertised_health_schema_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches advertised output schemas requiring remote resolution."""

    def reject_remote_schema_retrieval(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("advertised schema attempted remote retrieval")

    monkeypatch.setattr(urllib.request, "urlopen", reject_remote_schema_retrieval)

    async def exercise_process() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "modeling_mcp", "--project-root", str(tmp_path)],
            env={"UV_OFFLINE": "1"},
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert tuple(tool.name for tool in tools.tools) == (
                    "health_check",
                    "create_project",
                    "get_project_status",
                    "list_capabilities",
                    "run_experiment",
                    "validate_experiment",
                    "register_problem_assets",
                    "put_subproblem_mmir",
                    "confirm_subproblem_mmir",
                    "export_subproblem",
                )
                result = await session.call_tool("health_check", arguments={})
                assert result.isError is False
                assert result.structuredContent is not None
                assert result.structuredContent["status"] == "OK"
                assert result.structuredContent["project_state"] == "UNINITIALIZED"

    asyncio.run(exercise_process())


def _tree_snapshot(root: Path) -> tuple[tuple[str, str, bytes | None], ...]:
    snapshot: list[tuple[str, str, bytes | None]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            snapshot.append((relative, "directory", None))
        else:
            snapshot.append((relative, "file", path.read_bytes()))
    return tuple(snapshot)


def _race_first_create_process(
    project_root: str,
    operation_id: str,
    barrier: Any,
    release_winner: Any,
    outcomes: Any,
) -> None:
    composition = build_composition(Path(project_root))
    try:
        composition.start()
        barrier.wait(timeout=20)
        try:
            result = composition.application.create_project(
                CreateProjectRequest(operation_id=operation_id)
            )
        except ModelingError as error:
            outcomes.put(
                (
                    "error",
                    error.response.code,
                    error.response.retryable,
                    error.response.details.model_dump(mode="json"),
                )
            )
        else:
            outcomes.put(("success", result.project_id, result.operation_id))
            if not release_winner.wait(timeout=20):
                raise AssertionError("parent did not release process winner")
    except BaseException as error:
        outcomes.put(("unexpected", type(error).__name__, str(error)))
    finally:
        composition.close()


def test_uninitialized_construction_and_start_are_byte_for_byte_side_effect_free(
    tmp_path: Path,
) -> None:
    """Catches eager startup bootstrap or lock-file creation."""
    marker = tmp_path / "existing.bin"
    marker.write_bytes(b"preserve-me")
    before = _tree_snapshot(tmp_path)

    composition = build_composition(tmp_path)
    composition.start()
    health = composition.application.health_check(HealthCheckRequest())

    assert _tree_snapshot(tmp_path) == before
    assert health.project_state == "UNINITIALIZED"
    assert health.status == "OK"
    assert health.ready_for_project_creation is True


def test_first_create_retains_published_writer_lease_until_composition_close(
    tmp_path: Path,
) -> None:
    """Catches a publish-to-transaction lock gap or an unreleased server lease."""
    composition = build_composition(tmp_path)
    composition.start()
    created = composition.application.create_project(
        CreateProjectRequest(operation_id="00000000-0000-4000-8000-000000000001")
    )
    contender = ProjectLock(
        tmp_path / ".modeling" / "project.lock",
        "00000000-0000-4000-8000-000000000002",
    )

    try:
        with pytest.raises(StorageConflict):
            contender.acquire()
    finally:
        contender.release()

    assert created.created is True
    composition.close()
    contender.acquire()
    contender.release()
    assert (tmp_path / ".modeling" / "project.lock").is_file()


def test_late_second_first_create_with_live_wal_reports_project_busy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches public create preflight misclassifying a live WAL as degradation."""
    holder = build_composition(tmp_path)
    contender = build_composition(tmp_path)
    holder.start()
    contender.start()
    transaction_live = threading.Event()
    release_transaction = threading.Event()
    original_write = holder.store._write

    @contextmanager
    def pause_before_commit(
        *, degrade_on_failure: bool = False
    ) -> Iterator[sqlite3.Connection]:
        with original_write(degrade_on_failure=degrade_on_failure) as connection:
            yield connection
            transaction_live.set()
            if not release_transaction.wait(timeout=10):
                raise AssertionError("live transaction was not released")

    monkeypatch.setattr(holder.store, "_write", pause_before_commit)
    holder_outcome: list[CreateProjectResult | BaseException] = []

    def create_as_holder() -> None:
        try:
            holder_outcome.append(
                holder.application.create_project(
                    CreateProjectRequest(
                        operation_id="00000000-0000-4000-8000-000000000003",
                        display_name="Published project",
                    )
                )
            )
        except BaseException as error:
            holder_outcome.append(error)

    holder_thread = threading.Thread(target=create_as_holder)
    holder_thread.start()
    assert transaction_live.wait(timeout=10)
    modeling = tmp_path / ".modeling"
    assert {"state.sqlite3-wal", "state.sqlite3-shm"} <= {
        path.name for path in modeling.iterdir()
    }

    try:
        with pytest.raises(ModelingError) as captured:
            contender.application.create_project(
                CreateProjectRequest(
                    operation_id="00000000-0000-4000-8000-000000000004"
                )
            )
    finally:
        release_transaction.set()
        holder_thread.join(timeout=10)
        holder.close()

    try:
        assert not holder_thread.is_alive()
        assert len(holder_outcome) == 1
        assert isinstance(holder_outcome[0], CreateProjectResult)
        assert captured.value.response.code == "CONFLICT"
        assert captured.value.response.retryable is True
        assert captured.value.response.details.conflict_type == "project_busy"
        retry_request = CreateProjectRequest(
            operation_id="00000000-0000-4000-8000-000000000004"
        )
        retried = contender.application.create_project(retry_request)
        replayed = contender.application.create_project(retry_request)
    finally:
        contender.close()

    assert retried.display_name == "Published project"
    assert retried.created is False
    assert retried.replayed is False
    assert replayed.project_id == retried.project_id
    assert replayed.created is False
    assert replayed.replayed is True
    with closing(sqlite3.connect(modeling / "state.sqlite3")) as connection:
        assert connection.execute("SELECT display_name FROM projects").fetchall() == [
            ("Published project",)
        ]
        assert connection.execute(
            "SELECT operation_id FROM idempotency_records "
            "WHERE tool_name='create_project' ORDER BY operation_id"
        ).fetchall() == [
            ("00000000-0000-4000-8000-000000000003",),
            ("00000000-0000-4000-8000-000000000004",),
        ]


def test_omitted_display_name_is_resolved_from_project_after_degraded_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a transient preflight freezing the local default before lease handoff."""
    publisher = build_composition(tmp_path)
    follower = build_composition(tmp_path)
    publisher.start()
    follower.start()
    transaction_live = threading.Event()
    release_publisher = threading.Event()
    publisher_released = threading.Event()
    degraded_preflight_seen = threading.Event()
    resume_follower = threading.Event()
    original_write = publisher.store._write
    original_integrity = follower.store.inspect_integrity

    @contextmanager
    def pause_publisher_before_commit(
        *, degrade_on_failure: bool = False
    ) -> Iterator[sqlite3.Connection]:
        with original_write(degrade_on_failure=degrade_on_failure) as connection:
            yield connection
            transaction_live.set()
            if not release_publisher.wait(timeout=10):
                raise AssertionError("publisher transaction was not released")

    def pause_after_degraded_preflight(*, deep: bool) -> object:
        report = original_integrity(deep=deep)
        if report.state.value == "DEGRADED" and not degraded_preflight_seen.is_set():
            degraded_preflight_seen.set()
            if not resume_follower.wait(timeout=10):
                raise AssertionError("follower preflight was not resumed")
        return report

    monkeypatch.setattr(publisher.store, "_write", pause_publisher_before_commit)
    monkeypatch.setattr(
        follower.store, "inspect_integrity", pause_after_degraded_preflight
    )
    publisher_outcome: list[CreateProjectResult | BaseException] = []
    follower_outcome: list[CreateProjectResult | BaseException] = []

    def create_publisher() -> None:
        try:
            publisher_outcome.append(
                publisher.application.create_project(
                    CreateProjectRequest(
                        operation_id="00000000-0000-4000-8000-000000000006",
                        display_name="Published project",
                    )
                )
            )
        except BaseException as error:
            publisher_outcome.append(error)
        finally:
            publisher.close()
            publisher_released.set()

    def create_follower() -> None:
        try:
            follower_outcome.append(
                follower.application.create_project(
                    CreateProjectRequest(
                        operation_id="00000000-0000-4000-8000-000000000007"
                    )
                )
            )
        except BaseException as error:
            follower_outcome.append(error)
        finally:
            follower.close()

    publisher_thread = threading.Thread(target=create_publisher)
    follower_thread = threading.Thread(target=create_follower)
    publisher_thread.start()
    assert transaction_live.wait(timeout=10)
    follower_thread.start()
    assert degraded_preflight_seen.wait(timeout=10)
    release_publisher.set()
    assert publisher_released.wait(timeout=10)
    resume_follower.set()
    publisher_thread.join(timeout=10)
    follower_thread.join(timeout=10)

    assert not publisher_thread.is_alive()
    assert not follower_thread.is_alive()
    assert len(publisher_outcome) == 1
    assert isinstance(publisher_outcome[0], CreateProjectResult)
    assert len(follower_outcome) == 1
    assert isinstance(follower_outcome[0], CreateProjectResult)
    follower_result = follower_outcome[0]
    assert follower_result.display_name == "Published project"
    assert follower_result.created is False
    explicit_conflict = build_composition(tmp_path)
    explicit_conflict.start()
    try:
        with pytest.raises(ModelingError) as captured:
            explicit_conflict.application.create_project(
                CreateProjectRequest(
                    operation_id="00000000-0000-4000-8000-000000000008",
                    display_name="Math modeling project",
                )
            )
    finally:
        explicit_conflict.close()
    assert captured.value.response.code == "CONFLICT"
    assert captured.value.response.retryable is False
    assert captured.value.response.details.conflict_type == "project_metadata_mismatch"
    with closing(
        sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")
    ) as connection:
        assert connection.execute(
            "SELECT canonical_request_hash FROM idempotency_records "
            "WHERE operation_id='00000000-0000-4000-8000-000000000007'"
        ).fetchone() == (
            "sha256:6e09b10abf7a225afce1842ccef1e33547051bca91c3d343ff4e310c607b8ee7",
        )


@pytest.mark.parametrize(
    "damage",
    ["missing-lock", "missing-metadata", "unknown-entry", "corrupt-metadata"],
)
def test_late_first_create_preserves_genuine_layout_integrity_failures(
    tmp_path: Path,
    damage: str,
) -> None:
    """Catches transient-contention handling masking invalid published storage."""
    composition = build_composition(tmp_path)
    composition.start()
    bootstrap_storage(tmp_path, VersionSet.m1b())
    modeling = tmp_path / ".modeling"
    if damage == "missing-lock":
        (modeling / "project.lock").unlink()
    elif damage == "missing-metadata":
        (modeling / "project.json").unlink()
    elif damage == "unknown-entry":
        (modeling / "unexpected.bin").write_bytes(b"unexpected")
    else:
        (modeling / "project.json").write_bytes(b"not-json")

    try:
        with pytest.raises(ModelingError) as captured:
            composition.application.create_project(
                CreateProjectRequest(
                    operation_id="00000000-0000-4000-8000-000000000005"
                )
            )
    finally:
        composition.close()

    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert captured.value.response.retryable is False
    with closing(sqlite3.connect(modeling / "state.sqlite3")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM idempotency_records"
        ).fetchone() == (0,)


def test_stable_application_rejects_preview_storage_with_typed_error(
    tmp_path: Path,
) -> None:
    """Catches infrastructure version details escaping the public error model."""
    bootstrap_storage(tmp_path, VersionSet.m1a())
    composition = build_composition(tmp_path)

    try:
        with pytest.raises(ModelingError) as captured:
            composition.application.create_project(
                CreateProjectRequest(
                    operation_id="00000000-0000-4000-8000-000000000009"
                )
            )
    finally:
        composition.close()

    assert captured.value.response.code == "UNSUPPORTED_VERSION"
    assert captured.value.response.details.subject == "database_schema"
    assert captured.value.response.details.requested_version == "1"
    assert captured.value.response.details.supported_versions == ("2",)


def _leave_uninitialized(_root: Path) -> None:
    return


def _make_storage_ready(root: Path) -> None:
    bootstrap_storage(root, VersionSet.m1b())


def _make_ready(root: Path) -> None:
    composition = build_composition(root)
    composition.start()
    composition.application.create_project(
        CreateProjectRequest(operation_id="00000000-0000-4000-8000-000000000010")
    )
    composition.close()


def _make_degraded(root: Path) -> None:
    bootstrap_storage(root, VersionSet.m1b())
    (root / ".modeling" / "project.json").write_bytes(b"not-json")


@pytest.mark.parametrize(
    ("arrange", "expected_state", "expected_ready"),
    [
        (_leave_uninitialized, "UNINITIALIZED", True),
        (_make_storage_ready, "STORAGE_READY", True),
        (_make_ready, "READY", False),
        (_make_degraded, "DEGRADED", False),
    ],
)
def test_health_project_creation_readiness_has_exact_four_state_truth_table(
    tmp_path: Path,
    arrange: Callable[[Path], None],
    expected_state: str,
    expected_ready: bool,
) -> None:
    """Catches READY or DEGRADED storage being advertised as creatable."""
    arrange(tmp_path)
    composition = build_composition(tmp_path)

    health = composition.application.health_check(HealthCheckRequest())

    assert health.project_state == expected_state
    assert health.ready_for_project_creation is expected_ready


@pytest.mark.parametrize("damage", ["corrupt-metadata", "unknown-entry"])
def test_real_mcp_process_serves_read_only_health_for_degraded_storage(
    tmp_path: Path,
    damage: str,
) -> None:
    """Catches production startup exiting instead of serving DEGRADED health."""
    bootstrap_storage(tmp_path, VersionSet.m1b())
    modeling = tmp_path / ".modeling"
    if damage == "corrupt-metadata":
        (modeling / "project.json").write_bytes(b"not-json")
    else:
        (modeling / "unexpected.bin").write_bytes(b"preserve-me")
    before_evidence = tuple(
        item for item in _tree_snapshot(tmp_path) if item[0] != ".modeling/project.lock"
    )
    project_id = "00000000-0000-4000-8000-000000000080"

    async def exercise_process() -> None:
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "modeling_mcp", "--project-root", str(tmp_path)],
        )
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                health = await session.send_request(
                    mcp_types.ClientRequest(
                        mcp_types.CallToolRequest(
                            params=mcp_types.CallToolRequestParams(
                                name="health_check",
                                arguments={},
                            )
                        )
                    ),
                    mcp_types.CallToolResult,
                )
                assert health.isError is False
                assert health.structuredContent is not None
                assert health.structuredContent["status"] == "DEGRADED"
                assert health.structuredContent["project_state"] == "DEGRADED"
                assert health.structuredContent["ready_for_project_creation"] is False
                live_contender = ProjectLock(
                    modeling / "project.lock",
                    "00000000-0000-4000-8000-000000000086",
                )
                with pytest.raises(StorageConflict):
                    live_contender.acquire()
                live_contender.release()

                rejected_requests = {
                    "create_project": CreateProjectRequest(
                        operation_id="00000000-0000-4000-8000-000000000081"
                    ).model_dump(mode="json", exclude_none=True),
                    "get_project_status": GetProjectStatusSummaryRequest(
                        project_id=project_id
                    ).model_dump(mode="json", exclude_none=True),
                    "list_capabilities": ListCapabilitiesSummaryRequest().model_dump(
                        mode="json", exclude_none=True
                    ),
                    "run_experiment": RunExperimentRequest(
                        operation_id="00000000-0000-4000-8000-000000000082",
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
                    ).model_dump(mode="json", exclude_none=True),
                    "validate_experiment": ValidateExperimentRequest(
                        operation_id="00000000-0000-4000-8000-000000000083",
                        project_id=project_id,
                        attempt_id="00000000-0000-4000-8000-000000000084",
                        expected_result_hash="sha256:" + ("0" * 64),
                        validator_id="numerical.root_finding.residual",
                        policy_version="1.0.0",
                        policy={},
                    ).model_dump(mode="json", exclude_none=True),
                }
                for tool_name, arguments in rejected_requests.items():
                    result = await session.call_tool(tool_name, arguments=arguments)
                    assert result.isError is True, tool_name
                    assert result.structuredContent is not None
                    assert result.structuredContent["code"] == "PRECONDITION_FAILED"
                    assert result.structuredContent["details"]["condition"] == (
                        "project_degraded"
                    )

    asyncio.run(exercise_process())

    after_evidence = tuple(
        item for item in _tree_snapshot(tmp_path) if item[0] != ".modeling/project.lock"
    )
    assert after_evidence == before_evidence
    replacement = ProjectLock(
        modeling / "project.lock",
        "00000000-0000-4000-8000-000000000085",
    )
    replacement.acquire()
    replacement.release()


@pytest.mark.parametrize("exit_error", [None, RuntimeError, asyncio.CancelledError])
def test_lifespan_releases_held_lease_on_normal_error_and_cancellation_exit(
    tmp_path: Path,
    exit_error: type[BaseException] | None,
) -> None:
    """Catches any lifespan exit path leaking its OS writer lease."""
    bootstrap_storage(tmp_path, VersionSet.m1b())
    composition = build_composition(tmp_path)
    contender = ProjectLock(
        tmp_path / ".modeling" / "project.lock",
        "00000000-0000-4000-8000-000000000020",
    )

    def exercise_lifespan() -> None:
        with composition:
            with pytest.raises(StorageConflict):
                contender.acquire()
            if exit_error is not None:
                raise exit_error("injected lifespan exit")

    if exit_error is None:
        exercise_lifespan()
    else:
        with pytest.raises(exit_error):
            exercise_lifespan()

    contender.acquire()
    contender.release()
    assert (tmp_path / ".modeling" / "project.lock").is_file()


@pytest.mark.parametrize("ready", [False, True], ids=["storage-ready", "ready"])
def test_existing_storage_is_leased_before_readiness_and_contention_is_transient(
    tmp_path: Path,
    ready: bool,
) -> None:
    """Catches startup readiness preceding lease ownership or sticky contention."""
    if ready:
        _make_ready(tmp_path)
    else:
        _make_storage_ready(tmp_path)
    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        before = (
            connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
            connection.execute("SELECT COUNT(*) FROM idempotency_records").fetchone()[
                0
            ],
        )

    holder = build_composition(tmp_path)
    contender = build_composition(tmp_path)
    holder.start()
    try:
        with pytest.raises(ProjectStoreError) as captured:
            contender.start()
        assert captured.value.code == "CONFLICT"
        assert captured.value.retryable is True
        assert captured.value.details == {
            "conflict_type": "project_busy",
            "retry_after_ms": 250,
        }
        with closing(sqlite3.connect(database)) as connection:
            after = (
                connection.execute("SELECT COUNT(*) FROM projects").fetchone()[0],
                connection.execute(
                    "SELECT COUNT(*) FROM idempotency_records"
                ).fetchone()[0],
            )
        assert after == before
    finally:
        holder.close()

    contender.start()
    assert contender.application.health_check(HealthCheckRequest()).status == "OK"
    contender.close()


def test_publish_to_lock_handoff_loser_opens_no_write_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches the publisher writing after a competitor owns its published lock."""
    from modeling_infrastructure.sqlite import store as sqlite_store

    published = threading.Event()
    resume_publisher = threading.Event()
    contender_holds_lease = threading.Event()
    release_contender = threading.Event()
    losing_write_opened = threading.Event()
    original_bootstrap = sqlite_store.bootstrap_storage

    def pause_after_publish(
        project_root: Path, versions: VersionSet
    ) -> StorageMetadata:
        metadata = original_bootstrap(project_root, versions)
        if metadata.created:
            published.set()
            if not resume_publisher.wait(timeout=10):
                raise AssertionError("publisher was not resumed")
        return metadata

    monkeypatch.setattr(sqlite_store, "bootstrap_storage", pause_after_publish)
    publisher = build_composition(tmp_path)
    contender = build_composition(tmp_path)
    original_publisher_write = publisher.store._write

    @contextmanager
    def observe_losing_write(*, degrade_on_failure: bool = False) -> object:
        losing_write_opened.set()
        with original_publisher_write(
            degrade_on_failure=degrade_on_failure
        ) as connection:
            yield connection

    monkeypatch.setattr(publisher.store, "_write", observe_losing_write)
    publisher_outcome: list[CreateProjectResult | BaseException] = []
    contender_outcome: list[CreateProjectResult | BaseException] = []

    def create_as_publisher() -> None:
        try:
            publisher_outcome.append(
                publisher.application.create_project(
                    CreateProjectRequest(
                        operation_id="00000000-0000-4000-8000-000000000030"
                    )
                )
            )
        except BaseException as error:
            publisher_outcome.append(error)
        finally:
            publisher.close()

    def create_as_contender() -> None:
        try:
            contender_outcome.append(
                contender.application.create_project(
                    CreateProjectRequest(
                        operation_id="00000000-0000-4000-8000-000000000031"
                    )
                )
            )
            contender_holds_lease.set()
            if not release_contender.wait(timeout=10):
                raise AssertionError("contender lease was not released")
        except BaseException as error:
            contender_outcome.append(error)
        finally:
            contender.close()

    publisher_thread = threading.Thread(target=create_as_publisher)
    contender_thread = threading.Thread(target=create_as_contender)
    publisher_thread.start()
    assert published.wait(timeout=10)
    contender_thread.start()
    assert contender_holds_lease.wait(timeout=10)
    resume_publisher.set()
    publisher_thread.join(timeout=10)
    release_contender.set()
    contender_thread.join(timeout=10)

    assert not publisher_thread.is_alive()
    assert not contender_thread.is_alive()
    assert len(publisher_outcome) == 1
    assert isinstance(publisher_outcome[0], ModelingError)
    assert publisher_outcome[0].response.code == "CONFLICT"
    assert publisher_outcome[0].response.retryable is True
    assert publisher_outcome[0].response.details.conflict_type == "project_busy"
    assert len(contender_outcome) == 1
    assert isinstance(contender_outcome[0], CreateProjectResult)
    assert losing_write_opened.is_set() is False
    with closing(
        sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3")
    ) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (1,)
        assert connection.execute(
            "SELECT COUNT(*) FROM idempotency_records WHERE tool_name='create_project'"
        ).fetchone() == (1,)


def test_two_process_first_create_race_publishes_one_complete_project(
    tmp_path: Path,
) -> None:
    """Catches independent initializers publishing or mutating two winners."""
    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    release_winner = context.Event()
    outcomes = context.Queue()
    operation_ids = (
        "00000000-0000-4000-8000-000000000040",
        "00000000-0000-4000-8000-000000000041",
    )
    processes = [
        context.Process(
            target=_race_first_create_process,
            args=(
                str(tmp_path),
                operation_id,
                barrier,
                release_winner,
                outcomes,
            ),
            daemon=True,
        )
        for operation_id in operation_ids
    ]
    try:
        for process in processes:
            process.start()
        results = [outcomes.get(timeout=30), outcomes.get(timeout=30)]
    finally:
        release_winner.set()
        for process in processes:
            process.join(timeout=20)

    assert all(not process.is_alive() for process in processes)
    assert all(process.exitcode == 0 for process in processes)
    successes = [result for result in results if result[0] == "success"]
    errors = [result for result in results if result[0] == "error"]
    assert len(successes) == 1
    assert errors == [
        (
            "error",
            "CONFLICT",
            True,
            {
                "conflict_type": "project_busy",
                "existing_resource_id": None,
                "retry_after_ms": 250,
            },
        )
    ]
    modeling = tmp_path / ".modeling"
    assert {path.name for path in modeling.iterdir()} == {
        "artifacts",
        "project.json",
        "project.lock",
        "staging",
        "state.sqlite3",
    }
    metadata = load_storage_metadata(tmp_path, VersionSet.m1b())
    with closing(sqlite3.connect(modeling / "state.sqlite3")) as connection:
        project_rows = connection.execute(
            "SELECT project_id, storage_instance_id FROM projects"
        ).fetchall()
        idempotency_rows = connection.execute(
            "SELECT scope_id, operation_id FROM idempotency_records "
            "WHERE tool_name='create_project'"
        ).fetchall()
    assert project_rows == [(successes[0][1], metadata.storage_instance_id)]
    assert idempotency_rows == [(metadata.storage_instance_id, successes[0][2])]
    assert list(tmp_path.glob(".modeling.tmp.*")) == []
    assert b".modeling.tmp." not in (modeling / "project.json").read_bytes()


def test_one_held_lease_covers_every_create_run_and_validate_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches any persistence phase escaping the server-lifetime writer lease."""
    composition = build_composition(tmp_path)
    phase = "create"
    observed_phases: list[str] = []
    original_write = composition.store._write

    @contextmanager
    def checked_write(
        *, degrade_on_failure: bool = False
    ) -> Iterator[sqlite3.Connection]:
        assert composition.store._project_lock.held is True
        observed_phases.append(phase)
        with original_write(degrade_on_failure=degrade_on_failure) as connection:
            yield connection

    monkeypatch.setattr(composition.store, "_write", checked_write)
    with composition:
        project = composition.application.create_project(
            CreateProjectRequest(operation_id="00000000-0000-4000-8000-000000000050")
        )
        phase = "run"
        run = composition.application.run_experiment(
            RunExperimentRequest(
                operation_id="00000000-0000-4000-8000-000000000051",
                project_id=project.project_id,
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
        )
        assert isinstance(run, RunExperimentSucceededResult)
        phase = "validate"
        composition.application.validate_experiment(
            ValidateExperimentRequest(
                operation_id="00000000-0000-4000-8000-000000000052",
                project_id=project.project_id,
                attempt_id=run.attempt_id,
                expected_result_hash=run.result_hash,
                validator_id="numerical.root_finding.residual",
                policy_version="1.0.0",
                policy={},
            )
        )

    assert set(observed_phases) == {"create", "run", "validate"}


def test_writer_lease_acquisition_failure_opens_no_sqlite_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches SQLite becoming the first-line cross-process ownership gate."""
    bootstrap_storage(tmp_path, VersionSet.m1b())
    holder = build_composition(tmp_path)
    contender = build_composition(tmp_path)
    holder.start()
    statements: list[str] = []
    original_connect = contender.store._connect

    def traced_connect(*, named_rows: bool = False) -> sqlite3.Connection:
        connection = original_connect(named_rows=named_rows)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(contender.store, "_connect", traced_connect)
    try:
        with pytest.raises(ModelingError) as captured:
            contender.application.create_project(
                CreateProjectRequest(
                    operation_id="00000000-0000-4000-8000-000000000053"
                )
            )
        assert captured.value.response.code == "CONFLICT"
        assert captured.value.response.details.conflict_type == "project_busy"
        assert not any(
            statement.lstrip().upper().startswith("BEGIN") for statement in statements
        )
    finally:
        holder.close()
        contender.close()


def test_held_lease_classifies_sqlite_runtime_sidecars_as_transient_contention(
    tmp_path: Path,
) -> None:
    """Catches SQLite runtime files becoming a sticky degraded server state."""
    bootstrap_storage(tmp_path, VersionSet.m1b())
    modeling = tmp_path / ".modeling"
    for name in ("state.sqlite3-wal", "state.sqlite3-shm"):
        (modeling / name).write_bytes(b"")
    composition = build_composition(tmp_path)

    with pytest.raises(ProjectStoreError) as captured:
        composition.start()

    assert captured.value.code == "CONFLICT"
    assert captured.value.retryable is True
    replacement = ProjectLock(
        modeling / "project.lock",
        "00000000-0000-4000-8000-000000000054",
    )
    replacement.acquire()
    replacement.release()


@pytest.mark.parametrize(
    ("code", "message", "details"),
    [
        (
            "SECURITY_VIOLATION",
            "project root cannot be safely rebound",
            {"rule": "unsafe_reparse_point"},
        ),
        (
            "UNSUPPORTED_VERSION",
            "database schema is newer than this application",
            {
                "subject": "database_schema",
                "requested_version": "2",
                "supported_versions": ["1"],
            },
        ),
    ],
)
def test_non_integrity_storage_error_releases_lease_and_preserves_taxonomy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    message: str,
    details: dict[str, object],
) -> None:
    """Catches security/version failures being masked as read-only degradation."""
    from modeling_infrastructure.sqlite import store as sqlite_store
    from modeling_infrastructure.storage import StorageError

    bootstrap_storage(tmp_path, VersionSet.m1b())
    composition = build_composition(tmp_path)
    original_load = sqlite_store.load_storage_metadata
    lock_path = tmp_path / ".modeling" / "project.lock"
    observed_lease = ProjectLock(
        lock_path,
        "00000000-0000-4000-8000-000000000087",
    )

    def fail_after_lease(*_args: object, **_kwargs: object) -> object:
        with pytest.raises(StorageConflict):
            observed_lease.acquire()
        observed_lease.release()
        raise StorageError(code, message, details=details)

    monkeypatch.setattr(sqlite_store, "load_storage_metadata", fail_after_lease)
    with pytest.raises(ProjectStoreError) as captured:
        composition.start()

    assert captured.value.code == code
    assert captured.value.message == message
    assert captured.value.retryable is False
    assert captured.value.details == details
    replacement = ProjectLock(
        lock_path,
        "00000000-0000-4000-8000-000000000088",
    )
    replacement.acquire()
    replacement.release()

    monkeypatch.setattr(sqlite_store, "load_storage_metadata", original_load)
    health = composition.application.health_check(HealthCheckRequest())
    assert health.status == "OK"
    assert health.project_state == "STORAGE_READY"


@pytest.mark.parametrize("server_error", [None, RuntimeError, asyncio.CancelledError])
def test_process_runner_releases_lease_on_normal_error_and_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    server_error: type[BaseException] | None,
) -> None:
    """Catches the lazy process hook bypassing composition cleanup."""
    from modeling_mcp import server as mcp_server

    bootstrap_storage(tmp_path, VersionSet.m1b())
    contender = ProjectLock(
        tmp_path / ".modeling" / "project.lock",
        "00000000-0000-4000-8000-000000000060",
    )

    async def exercise_server(_facade: object) -> None:
        with pytest.raises(StorageConflict):
            contender.acquire()
        if server_error is not None:
            raise server_error("injected server exit")

    monkeypatch.setattr(mcp_server, "run_mcp_server", exercise_server)
    if server_error is None:
        run_composed_mcp_server(tmp_path)
    else:
        with pytest.raises(server_error):
            run_composed_mcp_server(tmp_path)

    contender.acquire()
    contender.release()
