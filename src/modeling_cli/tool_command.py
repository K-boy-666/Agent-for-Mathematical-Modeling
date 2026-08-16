"""CLI tool subcommand — expose all MCP tools as JSON CLI commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from modeling_bootstrap.composition import build_composition
from modeling_core.contracts.errors import ModelingError
from modeling_mcp.adapter import _DISPATCH


def run_tool(project_root: Path, tool_name: str, input_json: str) -> int:
    """Execute a single modeling tool via CLI and print JSON result.

    Args:
        project_root: Path to the project root directory.
        tool_name: One of the 10 registered tool names.
        input_json: JSON string with the tool arguments.

    Returns:
        0 on success, 1 on modeled error, 2 on unhandled failure.
    """
    invoker = _DISPATCH.get(tool_name)
    if invoker is None:
        print(
            json.dumps(
                {
                    "error_schema_version": "modeling-error/0.1.0",
                    "code": "INVALID_REQUEST",
                    "message": f"unknown tool: {tool_name}",
                    "retryable": False,
                    "details": {
                        "field_path": "/name",
                        "reason": "invalid_format",
                    },
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    try:
        arguments = json.loads(input_json)
    except json.JSONDecodeError as error:
        print(
            json.dumps(
                {
                    "error_schema_version": "modeling-error/0.1.0",
                    "code": "INVALID_REQUEST",
                    "message": f"input is not valid JSON: {error}",
                    "retryable": False,
                    "details": {
                        "field_path": "/",
                        "reason": "invalid_format",
                    },
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1

    composition = build_composition(project_root)
    try:
        with composition:
            result = invoker(composition.application, arguments)
    except ModelingError as error:
        print(
            json.dumps(
                error.response.model_dump(
                    mode="json", by_alias=True, exclude_none=True
                ),
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as error:
        print(
            json.dumps(
                {
                    "error_schema_version": "modeling-error/0.1.0",
                    "code": "INTERNAL_ERROR",
                    "message": str(error),
                    "retryable": False,
                },
                separators=(",", ":"),
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2

    print(
        json.dumps(
            result.model_dump(mode="json", by_alias=True),
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0
