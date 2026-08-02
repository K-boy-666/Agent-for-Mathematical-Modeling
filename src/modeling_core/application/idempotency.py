"""Canonical request identities for the three M1a write use cases."""

from __future__ import annotations

from typing import cast

from modeling_core.contracts.canonical_json import sha256_json
from modeling_core.contracts.capability import CanonicalInputRecord
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.tools import ExecutionOptions

_TOOL_CONTRACT_VERSION = "modeling-tools/0.1.0"


def _request_hash(request: JsonObject) -> str:
    return sha256_json(
        {
            "tool_contract_version": _TOOL_CONTRACT_VERSION,
            "request": request,
        }
    )


def create_project_request_hash(display_name: str) -> str:
    return _request_hash({"display_name": display_name})


def run_experiment_request_hash(
    *,
    project_id: str,
    mode: str,
    capability_id: str,
    contract_version: str,
    canonical_input: CanonicalInputRecord,
    execution: ExecutionOptions,
) -> str:
    return _request_hash(
        {
            "project_id": project_id,
            "mode": mode,
            "capability": {
                "capability_id": capability_id,
                "contract_version": contract_version,
            },
            "canonical_input": cast(
                JsonObject, canonical_input.model_dump(mode="json")
            ),
            "execution": cast(JsonObject, execution.model_dump(mode="json")),
        }
    )


def validate_experiment_request_hash(
    *,
    project_id: str,
    attempt_id: str,
    expected_result_hash: str,
    validator_id: str,
    policy_version: str,
    policy: JsonObject,
    timeout_ms: int,
) -> str:
    return _request_hash(
        {
            "project_id": project_id,
            "attempt_id": attempt_id,
            "expected_result_hash": expected_result_hash,
            "validator_id": validator_id,
            "policy_version": policy_version,
            "policy": policy,
            "timeout_ms": timeout_ms,
        }
    )


__all__ = [
    "create_project_request_hash",
    "run_experiment_request_hash",
    "validate_experiment_request_hash",
]
