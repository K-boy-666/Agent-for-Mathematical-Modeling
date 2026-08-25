"""Worker runner — spawns an isolated subprocess and enforces limits.

The parent owns SQLite, locks, states, and publication. The worker subprocess
receives only serialized capability input, deadline, and limits. It has no
database or project-root access.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import Any

from modeling_core.contracts.capability import (
    ExecutionContext,
    ExecutionDeadlineExceeded,
    ExecutionResourceLimitExceeded,
)
from modeling_core.contracts.common import JsonObject

# ── limits ────────────────────────────────────────────────────────────

WORKER_HARD_TIMEOUT_SECONDS: float = 60.0
WORKER_OUTPUT_LIMIT_BYTES: int = 16 * 1024 * 1024  # 16 MiB


@dataclass(frozen=True)
class WorkerResult:
    """Result from a completed worker subprocess."""

    result_kind: str
    result_payload: JsonObject
    warnings: list[dict[str, Any]]


def run_worker(
    *,
    capability_id: str,
    contract_version: str,
    canonical_input_json: str,
    execution_context: ExecutionContext,
    capability_registry_json: str,
) -> WorkerResult:
    """Spawn a worker subprocess, enforce limits, and return the result.

    Raises:
        ExecutionDeadlineExceeded: if the worker exceeds the hard timeout.
        ExecutionResourceLimitExceeded: if the worker output exceeds the cap.
    """
    entry_module = "modeling_core.worker.entry"
    cmd = [
        sys.executable,
        "-c",
        (
            f"import sys, json; "
            f"from {entry_module} import main; "
            f"input_data = json.loads(sys.stdin.read()); "
            f"result = main(input_data); "
            f"json.dump(result, sys.stdout)"
        ),
    ]

    input_data = {
        "capability_id": capability_id,
        "contract_version": contract_version,
        "canonical_input_json": canonical_input_json,
        "execution_context": {
            "attempt_id": execution_context.attempt_id,
            "randomness": execution_context.randomness,
            "seed": execution_context.seed,
            "deadline": execution_context.deadline,
        },
        "capability_registry_json": capability_registry_json,
    }

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

    process = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        creationflags=creationflags,
        start_new_session=sys.platform != "win32",
        cwd=tempfile.gettempdir(),
        text=False,
    )

    try:
        input_bytes = json.dumps(input_data).encode("utf-8")
        stdout_bytes, stderr_bytes = process.communicate(
            input=input_bytes, timeout=WORKER_HARD_TIMEOUT_SECONDS
        )
    except subprocess.TimeoutExpired:
        if sys.platform == "win32":
            process.kill()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)  # type: ignore[union-attr]
        process.wait()
        raise ExecutionDeadlineExceeded()

    if len(stdout_bytes) > WORKER_OUTPUT_LIMIT_BYTES:
        raise ExecutionResourceLimitExceeded(
            resource="worker_output_bytes",
            limit=WORKER_OUTPUT_LIMIT_BYTES,
            observed=len(stdout_bytes),
        )

    if process.returncode != 0:
        raise RuntimeError("worker subprocess failed")

    try:
        result_data = json.loads(stdout_bytes.decode("utf-8"))
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Worker output is not valid JSON: {e}")

    return WorkerResult(
        result_kind=result_data["result_kind"],
        result_payload=result_data["result_payload"],
        warnings=result_data.get("warnings", []),
    )


__all__ = [
    "WORKER_HARD_TIMEOUT_SECONDS",
    "WORKER_OUTPUT_LIMIT_BYTES",
    "WorkerResult",
    "run_worker",
]
