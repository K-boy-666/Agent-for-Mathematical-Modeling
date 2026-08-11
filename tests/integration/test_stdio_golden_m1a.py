from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import shutil
import threading
import time
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from modeling_infrastructure.project_lock import ProjectLock


TOOL_NAMES = (
    "health_check",
    "create_project",
    "get_project_status",
    "list_capabilities",
    "run_experiment",
    "validate_experiment",
)
CREATE_OPERATION = "10000000-0000-4000-8000-000000000001"
RUN_OPERATION = "10000000-0000-4000-8000-000000000002"
VALIDATE_OPERATION = "10000000-0000-4000-8000-000000000003"
FAILURE_OPERATION = "10000000-0000-4000-8000-000000000004"
FORBIDDEN_OPERATION = "10000000-0000-4000-8000-000000000005"


class _TeeByteReceiveStream:
    def __init__(self, wrapped: Any, captured: bytearray) -> None:
        self._wrapped = wrapped
        self._captured = captured

    async def receive(self, max_bytes: int = 65536) -> bytes:
        chunk = await self._wrapped.receive(max_bytes)
        self._captured.extend(chunk)
        return chunk

    async def aclose(self) -> None:
        await self._wrapped.aclose()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._wrapped, name)


class _ObservedProcess:
    def __init__(self, process: Any, captured: bytearray) -> None:
        self._process = process
        self._windows_process_handles: list[tuple[int, Any]] = []
        self._captured_tree_pids: tuple[int, ...] = ()
        assert process.stdout is not None
        self.stdout = _TeeByteReceiveStream(process.stdout, captured)

    @property
    def stdin(self) -> Any:
        return self._process.stdin

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> int | None:
        popen = getattr(self._process, "popen", None)
        return popen.poll() if popen is not None else self._process.returncode

    async def wait(self) -> int:
        return await self._process.wait()

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    async def __aenter__(self) -> _ObservedProcess:
        await self._process.__aenter__()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._process.__aexit__(*args)

    def capture_windows_process_tree(self) -> None:
        if sys.platform != "win32":
            self._captured_tree_pids = (self.pid,)
            return

        import win32api
        import win32con
        import win32job

        job = getattr(self._process, "_job_object", None)
        assert job is not None, "official client did not retain its Windows Job Object"
        process_ids = tuple(
            int(process_id)
            for process_id in win32job.QueryInformationJobObject(
                job,
                win32job.JobObjectBasicProcessIdList,
            )
        )
        assert self.pid in process_ids
        assert len(process_ids) >= 2, "uv Job Object did not expose the MCP descendant"

        handles: list[tuple[int, Any]] = []
        try:
            for process_id in process_ids:
                handle = win32api.OpenProcess(win32con.SYNCHRONIZE, False, process_id)
                handles.append((process_id, handle))
        except BaseException:
            for _, handle in handles:
                handle.Close()
            raise
        self._captured_tree_pids = process_ids
        self._windows_process_handles = handles

    async def assert_pipes_closed(self) -> None:
        stdin = self.stdin
        assert stdin is not None
        with anyio.fail_after(1.0):
            with pytest.raises((anyio.BrokenResourceError, anyio.ClosedResourceError)):
                await stdin.send(b"\n")
        with anyio.fail_after(1.0):
            with pytest.raises(
                (
                    anyio.BrokenResourceError,
                    anyio.ClosedResourceError,
                    anyio.EndOfStream,
                )
            ):
                await self.stdout.receive()

    def assert_process_tree_signaled(self, timeout_seconds: float = 5.0) -> None:
        if sys.platform != "win32":
            assert self.returncode is not None
            return

        import win32api
        import win32event

        assert len(self._captured_tree_pids) >= 2
        assert self._windows_process_handles
        deadline = time.monotonic() + timeout_seconds
        try:
            for process_id, handle in self._windows_process_handles:
                remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
                status = win32event.WaitForSingleObject(handle, remaining_ms)
                assert status == win32event.WAIT_OBJECT_0, (
                    f"process {process_id} remained alive after MCP transport shutdown"
                )
        finally:
            for _, handle in self._windows_process_handles:
                win32api.CloseHandle(handle)
            self._windows_process_handles.clear()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._process, name)


def _validated_uv(repository_root: Path) -> Path:
    raw = os.environ.get("UV")
    assert raw is not None, "pinned uv must be supplied through os.environ['UV']"
    executable = Path(raw)
    assert executable.is_absolute()
    assert executable.is_file()
    environment = os.environ.copy()
    environment["UV_OFFLINE"] = "1"
    completed = subprocess.run(
        [str(executable), "--version"],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0
    assert completed.stdout.split()[:2] == ["uv", "0.11.28"]
    return executable


def _server_parameters(
    uv: Path,
    repository_root: Path,
    project_root: Path,
) -> StdioServerParameters:
    return StdioServerParameters(
        command=str(uv),
        args=[
            "run",
            "--locked",
            "--no-sync",
            "modeling-mcp",
            "--project-root",
            str(project_root),
        ],
        cwd=repository_root,
        env={"UV_OFFLINE": "1"},
    )


def _assert_protocol_pure(raw_stdout: bytes) -> None:
    assert raw_stdout
    assert not raw_stdout.startswith(b"\xef\xbb\xbf")
    for frame in raw_stdout.splitlines(keepends=True):
        assert frame.endswith(b"\n")
        assert not frame.startswith(b"\xef\xbb\xbf")
        decoded = frame[:-1].decode("utf-8", errors="strict")
        message = json.loads(decoded)
        assert isinstance(message, dict)
        assert message.get("jsonrpc") == "2.0"


def _install_process_observer(
    monkeypatch: pytest.MonkeyPatch,
    captured: bytearray,
) -> list[_ObservedProcess]:
    from mcp.client import stdio as sdk_stdio

    observed_processes: list[_ObservedProcess] = []
    original_create = sdk_stdio._create_platform_compatible_process

    async def observe_process(*args: object, **kwargs: object) -> _ObservedProcess:
        process = await original_create(*args, **kwargs)
        observed = _ObservedProcess(process, captured)
        observed_processes.append(observed)
        return observed

    monkeypatch.setattr(
        sdk_stdio,
        "_create_platform_compatible_process",
        observe_process,
    )
    return observed_processes


def test_official_client_completes_m1a_golden_chain_records_protocol_purity_and_closes_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches fake/in-process MCP evidence, polluted stdout, or leaked child/lease."""
    repository_root = Path(__file__).resolve().parents[2]
    uv = _validated_uv(repository_root)
    project_root = tmp_path / "stdio-golden-project"
    project_root.mkdir()
    raw_stdout = bytearray()
    observed_processes = _install_process_observer(monkeypatch, raw_stdout)
    parser_errors: list[Exception] = []
    transcript: list[dict[str, object]] = []

    async def reject_parser_error(message: object) -> None:
        if isinstance(message, Exception):
            parser_errors.append(message)
            raise AssertionError(
                "official MCP client received a parser exception"
            ) from message

    async def call(
        session: ClientSession,
        name: str,
        arguments: dict[str, object],
        *,
        expected_is_error: bool = False,
    ) -> dict[str, Any]:
        transcript.append(
            {
                "direction": "client_to_server",
                "kind": "tool_call",
                "tool": name,
                "is_error": False,
                "status": None,
            }
        )
        result = await session.call_tool(name, arguments=arguments)
        assert result.isError is expected_is_error
        assert result.structuredContent is not None
        structured = dict(result.structuredContent)
        transcript.append(
            {
                "direction": "server_to_client",
                "kind": "tool_result",
                "tool": name,
                "is_error": bool(result.isError),
                "status": structured.get("status")
                or structured.get("attempt_status")
                or structured.get("validation_status")
                or structured.get("code"),
            }
        )
        return structured

    async def exercise() -> tuple[
        float,
        str,
        dict[str, Any],
        dict[str, Any],
        dict[str, Any],
    ]:
        parameters = _server_parameters(uv, repository_root, project_root)
        with (tmp_path / "child.stderr").open("w+", encoding="utf-8") as stderr:
            async with stdio_client(parameters, errlog=stderr) as (
                read_stream,
                write_stream,
            ):
                async with ClientSession(
                    read_stream,
                    write_stream,
                    message_handler=reject_parser_error,
                ) as session:
                    initialized = await session.initialize()
                    assert initialized.protocolVersion == "2025-11-25"
                    assert len(observed_processes) == 1
                    observed_processes[0].capture_windows_process_tree()
                    transcript.append(
                        {
                            "direction": "server_to_client",
                            "kind": "initialize",
                            "is_error": False,
                            "status": "OK",
                            "versions": {
                                "mcp_protocol": initialized.protocolVersion,
                                "application": initialized.serverInfo.version,
                            },
                        }
                    )
                    tools = await session.list_tools()
                    assert tuple(tool.name for tool in tools.tools) == TOOL_NAMES
                    transcript.append(
                        {
                            "direction": "server_to_client",
                            "kind": "tools_list",
                            "is_error": False,
                            "status": "OK",
                        }
                    )

                    initial_health = await call(session, "health_check", {})
                    assert initial_health["project_state"] == "UNINITIALIZED"

                    created = await call(
                        session,
                        "create_project",
                        {"operation_id": CREATE_OPERATION},
                    )
                    project_id = created["project_id"]
                    assert created["created"] is True
                    assert created["replayed"] is False

                    ready_health = await call(session, "health_check", {})
                    assert ready_health["project_state"] == "READY"

                    summary = await call(
                        session,
                        "get_project_status",
                        {"project_id": project_id, "view": "summary"},
                    )
                    assert summary["view"] == "summary"
                    assert summary["project"]["project_id"] == project_id

                    capabilities = await call(
                        session,
                        "list_capabilities",
                        {"detail": "summary"},
                    )
                    assert [
                        item["capability_id"] for item in capabilities["capabilities"]
                    ] == ["numerical.root_finding"]
                    contract = await call(
                        session,
                        "list_capabilities",
                        {
                            "detail": "contract",
                            "capability_id": "numerical.root_finding",
                            "contract_version": "0.1.0",
                        },
                    )
                    assert contract["capability"]["contract_version"] == "0.1.0"
                    assert contract["capability"]["validators"][0]["validator_id"] == (
                        "numerical.root_finding.residual"
                    )

                    run_arguments = {
                        "operation_id": RUN_OPERATION,
                        "project_id": project_id,
                        "mode": "new",
                        "capability": {
                            "capability_id": "numerical.root_finding",
                            "contract_version": "0.1.0",
                        },
                        "payload": {
                            "expression": "x*x-2",
                            "lower": 0.0,
                            "upper": 2.0,
                        },
                    }
                    run = await call(session, "run_experiment", run_arguments)
                    assert run["attempt_status"] == "SUCCEEDED"
                    assert abs(run["result_summary"]["root"] ** 2 - 2.0) <= 1e-9

                    validation = await call(
                        session,
                        "validate_experiment",
                        {
                            "operation_id": VALIDATE_OPERATION,
                            "project_id": project_id,
                            "attempt_id": run["attempt_id"],
                            "expected_result_hash": run["result_hash"],
                            "validator_id": "numerical.root_finding.residual",
                            "policy_version": "0.1.0",
                            "policy": {},
                        },
                    )
                    assert validation["validation_status"] == "SUCCEEDED"
                    assert validation["outcome"] == "PASSED"

                    experiment = await call(
                        session,
                        "get_project_status",
                        {
                            "project_id": project_id,
                            "view": "experiment",
                            "experiment_id": run["experiment_id"],
                        },
                    )
                    assert experiment["view"] == "experiment"
                    assert [item["record_type"] for item in experiment["trace"]] == [
                        "attempt",
                        "validation",
                    ]
                    persisted_attempt, persisted_validation = experiment["trace"]
                    persisted_experiment = experiment["experiment"]
                    assert experiment["project"]["project_id"] == project_id
                    assert persisted_experiment["project_id"] == project_id
                    assert persisted_experiment["experiment_id"] == run["experiment_id"]
                    assert persisted_experiment["capability_id"] == run["capability_id"]
                    assert (
                        persisted_experiment["contract_version"]
                        == run["contract_version"]
                    )
                    assert persisted_attempt["attempt_id"] == run["attempt_id"]
                    assert persisted_attempt["experiment_id"] == run["experiment_id"]
                    assert persisted_attempt["status"] == run["attempt_status"]
                    assert (
                        persisted_attempt["implementation_id"]
                        == run["implementation_id"]
                    )
                    assert (
                        persisted_attempt["implementation_version"]
                        == run["implementation_version"]
                    )
                    assert (
                        persisted_attempt["result"]["result_hash"] == run["result_hash"]
                    )
                    assert (
                        persisted_validation["validation_id"]
                        == validation["validation_id"]
                    )
                    assert persisted_validation["attempt_id"] == run["attempt_id"]
                    assert (
                        persisted_validation["status"]
                        == validation["validation_status"]
                    )
                    assert persisted_validation["outcome"] == validation["outcome"]
                    assert persisted_validation["result_hash"] == run["result_hash"]
                    assert (
                        persisted_validation["validator_id"]
                        == validation["validator_id"]
                    )
                    assert (
                        persisted_validation["validator_implementation_id"]
                        == validation["validator_implementation_id"]
                    )
                    assert (
                        persisted_validation["validator_implementation_version"]
                        == validation["validator_implementation_version"]
                    )
                    assert (
                        persisted_validation["policy_version"]
                        == validation["policy_version"]
                    )
                    assert (
                        persisted_validation["policy_hash"] == validation["policy_hash"]
                    )
                    assert (
                        persisted_validation["validation_report_hash"]
                        == validation["validation_report_hash"]
                    )

                    numerical_failure = await call(
                        session,
                        "run_experiment",
                        {
                            **run_arguments,
                            "operation_id": FAILURE_OPERATION,
                            "payload": {
                                "expression": "x*x+1",
                                "lower": -1.0,
                                "upper": 1.0,
                            },
                        },
                    )
                    assert numerical_failure["attempt_status"] == "NUMERICAL_FAILURE"
                    assert numerical_failure["result_summary"]["failure_code"] == (
                        "no_sign_change"
                    )

                    forbidden = await call(
                        session,
                        "run_experiment",
                        {
                            **run_arguments,
                            "operation_id": FORBIDDEN_OPERATION,
                            "payload": {
                                "expression": "__import__('os')",
                                "lower": 0.0,
                                "upper": 2.0,
                            },
                        },
                        expected_is_error=True,
                    )
                    assert forbidden["code"] == "SECURITY_VIOLATION"
                    assert forbidden["details"]["rule"] == "math_expr_forbidden_syntax"

                    replay = await call(session, "run_experiment", run_arguments)
                    assert replay["replayed"] is True
                    assert replay["attempt_id"] == run["attempt_id"]

                    mismatch = await call(
                        session,
                        "run_experiment",
                        {
                            **run_arguments,
                            "payload": {
                                "expression": "x-1",
                                "lower": 0.0,
                                "upper": 2.0,
                            },
                        },
                        expected_is_error=True,
                    )
                    assert mismatch["code"] == "CONFLICT"
                    assert (
                        mismatch["details"]["conflict_type"] == "idempotency_mismatch"
                    )
                    shutdown_started = time.monotonic()

            await observed_processes[0].assert_pipes_closed()
            stderr.flush()
            stderr.seek(0)
            assert stderr.read() == ""
        return shutdown_started, str(project_id), run, validation, experiment

    shutdown_started, project_id, run, validation, experiment = asyncio.run(exercise())

    assert parser_errors == []
    assert len(observed_processes) == 1
    _assert_protocol_pure(bytes(raw_stdout))
    observed_processes[0].assert_process_tree_signaled()
    lease_contender = ProjectLock(
        project_root / ".modeling" / "project.lock",
        "10000000-0000-4000-8000-000000000006",
    )
    lease_contender.acquire()
    lease_contender.release()
    assert time.monotonic() - shutdown_started <= 5.0

    from modeling_harness.evidence import write_redacted_golden_evidence

    hook = os.environ.get("MODELING_M1A_GOLDEN_EVIDENCE_DIR")
    if hook is None:
        staging = tmp_path / "evidence-staging"
        staging.mkdir()
    else:
        staging = Path(hook)
        assert staging.is_absolute()
        assert staging.is_dir()
    persisted_experiment = experiment["experiment"]
    persisted_attempt, persisted_validation = experiment["trace"]
    paths = write_redacted_golden_evidence(
        staging,
        transcript=transcript,
        trace={
            "project_id": str(experiment["project"]["project_id"]),
            "experiment_id": str(persisted_experiment["experiment_id"]),
            "attempt_id": str(persisted_attempt["attempt_id"]),
            "validation_id": str(persisted_validation["validation_id"]),
            "capability_id": str(persisted_experiment["capability_id"]),
            "contract_version": str(persisted_experiment["contract_version"]),
            "attempt_status": str(persisted_attempt["status"]),
            "validation_status": str(persisted_validation["status"]),
            "validation_outcome": str(persisted_validation["outcome"]),
            "result_hash": str(persisted_attempt["result"]["result_hash"]),
            "validation_report_hash": str(
                persisted_validation["validation_report_hash"]
            ),
        },
    )
    assert paths.transcript == Path("stdio-transcript.json")
    assert paths.trace == Path("golden-trace.json")
    transcript_document = json.loads((staging / paths.transcript).read_text("utf-8"))
    trace_document = json.loads((staging / paths.trace).read_text("utf-8"))
    assert transcript_document["schema_version"] == ("m1a-stdio-transcript/0.1.0")
    events = transcript_document["events"]
    assert len(events) == 28
    assert [event["kind"] for event in events[:2]] == ["initialize", "tools_list"]
    assert [event["tool"] for event in events if event["kind"] == "tool_call"] == [
        "health_check",
        "create_project",
        "health_check",
        "get_project_status",
        "list_capabilities",
        "list_capabilities",
        "run_experiment",
        "validate_experiment",
        "get_project_status",
        "run_experiment",
        "run_experiment",
        "run_experiment",
        "run_experiment",
    ]
    assert [
        (event["tool"], event["is_error"])
        for event in events
        if event["kind"] == "tool_result"
    ] == [
        ("health_check", False),
        ("create_project", False),
        ("health_check", False),
        ("get_project_status", False),
        ("list_capabilities", False),
        ("list_capabilities", False),
        ("run_experiment", False),
        ("validate_experiment", False),
        ("get_project_status", False),
        ("run_experiment", False),
        ("run_experiment", True),
        ("run_experiment", False),
        ("run_experiment", True),
    ]
    assert trace_document == {
        "schema_version": "m1a-golden-trace/0.1.0",
        "project_id": project_id,
        "experiment_id": run["experiment_id"],
        "attempt_id": run["attempt_id"],
        "validation_id": validation["validation_id"],
        "capability_id": "numerical.root_finding",
        "contract_version": "0.1.0",
        "attempt_status": "SUCCEEDED",
        "validation_status": "SUCCEEDED",
        "validation_outcome": "PASSED",
        "result_hash": run["result_hash"],
        "validation_report_hash": validation["validation_report_hash"],
    }


def test_official_client_exception_path_closes_child_and_releases_writer_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches client-side failure bypassing STDIO child and writer-lease cleanup."""
    repository_root = Path(__file__).resolve().parents[2]
    uv = _validated_uv(repository_root)
    project_root = tmp_path / "stdio-error-project"
    project_root.mkdir()
    raw_stdout = bytearray()
    observed_processes = _install_process_observer(monkeypatch, raw_stdout)
    shutdown_started = 0.0

    class ClientAbort(RuntimeError):
        pass

    async def exercise() -> None:
        nonlocal shutdown_started
        parameters = _server_parameters(uv, repository_root, project_root)
        try:
            with (tmp_path / "error-child.stderr").open(
                "w+", encoding="utf-8"
            ) as stderr:
                async with stdio_client(parameters, errlog=stderr) as (
                    read_stream,
                    write_stream,
                ):
                    async with ClientSession(read_stream, write_stream) as session:
                        await session.initialize()
                        created = await session.call_tool(
                            "create_project",
                            arguments={
                                "operation_id": ("30000000-0000-4000-8000-000000000001")
                            },
                        )
                        assert created.isError is False
                        assert len(observed_processes) == 1
                        observed_processes[0].capture_windows_process_tree()
                        shutdown_started = time.monotonic()
                        raise ClientAbort("injected client failure")
        except* ClientAbort as caught:
            assert len(caught.exceptions) == 1
        await observed_processes[0].assert_pipes_closed()

    asyncio.run(exercise())

    assert len(observed_processes) == 1
    _assert_protocol_pure(bytes(raw_stdout))
    observed_processes[0].assert_process_tree_signaled()
    assert (tmp_path / "error-child.stderr").read_text(encoding="utf-8") == ""
    contender = ProjectLock(
        project_root / ".modeling" / "project.lock",
        "30000000-0000-4000-8000-000000000002",
    )
    contender.acquire()
    contender.release()
    assert time.monotonic() - shutdown_started <= 5.0


def _minimal_transcript() -> list[dict[str, object]]:
    return [
        {
            "direction": "server_to_client",
            "kind": "tool_result",
            "tool": "health_check",
            "is_error": False,
            "status": "OK",
        }
    ]


def _minimal_trace() -> dict[str, object]:
    return {
        "project_id": "20000000-0000-4000-8000-000000000001",
        "experiment_id": "20000000-0000-4000-8000-000000000002",
        "attempt_id": "20000000-0000-4000-8000-000000000003",
        "validation_id": "20000000-0000-4000-8000-000000000004",
        "capability_id": "numerical.root_finding",
        "contract_version": "0.1.0",
        "attempt_status": "SUCCEEDED",
        "validation_status": "SUCCEEDED",
        "validation_outcome": "PASSED",
        "result_hash": "sha256:" + "a" * 64,
        "validation_report_hash": "sha256:" + "b" * 64,
    }


@pytest.mark.parametrize(
    ("transcript_change", "trace_change"),
    [
        ({"arguments": {"expression": "x*x-2"}}, {}),
        ({"raw_payload": {"secret": "value"}}, {}),
        ({"absolute_path": "C:/private/project"}, {}),
        ({"api_token": "do-not-record"}, {}),
        ({"versions": {"absolute_uv_path": "C:/private/uv.exe"}}, {}),
        ({"versions": {"token": "secret"}}, {}),
        ({}, {"result_summary": {"root": 1.414}}),
        ({}, {"project_root": "C:/private/project"}),
        ({}, {"stderr": "password=secret"}),
    ],
)
def test_evidence_writer_rejects_non_redacted_or_unbounded_fields(
    tmp_path: Path,
    transcript_change: dict[str, object],
    trace_change: dict[str, object],
) -> None:
    """Catches raw payloads, full results, paths, or secrets entering evidence."""
    from modeling_harness.evidence import (
        EvidenceValidationError,
        write_redacted_golden_evidence,
    )

    transcript = _minimal_transcript()
    transcript[0].update(transcript_change)
    trace = {**_minimal_trace(), **trace_change}

    with pytest.raises(EvidenceValidationError):
        write_redacted_golden_evidence(
            tmp_path,
            transcript=transcript,
            trace=trace,
        )

    assert list(tmp_path.iterdir()) == []


def test_evidence_writer_fails_closed_without_overwriting_existing_output(
    tmp_path: Path,
) -> None:
    """Catches stale evidence reuse or replacement of an earlier golden run."""
    from modeling_harness.evidence import write_redacted_golden_evidence

    transcript = tmp_path / "stdio-transcript.json"
    transcript.write_text("preserve", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_redacted_golden_evidence(
            tmp_path,
            transcript=_minimal_transcript(),
            trace=_minimal_trace(),
        )

    assert transcript.read_text("utf-8") == "preserve"
    assert not (tmp_path / "golden-trace.json").exists()


def test_evidence_writer_preserves_a_race_winner_without_overwriting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches publication replacing a winner created after the stale precheck."""
    from modeling_harness import evidence

    temporary_flushed = threading.Event()
    allow_publish = threading.Event()
    original_fsync = evidence.os.fsync
    outcomes: list[object] = []

    def pause_after_first_complete_temporary(descriptor: int) -> None:
        original_fsync(descriptor)
        if not temporary_flushed.is_set():
            temporary_flushed.set()
            if not allow_publish.wait(timeout=5):
                raise AssertionError("race fixture did not release evidence writer")

    def write_evidence() -> None:
        try:
            outcomes.append(
                evidence.write_redacted_golden_evidence(
                    tmp_path,
                    transcript=_minimal_transcript(),
                    trace=_minimal_trace(),
                )
            )
        except BaseException as error:
            outcomes.append(error)

    monkeypatch.setattr(evidence.os, "fsync", pause_after_first_complete_temporary)
    writer = threading.Thread(target=write_evidence)
    writer.start()
    try:
        assert temporary_flushed.wait(timeout=5)
        transcript = tmp_path / "stdio-transcript.json"
        transcript.write_text("race-winner", encoding="utf-8")
    finally:
        allow_publish.set()
        writer.join(timeout=5)

    assert not writer.is_alive()
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], FileExistsError)
    assert transcript.read_text(encoding="utf-8") == "race-winner"
    assert not (tmp_path / "golden-trace.json").exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_evidence_writer_closes_files_and_returns_only_relative_paths(
    tmp_path: Path,
) -> None:
    """Catches leaked file handles or absolute evidence paths in reports."""
    from modeling_harness.evidence import write_redacted_golden_evidence

    staging = tmp_path / "staging"
    staging.mkdir()
    paths = write_redacted_golden_evidence(
        staging,
        transcript=_minimal_transcript(),
        trace=_minimal_trace(),
    )

    assert not paths.transcript.is_absolute()
    assert not paths.trace.is_absolute()
    moved = tmp_path / "moved"
    staging.rename(moved)
    shutil.rmtree(moved)
    assert not moved.exists()
