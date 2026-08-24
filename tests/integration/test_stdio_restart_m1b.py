from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from mcp import ClientSession
from mcp.client.stdio import stdio_client

from modeling_core.contracts.tools import TOOL_NAMES
from modeling_infrastructure.project_lock import ProjectLock
from tests.integration.test_stdio_golden_m1a import (
    _assert_protocol_pure,
    _install_process_observer,
    _server_parameters,
    _validated_uv,
)


CREATE = "20000000-0000-4000-8000-000000000001"
RUN = "20000000-0000-4000-8000-000000000002"
RERUN = "20000000-0000-4000-8000-000000000003"
VALIDATE = "20000000-0000-4000-8000-000000000004"
LOCK = "20000000-0000-4000-8000-000000000005"


async def _call(
    session: ClientSession,
    name: str,
    arguments: dict[str, object],
    *,
    error: bool = False,
) -> dict[str, Any]:
    result = await session.call_tool(name, arguments=arguments)
    assert result.isError is error
    assert result.structuredContent is not None
    return dict(result.structuredContent)


def _run_request(project_id: str) -> dict[str, object]:
    return {
        "operation_id": RUN,
        "project_id": project_id,
        "mode": "new",
        "capability": {
            "capability_id": "numerical.root_finding",
            "contract_version": "1.0.0",
        },
        "payload": {"expression": "x*x-2", "lower": 0.0, "upper": 2.0},
    }


def test_real_stdio_restart_replay_rerun_validation_and_trace_are_stable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository_root = Path(__file__).parents[2]
    project_root = tmp_path / "restart-project"
    project_root.mkdir()
    uv = _validated_uv(repository_root)
    captured = bytearray()
    observed = _install_process_observer(monkeypatch, captured)

    async def first_process() -> tuple[str, dict[str, Any], dict[str, object]]:
        parameters = _server_parameters(uv, repository_root, project_root)
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                initialized = await session.initialize()
                assert initialized.protocolVersion == "2025-11-25"
                observed[-1].capture_windows_process_tree()
                tools = await session.list_tools()
                assert tuple(tool.name for tool in tools.tools) == TOOL_NAMES
                assert all("/1.0.0/" in tool.inputSchema["$id"] for tool in tools.tools)
                assert (await _call(session, "health_check", {}))["project_state"] == (
                    "UNINITIALIZED"
                )
                created = await _call(
                    session, "create_project", {"operation_id": CREATE}
                )
                request = _run_request(created["project_id"])
                run = await _call(session, "run_experiment", request)
                assert run["attempt_status"] == "SUCCEEDED"
                assert len(run["artifacts"]) == 1
                return created["project_id"], run, request

    project_id, first_run, request = asyncio.run(first_process())

    async def second_process() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        parameters = _server_parameters(uv, repository_root, project_root)
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                observed[-1].capture_windows_process_tree()
                replay = await _call(session, "run_experiment", request)
                assert replay["replayed"] is True
                assert replay["attempt_id"] == first_run["attempt_id"]

                rerun_request = {
                    **request,
                    "operation_id": RERUN,
                    "mode": "rerun",
                    "experiment_id": first_run["experiment_id"],
                }
                rerun = await _call(session, "run_experiment", rerun_request)
                assert rerun["experiment_id"] == first_run["experiment_id"]
                assert rerun["attempt_id"] != first_run["attempt_id"]
                assert rerun["result_hash"] == first_run["result_hash"]
                assert len(rerun["artifacts"]) == 1

                validation = await _call(
                    session,
                    "validate_experiment",
                    {
                        "operation_id": VALIDATE,
                        "project_id": project_id,
                        "attempt_id": rerun["attempt_id"],
                        "expected_result_hash": rerun["result_hash"],
                        "validator_id": "numerical.root_finding.residual",
                        "policy_version": "1.0.0",
                        "policy": {},
                    },
                )
                assert validation["outcome"] == "PASSED"
                assert validation["report_artifact"]["role"] == "validation_report"

                page = await _call(
                    session,
                    "get_project_status",
                    {
                        "project_id": project_id,
                        "view": "experiment",
                        "experiment_id": first_run["experiment_id"],
                    },
                )
                identities = [
                    item.get("attempt_id")
                    if item["record_type"] == "attempt"
                    else item["validation_id"]
                    for item in page["trace"]
                ]
                assert len(identities) == len(set(identities)) == 3
                assert {item["record_type"] for item in page["trace"]} == {
                    "attempt",
                    "validation",
                }
                return replay, rerun, validation

    replay, rerun, validation = asyncio.run(second_process())
    assert replay["attempt_id"] == first_run["attempt_id"]
    assert rerun["attempt_id"] != replay["attempt_id"]
    assert validation["attempt_id"] == rerun["attempt_id"]
    _assert_protocol_pure(bytes(captured))
    assert len(observed) == 2
    for process in observed:
        process.assert_process_tree_signaled()
    contender = ProjectLock(project_root / ".modeling" / "project.lock", LOCK)
    contender.acquire()
    contender.release()


def test_restart_replay_fails_closed_after_result_artifact_tampering(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[2]
    project_root = tmp_path / "tampered-project"
    project_root.mkdir()
    uv = _validated_uv(repository_root)

    async def create_run() -> tuple[dict[str, object], Path]:
        parameters = _server_parameters(uv, repository_root, project_root)
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                created = await _call(
                    session, "create_project", {"operation_id": CREATE}
                )
                request = _run_request(created["project_id"])
                run = await _call(session, "run_experiment", request)
                return request, project_root / run["artifacts"][0][
                    "project_relative_path"
                ]

    request, artifact = asyncio.run(create_run())
    artifact.write_bytes(b"{}")

    async def replay_tampered() -> None:
        parameters = _server_parameters(uv, repository_root, project_root)
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                failure = await _call(session, "run_experiment", request, error=True)
                assert failure["code"] == "INTEGRITY_FAILURE"

    asyncio.run(replay_tampered())
