from __future__ import annotations

import json
import hashlib
from pathlib import Path

import pytest

from verify_codex_transcript import (
    HOST_EVIDENCE_SCHEMA_VERSION,
    normalize_codex_cli_jsonl,
    normalize_codex_task_export,
    verify_host_evidence,
)


ARGUMENTS = {
    "equation": "x*x-2",
    "lower": 0,
    "upper": 2,
    "tolerance": 1e-10,
}
RESULT = {
    "structuredContent": {
        "equation": "x*x-2",
        "root": 1.4142135623842478,
        "residual": 3.154454475406965e-11,
        "iterations": 30,
    }
}


def _write_jsonl(path: Path, events: list[dict[str, object]]) -> Path:
    path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    return path


def _cli_events(
    *,
    arguments: dict[str, object] = ARGUMENTS,
    include_shell: bool = False,
) -> list[dict[str, object]]:
    events: list[dict[str, object]] = [
        {"type": "thread.started", "thread_id": "thread-platform-generated"},
        {
            "type": "item.completed",
            "item": {
                "id": "mcp-1",
                "type": "mcp_tool_call",
                "server": "modeling_spike",
                "tool": "root_finding",
                "arguments": arguments,
                "result": RESULT,
                "error": None,
                "status": "completed",
            },
        },
    ]
    if include_shell:
        events.insert(
            1,
            {
                "type": "item.completed",
                "item": {
                    "id": "shell-1",
                    "type": "command_execution",
                    "command": "python -c pass",
                    "status": "completed",
                },
            },
        )
    return events


def _task_export(
    *,
    arguments: dict[str, object] = ARGUMENTS,
    include_shell: bool = False,
) -> list[dict[str, object]]:
    target_turn = "turn-platform-generated"
    events: list[dict[str, object]] = [
        {
            "timestamp": "2026-07-23T09:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "session-platform-generated",
                "originator": "Codex Desktop",
            },
        },
        {
            "timestamp": "2026-07-23T08:59:00Z",
            "type": "session_meta",
            "payload": {
                "id": "inherited-parent-session",
                "originator": "Codex Desktop",
            },
        },
        {
            "timestamp": "2026-07-23T09:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": "inherited-turn",
            },
        },
        {
            "timestamp": "2026-07-23T09:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "shell_command",
                "arguments": '{"command":"python -c pass"}',
                "call_id": "inherited-shell",
            },
        },
        {
            "timestamp": "2026-07-23T09:00:03Z",
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "inherited-turn",
            },
        },
        {
            "timestamp": "2026-07-23T09:00:04Z",
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": target_turn,
            },
        },
        {
            "timestamp": "2026-07-23T09:00:05Z",
            "type": "turn_context",
            "payload": {"turn_id": target_turn},
        },
        {
            "timestamp": "2026-07-23T09:00:06Z",
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "root_finding",
                "namespace": "mcp__modeling_spike",
                "arguments": json.dumps(arguments),
                "call_id": "mcp-1",
            },
        },
        {
            "timestamp": "2026-07-23T09:00:07Z",
            "type": "event_msg",
            "payload": {
                "type": "mcp_tool_call_end",
                "call_id": "mcp-1",
                "invocation": {
                    "server": "modeling_spike",
                    "tool": "root_finding",
                    "arguments": arguments,
                },
                "result": {
                    "Ok": {
                        "content": [],
                        "structuredContent": RESULT["structuredContent"],
                        "isError": False,
                    }
                },
            },
        },
    ]
    if include_shell:
        events.insert(
            -1,
            {
                "timestamp": "2026-07-23T09:00:06Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "shell_command",
                    "arguments": '{"command":"python -c pass"}',
                    "call_id": "target-shell",
                },
            },
        )
    events.append(
        {
            "timestamp": "2026-07-23T09:00:08Z",
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": target_turn,
            },
        }
    )
    return events


def test_normalize_codex_cli_jsonl_and_verify(tmp_path: Path) -> None:
    raw_path = _write_jsonl(tmp_path / "codex.jsonl", _cli_events())

    evidence = normalize_codex_cli_jsonl(raw_path)
    report = verify_host_evidence(evidence)

    assert evidence == {
        "schema_version": HOST_EVIDENCE_SCHEMA_VERSION,
        "host_family": "codex",
        "surface": "cli",
        "thread_or_run_id": "thread-platform-generated",
        "server": "modeling_spike",
        "tool": "root_finding",
        "arguments": ARGUMENTS,
        "structured_result": RESULT["structuredContent"],
        "raw_evidence_sha256": "sha256:"
        + hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "mcp_calls": 1,
        "shell_calls": 0,
    }
    assert report.calls == 1
    assert report.shell_calls == 0
    assert report.arguments == ARGUMENTS
    assert report.residual == RESULT["structuredContent"]["residual"]


def test_normalize_codex_task_export_and_verify(tmp_path: Path) -> None:
    raw_path = tmp_path / "codex-task-export.json"
    _write_jsonl(raw_path, _task_export())

    evidence = normalize_codex_task_export(raw_path, "turn-platform-generated")
    report = verify_host_evidence(evidence)

    assert evidence == {
        "schema_version": HOST_EVIDENCE_SCHEMA_VERSION,
        "host_family": "codex",
        "surface": "desktop",
        "thread_or_run_id": "turn-platform-generated",
        "server": "modeling_spike",
        "tool": "root_finding",
        "arguments": ARGUMENTS,
        "structured_result": RESULT["structuredContent"],
        "raw_evidence_sha256": "sha256:"
        + hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        "mcp_calls": 1,
        "shell_calls": 0,
    }
    assert report.calls == 1
    assert report.shell_calls == 0


@pytest.mark.parametrize(
    ("normalizer", "raw_payload"),
    [
        ("cli", _cli_events(arguments={**ARGUMENTS, "upper": 3})),
        ("task_export", _task_export(arguments={**ARGUMENTS, "upper": 3})),
    ],
)
def test_verify_rejects_argument_drift(
    tmp_path: Path,
    normalizer: str,
    raw_payload: object,
) -> None:
    if normalizer == "cli":
        raw_path = _write_jsonl(tmp_path / "codex.jsonl", raw_payload)
        evidence = normalize_codex_cli_jsonl(raw_path)
    else:
        raw_path = tmp_path / "codex-task-export.json"
        _write_jsonl(raw_path, raw_payload)
        evidence = normalize_codex_task_export(
            raw_path,
            "turn-platform-generated",
        )

    with pytest.raises(ValueError, match="arguments"):
        verify_host_evidence(evidence)


@pytest.mark.parametrize(
    ("normalizer", "raw_payload"),
    [
        ("cli", _cli_events(include_shell=True)),
        ("task_export", _task_export(include_shell=True)),
    ],
)
def test_verify_rejects_shell_or_command_activity(
    tmp_path: Path,
    normalizer: str,
    raw_payload: object,
) -> None:
    if normalizer == "cli":
        raw_path = _write_jsonl(tmp_path / "codex.jsonl", raw_payload)
        evidence = normalize_codex_cli_jsonl(raw_path)
    else:
        raw_path = tmp_path / "codex-task-export.json"
        _write_jsonl(raw_path, raw_payload)
        evidence = normalize_codex_task_export(
            raw_path,
            "turn-platform-generated",
        )

    with pytest.raises(ValueError, match="shell or command"):
        verify_host_evidence(evidence)
