from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from math import inf, nan

import pytest
from pydantic import TypeAdapter, ValidationError

from modeling_core.contracts.canonical_json import (
    canonical_json_bytes,
    sha256_json,
    strict_json_loads,
)
from modeling_core.contracts.common import (
    EntityId,
    Hash,
    StrictModel,
    Timestamp,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.contracts.tools import (
    AttemptTrace,
    GetProjectStatusRequest,
    GetProjectStatusSummaryRequest,
    ListCapabilitiesRequest,
    ListCapabilitiesSummaryRequest,
    ResultTrace,
    UnaryNode,
    ValidateExperimentRequest,
    ValidationTrace,
)


class _StrictProbe(StrictModel):
    count: int
    ratio: float


@pytest.mark.parametrize(
    "value",
    [
        "123e4567-e89b-42d3-a456-426614174000",
        "00000000-0000-4000-8000-000000000000",
    ],
)
def test_entity_ids_accept_lowercase_uuid_v4(value: str) -> None:
    assert TypeAdapter(EntityId).validate_python(value, strict=True) == value


@pytest.mark.parametrize(
    "value",
    [
        "123E4567-E89B-42D3-A456-426614174000",
        "123e4567-e89b-12d3-a456-426614174000",
        "not-a-uuid",
    ],
)
def test_entity_ids_reject_noncanonical_values(value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(EntityId).validate_python(value, strict=True)


@pytest.mark.parametrize(
    ("adapter_type", "valid", "invalid"),
    [
        (
            Hash,
            "sha256:" + "a" * 64,
            "sha256:" + "A" * 64,
        ),
        (
            Timestamp,
            "2026-07-23T12:34:56.789Z",
            "2026-07-23T12:34:56Z",
        ),
    ],
)
def test_hash_and_timestamp_formats(
    adapter_type: object, valid: str, invalid: str
) -> None:
    adapter = TypeAdapter(adapter_type)
    assert adapter.validate_python(valid, strict=True) == valid
    with pytest.raises(ValidationError):
        adapter.validate_python(invalid, strict=True)


@pytest.mark.parametrize(
    "value",
    [
        "2026-07-23T12:34:56.789+00:00",
        "2026-07-23T20:34:56.789+08:00",
        datetime(2026, 7, 23, 12, 34, 56, 789000),
    ],
)
def test_timestamps_require_millisecond_z_strings(value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Timestamp).validate_python(value, strict=True)


def test_strict_models_forbid_extras_coercion_nonfinite_and_mutation() -> None:
    probe = _StrictProbe(count=1, ratio=1.5)
    with pytest.raises(ValidationError):
        _StrictProbe.model_validate({"count": "1", "ratio": 1.5})
    with pytest.raises(ValidationError):
        _StrictProbe.model_validate({"count": 1, "ratio": nan})
    with pytest.raises(ValidationError):
        _StrictProbe.model_validate({"count": 1, "ratio": inf})
    with pytest.raises(ValidationError):
        _StrictProbe.model_validate({"count": 1, "ratio": 1.5, "extra": True})
    with pytest.raises(ValidationError):
        probe.count = 2


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":"\\ud800"}',
        b"\xff",
    ],
)
def test_strict_json_rejects_ambiguous_or_invalid_input(payload: bytes) -> None:
    with pytest.raises(ValueError):
        strict_json_loads(payload)


def test_fixed_hash_vectors() -> None:
    assert (
        sha256_json([])
        == "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    )
    assert (
        sha256_json({})
        == "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
    assert canonical_json_bytes({"b": 1.0, "a": -0.0}) == b'{"a":0,"b":1}'
    assert (
        sha256_json({"b": 1.0, "a": -0.0})
        == "sha256:f4c1d8bd90d7ccd720aa5a69a67185fb9caf4f35926a4eacf53a86d0e70bdf88"
    )


def test_canonicalization_is_repeatable_in_a_fresh_process() -> None:
    code = (
        "import json;"
        "from modeling_core.contracts.canonical_json import canonical_json_bytes,sha256_json;"
        "v={'e\\u0301':'e\\u0301','n':-0.0};"
        "print(json.dumps([canonical_json_bytes(v).decode(),sha256_json(v)]))"
    )
    expected = subprocess.check_output(
        [sys.executable, "-c", code], text=True, encoding="utf-8"
    ).strip()
    assert expected == subprocess.check_output(
        [sys.executable, "-c", code], text=True, encoding="utf-8"
    ).strip()
    assert json.loads(expected)[0] == '{"n":0,"é":"é"}'


def test_m1a_version_axes_are_exact() -> None:
    versions = VersionSet.m1a()
    assert versions.model_dump() == {
        "application_release": "0.1.0",
        "mcp_protocol_version": "2025-11-25",
        "tool_contract_version": "modeling-tools/0.1.0",
        "project_format_version": "modeling-project/0.1.0",
        "database_schema_version": 1,
        "capability_api_version": "modeling-capability/0.1.0",
        "error_schema_version": "modeling-error/0.1.0",
        "result_schema_version": "modeling-result/0.1.0",
        "validation_report_schema_version": "modeling-validation-report/0.1.0",
        "canonicalization_version": "canonical-json/0.1.0",
        "root_finding_contract_version": "numerical.root_finding/0.1.0",
        "root_finding_canonical_input_version": (
            "numerical.root_finding.canonical-input/0.1.0"
        ),
        "residual_policy_version": "numerical.root_finding.residual/0.1.0",
    }


def test_recursive_json_payload_is_fully_resolved_and_validated() -> None:
    request = ValidateExperimentRequest.model_validate(
        {
            "operation_id": "123e4567-e89b-42d3-a456-426614174000",
            "project_id": "223e4567-e89b-42d3-a456-426614174000",
            "attempt_id": "323e4567-e89b-42d3-a456-426614174000",
            "expected_result_hash": "sha256:" + "a" * 64,
            "validator_id": "numerical.root_finding.residual",
            "policy_version": "0.1.0",
            "policy": {"nested": [None, True, 2, 3.5, "value", {"leaf": "ok"}]},
        }
    )
    assert request.policy["nested"][-1] == {"leaf": "ok"}
    invalid = request.model_dump()
    invalid["policy"] = {"value": nan}
    with pytest.raises(ValidationError):
        ValidateExperimentRequest.model_validate(invalid)


def test_omitted_summary_discriminators_apply_documented_defaults() -> None:
    project = TypeAdapter(GetProjectStatusRequest).validate_python(
        {"project_id": "123e4567-e89b-42d3-a456-426614174000"}
    )
    capabilities = TypeAdapter(ListCapabilitiesRequest).validate_python({})
    assert isinstance(project, GetProjectStatusSummaryRequest)
    assert project.view == "summary"
    assert isinstance(capabilities, ListCapabilitiesSummaryRequest)
    assert capabilities.detail == "summary"


def test_attempt_trace_dto_enforces_terminal_output_matrix() -> None:
    entity = "123e4567-e89b-42d3-a456-426614174000"
    timestamp = "2026-07-23T12:34:56.789Z"
    digest = "sha256:" + "a" * 64
    with pytest.raises(ValidationError):
        AttemptTrace.model_validate(
            {
                "record_type": "attempt",
                "attempt_id": entity,
                "experiment_id": entity,
                "implementation_id": "builtin.numerical.root_finding.bisection",
                "implementation_version": "0.1.0",
                "environment_summary": {
                    "python_version": "3.11.14",
                    "application_version": "0.1.0",
                    "lock_hash": digest,
                },
                "randomness": "not_used",
                "seed": None,
                "session_id": entity,
                "status": "PENDING",
                "created_at": timestamp,
                "started_at": None,
                "finished_at": None,
                "warnings": (),
                "result": {
                    "result_snapshot_id": entity,
                    "result_kind": "success",
                    "result_schema_version": "modeling-result/0.1.0",
                    "result_hash": digest,
                    "result_payload": {
                        "result_schema_version": "modeling-result/0.1.0",
                        "capability_id": "numerical.root_finding",
                        "contract_version": "0.1.0",
                        "result_kind": "success",
                        "data": {
                            "root": 0.0,
                            "function_value": 0.0,
                            "iterations": 0,
                            "evaluations": 1,
                            "termination_reason": "endpoint_root",
                        },
                    },
                },
                "system_error": None,
                "numerical_failure": None,
                "terminal_reason": None,
            }
        )


def test_validation_trace_dto_enforces_terminal_output_matrix() -> None:
    entity = "123e4567-e89b-42d3-a456-426614174000"
    timestamp = "2026-07-23T12:34:56.789Z"
    digest = "sha256:" + "a" * 64
    with pytest.raises(ValidationError):
        ValidationTrace.model_validate(
            {
                "record_type": "validation",
                "validation_id": entity,
                "attempt_id": entity,
                "expected_result_hash": digest,
                "result_hash": digest,
                "validator_id": "numerical.root_finding.residual",
                "validator_implementation_id": (
                    "builtin.numerical.root_finding.residual"
                ),
                "validator_implementation_version": "0.1.0",
                "policy_version": "0.1.0",
                "policy": {},
                "policy_hash": digest,
                "status": "SUCCEEDED",
                "created_at": timestamp,
                "started_at": timestamp,
                "finished_at": timestamp,
                "outcome": None,
                "metrics": None,
                "validation_report_hash": None,
                "report_payload": None,
                "operational_error": None,
                "terminal_reason": None,
            }
        )


def test_validation_trace_dto_rejects_non_empty_m1a_policy() -> None:
    entity = "123e4567-e89b-42d3-a456-426614174000"
    timestamp = "2026-07-23T12:34:56.789Z"
    digest = "sha256:" + "a" * 64
    with pytest.raises(ValidationError, match="M1a residual policy must be empty"):
        ValidationTrace.model_validate(
            {
                "record_type": "validation",
                "validation_id": entity,
                "attempt_id": entity,
                "expected_result_hash": digest,
                "result_hash": digest,
                "validator_id": "numerical.root_finding.residual",
                "validator_implementation_id": (
                    "builtin.numerical.root_finding.residual"
                ),
                "validator_implementation_version": "0.1.0",
                "policy_version": "0.1.0",
                "policy": {"unexpected": True},
                "policy_hash": digest,
                "status": "PENDING",
                "created_at": timestamp,
                "started_at": None,
                "finished_at": None,
                "outcome": None,
                "metrics": None,
                "validation_report_hash": None,
                "report_payload": None,
                "operational_error": None,
                "terminal_reason": None,
            }
        )


def test_result_trace_dto_rejects_mismatched_result_kinds() -> None:
    entity = "123e4567-e89b-42d3-a456-426614174000"
    digest = "sha256:" + "a" * 64
    with pytest.raises(ValidationError):
        ResultTrace.model_validate(
            {
                "result_snapshot_id": entity,
                "result_kind": "success",
                "result_schema_version": "modeling-result/0.1.0",
                "result_hash": digest,
                "result_payload": {
                    "result_schema_version": "modeling-result/0.1.0",
                    "capability_id": "numerical.root_finding",
                    "contract_version": "0.1.0",
                    "result_kind": "numerical_failure",
                    "data": {
                        "failure_code": "no_sign_change",
                        "iterations": 0,
                        "evaluations": 2,
                    },
                },
            }
        )


def test_recursive_expression_ast_models_are_fully_resolved() -> None:
    value = UnaryNode.model_validate(
        {
            "kind": "unary",
            "op": "negative",
            "operand": {
                "kind": "binary",
                "op": "add",
                "left": {"kind": "variable", "name": "x"},
                "right": {
                    "kind": "call",
                    "name": "sin",
                    "argument": {"kind": "number", "value": 1.0},
                },
            },
        }
    )
    assert value.operand.kind == "binary"
