"""Worker entry point — runs in an isolated subprocess.

This module MUST NOT statically import store, sqlite, or project infrastructure.
It receives only serialized capability input and returns serialized output.
"""

from __future__ import annotations

import importlib
import json
import time
from datetime import UTC, datetime
from typing import Any

from modeling_core.contracts.capability import ExecutionContext
from modeling_core.contracts.versions import VersionSet
from modeling_core.registry import CapabilityRegistry

# ── capability module paths (for dynamic import) ──────────────────────

_CAPABILITY_MODULES: dict[str, str] = {
    "numerical.root_finding": "modeling_capabilities.root_finding.solver",
}

_CAPABILITY_CLASSES: dict[str, str] = {
    "numerical.root_finding": "BisectionRootFindingCapability",
}


def _build_registry() -> CapabilityRegistry:
    """Build a minimal registry with dynamically loaded capabilities."""
    versions = VersionSet.m1a()
    registry = CapabilityRegistry(versions)
    for capability_id, module_path in _CAPABILITY_MODULES.items():
        class_name = _CAPABILITY_CLASSES[capability_id]
        module = importlib.import_module(module_path)
        capability_cls = getattr(module, class_name)
        registry.register_capability(capability_cls())
    registry.seal(frozenset())
    return registry


class _WorkerClock:
    """Clock for use inside the worker subprocess."""

    def utc_now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()


class _WorkerCancellation:
    """Cancellation signal for use inside the worker subprocess."""

    def __init__(self, deadline: float) -> None:
        self._deadline = deadline

    def is_cancelled(self) -> bool:
        return time.monotonic() >= self._deadline


def main(input_data: dict[str, Any]) -> dict[str, Any]:
    """Execute a capability in the worker subprocess.

    Args:
        input_data: dict with keys:
            - capability_id: str
            - contract_version: str
            - canonical_input_json: str (JSON-encoded canonical input)
            - execution_context: dict with attempt_id, randomness, seed, deadline

    Returns:
        dict with keys: result_kind, result_payload, warnings
    """
    capability_id = input_data["capability_id"]
    contract_version = input_data["contract_version"]
    canonical_input = json.loads(input_data["canonical_input_json"])
    exec_ctx = input_data["execution_context"]

    registry = _build_registry()
    capability = registry.resolve(capability_id, contract_version)

    clock = _WorkerClock()
    deadline = exec_ctx["deadline"]
    cancellation = _WorkerCancellation(deadline)

    context = ExecutionContext(
        attempt_id=exec_ctx["attempt_id"],
        randomness=exec_ctx["randomness"],
        seed=exec_ctx["seed"],
        deadline=deadline,
        clock=clock,
        cancellation=cancellation,
    )

    outcome = capability.execute(canonical_input, context)

    result_payload = outcome.result_payload.model_dump(mode="python")
    result_payload = _sanitize_for_json(result_payload)

    return {
        "result_kind": outcome.result_kind,
        "result_payload": result_payload,
        "warnings": [],
    }


def _sanitize_for_json(obj: Any) -> Any:
    """Convert non-JSON-serializable values to JSON-safe equivalents."""
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(v) for v in obj]
    if isinstance(obj, float):
        if obj != obj:
            return None
        if obj == float("inf"):
            return None
        if obj == float("-inf"):
            return None
    return obj


__all__ = ["main"]
