from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


HOST_EVIDENCE_SCHEMA_VERSION = "m1a0-host-evidence/1"
EXPECTED_ARGUMENTS = {
    "equation": "x*x-2",
    "lower": 0,
    "upper": 2,
    "tolerance": 1e-10,
}
SHELL_ITEM_TYPES = {"command_execution", "shell", "shell_command", "command"}
SHELL_TOOL_NAMES = SHELL_ITEM_TYPES | {"exec", "exec_command", "functions.exec"}


@dataclass(frozen=True)
class SpikeTranscriptReport:
    calls: int
    shell_calls: int
    arguments: dict[str, Any]
    root: float
    residual: float
    iterations: int
    equation: str


def _jsonl_events(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"invalid JSONL at line {line_number}") from error
        if not isinstance(event, dict):
            raise ValueError(f"JSONL event at line {line_number} is not an object")
        events.append(event)
    return events


def _raw_evidence_sha256(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _canonical_call(
    server: Any,
    tool: Any,
    arguments: Any,
    structured_result: Any,
) -> dict[str, Any]:
    if not isinstance(server, str) or not isinstance(tool, str):
        raise ValueError("MCP server and tool must be strings")
    if not isinstance(arguments, dict):
        raise ValueError("MCP arguments must be an object")
    if not isinstance(structured_result, dict):
        raise ValueError("MCP structured result must be an object")
    return {
        "server": server,
        "tool": tool,
        "arguments": arguments,
        "structured_result": structured_result,
    }


def _normalized_record(
    *,
    surface: str,
    thread_or_run_id: Any,
    raw_evidence_sha256: str,
    calls: list[dict[str, Any]],
    shell_calls: int,
) -> dict[str, Any]:
    if surface not in {"cli", "desktop", "ide"}:
        raise ValueError("unexpected Codex surface")
    if not isinstance(thread_or_run_id, str) or not thread_or_run_id:
        raise ValueError("platform record has no non-empty thread or run ID")
    call = calls[0] if len(calls) == 1 else {}
    return {
        "schema_version": HOST_EVIDENCE_SCHEMA_VERSION,
        "host_family": "codex",
        "surface": surface,
        "thread_or_run_id": thread_or_run_id,
        "server": call.get("server"),
        "tool": call.get("tool"),
        "arguments": call.get("arguments"),
        "structured_result": call.get("structured_result"),
        "raw_evidence_sha256": raw_evidence_sha256,
        "mcp_calls": len(calls),
        "shell_calls": shell_calls,
    }


def normalize_codex_cli_jsonl(path: Path) -> dict[str, Any]:
    events = _jsonl_events(path)
    thread_ids = [
        event.get("thread_id")
        for event in events
        if event.get("type") == "thread.started"
    ]
    if len(thread_ids) != 1:
        raise ValueError("Codex CLI JSONL must contain exactly one thread.started record")
    all_items = [
        event.get("item")
        for event in events
        if str(event.get("type", "")).startswith("item.")
        and isinstance(event.get("item"), dict)
    ]
    shell_ids = {
        item.get("id", f"anonymous-{index}")
        for index, item in enumerate(all_items)
        if item.get("type") in SHELL_ITEM_TYPES
    }
    mcp_events = [
        (event.get("type"), event.get("item"))
        for event in events
        if str(event.get("type", "")).startswith("item.")
        and isinstance(event.get("item"), dict)
        and event["item"].get("type") == "mcp_tool_call"
    ]
    call_ids = {item.get("id") for _, item in mcp_events}
    completed = [
        item
        for event_type, item in mcp_events
        if event_type == "item.completed"
    ]
    if (
        len(call_ids) != 1
        or None in call_ids
        or len(completed) != 1
        or completed[0].get("status") not in {"completed", "succeeded"}
        or completed[0].get("error") is not None
    ):
        raise ValueError(
            "Codex CLI transcript must contain one successful completed MCP call"
        )
    item = completed[0]
    calls = [
        _canonical_call(
            item.get("server"),
            item.get("tool"),
            item.get("arguments"),
            _structured_content(item.get("result")),
        )
    ]
    return _normalized_record(
        surface="cli",
        thread_or_run_id=thread_ids[0],
        raw_evidence_sha256=_raw_evidence_sha256(path),
        calls=calls,
        shell_calls=len(shell_ids),
    )


def _task_export_surface(events: list[dict[str, Any]]) -> str:
    metadata = [
        event.get("payload")
        for event in events
        if event.get("type") == "session_meta"
        and isinstance(event.get("payload"), dict)
    ]
    if not metadata:
        raise ValueError("Codex task export has no session_meta")
    surfaces: set[str] = set()
    for record in metadata:
        originator = record.get("originator")
        if originator == "Codex Desktop":
            surfaces.add("desktop")
        elif isinstance(originator, str) and (
            "IDE" in originator
            or "VS Code" in originator
            or "vscode" in originator.lower()
        ):
            surfaces.add("ide")
        else:
            raise ValueError("task export is not from Codex Desktop or IDE")
    if len(surfaces) != 1:
        raise ValueError("task export mixes Codex surfaces")
    return surfaces.pop()


def _turn_slice(
    events: list[dict[str, Any]],
    turn_id: str,
) -> list[dict[str, Any]]:
    starts = [
        index
        for index, event in enumerate(events)
        if event.get("type") == "event_msg"
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("type") == "task_started"
        and event["payload"].get("turn_id") == turn_id
    ]
    if len(starts) != 1:
        raise ValueError("expected exactly one matching task_started turn")
    start = starts[0]
    ends = [
        index
        for index, event in enumerate(events[start + 1 :], start + 1)
        if event.get("type") == "event_msg"
        and isinstance(event.get("payload"), dict)
        and event["payload"].get("type") == "task_complete"
        and event["payload"].get("turn_id") == turn_id
    ]
    if not ends:
        raise ValueError("matching task turn has no task_complete record")
    return events[start : ends[0] + 1]


def _parsed_arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("tool-call arguments are not valid JSON") from error
    if not isinstance(value, dict):
        raise ValueError("tool-call arguments are not an object")
    return value


def _desktop_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    starts: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event.get("payload")
        if (
            event.get("type") == "response_item"
            and isinstance(payload, dict)
            and payload.get("type") == "function_call"
            and isinstance(payload.get("namespace"), str)
            and payload["namespace"].startswith("mcp__")
        ):
            call_id = payload.get("call_id")
            if not isinstance(call_id, str) or call_id in starts:
                raise ValueError("invalid or duplicate Desktop MCP call ID")
            starts[call_id] = payload

    calls: list[dict[str, Any]] = []
    for event in events:
        payload = event.get("payload")
        if not (
            event.get("type") == "event_msg"
            and isinstance(payload, dict)
            and payload.get("type") == "mcp_tool_call_end"
        ):
            continue
        call_id = payload.get("call_id")
        start = starts.get(call_id)
        if start is None:
            raise ValueError("Desktop MCP end record has no matching call")
        invocation = payload.get("invocation")
        if not isinstance(invocation, dict):
            raise ValueError("Desktop MCP end record has no invocation")
        start_arguments = _parsed_arguments(start.get("arguments"))
        invocation_arguments = _parsed_arguments(invocation.get("arguments"))
        expected_namespace = f"mcp__{invocation.get('server')}"
        if (
            start.get("namespace") != expected_namespace
            or start.get("name") != invocation.get("tool")
            or start_arguments != invocation_arguments
        ):
            raise ValueError("Desktop MCP call and completion records disagree")
        result = payload.get("result")
        successful = result.get("Ok") if isinstance(result, dict) else None
        if not isinstance(successful, dict) or successful.get("isError") is not False:
            raise ValueError("Desktop MCP call did not complete successfully")
        calls.append(
            _canonical_call(
                invocation.get("server"),
                invocation.get("tool"),
                invocation_arguments,
                successful.get("structuredContent"),
            )
        )
    if len(starts) != len(calls):
        raise ValueError("Desktop task turn has an incomplete MCP call")
    return calls


def _desktop_shell_calls(events: list[dict[str, Any]]) -> int:
    call_ids: set[str] = set()
    for index, event in enumerate(events):
        payload = event.get("payload")
        if event.get("type") != "response_item" or not isinstance(payload, dict):
            continue
        if payload.get("type") not in {"function_call", "custom_tool_call"}:
            continue
        name = payload.get("name")
        if isinstance(name, str) and (
            name in SHELL_TOOL_NAMES
            or name.rsplit(".", 1)[-1] in SHELL_TOOL_NAMES
        ):
            call_ids.add(str(payload.get("call_id") or f"anonymous-{index}"))
    return len(call_ids)


def normalize_codex_task_export(path: Path, turn_id: str) -> dict[str, Any]:
    events = _jsonl_events(path)
    surface = _task_export_surface(events)
    turn_events = _turn_slice(events, turn_id)
    return _normalized_record(
        surface=surface,
        thread_or_run_id=turn_id,
        raw_evidence_sha256=_raw_evidence_sha256(path),
        calls=_desktop_calls(turn_events),
        shell_calls=_desktop_shell_calls(turn_events),
    )


def _structured_content(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as error:
            raise ValueError("MCP result is not JSON") from error
    if not isinstance(value, dict):
        raise ValueError("MCP result is not an object")
    structured = value.get("structuredContent")
    if not isinstance(structured, dict):
        raise ValueError("MCP result has no structuredContent object")
    return structured


def verify_host_evidence(evidence: dict[str, Any]) -> SpikeTranscriptReport:
    if evidence.get("schema_version") != HOST_EVIDENCE_SCHEMA_VERSION:
        raise ValueError("unexpected host evidence schema version")
    if evidence.get("host_family") != "codex":
        raise ValueError("unexpected host family")
    source_surface = evidence.get("surface")
    if source_surface not in {"cli", "desktop", "ide"}:
        raise ValueError("unexpected Codex source surface")
    shell_calls = evidence.get("shell_calls")
    if not isinstance(shell_calls, int) or isinstance(shell_calls, bool):
        raise ValueError("normalized shell_calls is not an integer")
    if shell_calls != 0:
        raise ValueError("transcript contains shell or command execution")
    calls = evidence.get("mcp_calls")
    if not isinstance(calls, int) or isinstance(calls, bool):
        raise ValueError("normalized mcp_calls is not an integer")
    if calls != 1:
        raise ValueError(f"expected exactly one MCP call, found {calls}")
    raw_hash = evidence.get("raw_evidence_sha256")
    if not isinstance(raw_hash, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", raw_hash) is None:
        raise ValueError("invalid raw evidence SHA-256")
    if evidence.get("server") != "modeling_spike" or evidence.get("tool") != "root_finding":
        raise ValueError("unexpected MCP server or tool")
    arguments = evidence.get("arguments")
    if arguments != EXPECTED_ARGUMENTS:
        raise ValueError("unexpected MCP call arguments")
    result = evidence.get("structured_result")
    if not isinstance(result, dict):
        raise ValueError("normalized structured result is not an object")
    equation = result.get("equation")
    root = result.get("root")
    residual = result.get("residual")
    iterations = result.get("iterations")
    if equation != "x*x-2":
        raise ValueError("unexpected equation")
    if not isinstance(root, (int, float)) or isinstance(root, bool) or not math.isfinite(root):
        raise ValueError("root must be finite")
    if not isinstance(residual, (int, float)) or isinstance(residual, bool) or not math.isfinite(residual):
        raise ValueError("residual must be finite")
    if not isinstance(iterations, int) or isinstance(iterations, bool) or not 1 <= iterations <= 100:
        raise ValueError("iterations must be in [1, 100]")
    root = float(root)
    residual = float(residual)
    if residual != abs(root * root - 2.0):
        raise ValueError("residual does not match recomputed value")
    if residual > 1e-9:
        raise ValueError("residual exceeds 1e-9")
    return SpikeTranscriptReport(
        calls=1,
        shell_calls=0,
        arguments=arguments,
        root=root,
        residual=residual,
        iterations=iterations,
        equation=equation,
    )


def verify_codex_transcript(path: Path) -> SpikeTranscriptReport:
    return verify_host_evidence(normalize_codex_cli_jsonl(path))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("record", type=Path)
    parser.add_argument(
        "--source",
        choices=("cli", "task-export"),
        default="cli",
    )
    parser.add_argument("--turn-id")
    parser.add_argument("--normalized-output", type=Path)
    arguments = parser.parse_args()
    try:
        if arguments.source == "cli":
            evidence = normalize_codex_cli_jsonl(arguments.record)
        else:
            if not arguments.turn_id:
                raise ValueError("--turn-id is required for a task export")
            evidence = normalize_codex_task_export(arguments.record, arguments.turn_id)
        report = verify_host_evidence(evidence)
        if arguments.normalized_output is not None:
            arguments.normalized_output.write_text(
                json.dumps(evidence, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(asdict(report), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
