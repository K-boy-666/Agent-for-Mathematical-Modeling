"""Global 0.1 warning-count limits at typed and packaged public boundaries."""

from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path

import pytest
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from modeling_core.contracts.common import StrictModel
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.tools import (
    AttemptTrace,
    HealthCheckResult,
    RunExperimentStoppedResult,
)

CORPUS_ROOT = Path(__file__).parent / "corpus" / "tools" / "0.1.0"


def _valid_corpus_result(tool: str) -> dict[str, object]:
    corpus = json.loads((CORPUS_ROOT / f"{tool}.json").read_text(encoding="utf-8"))
    return next(
        item["instance"]
        for item in corpus
        if item["kind"] == "result" and item["label"] == "valid_result"
    )


def _warnings(count: int) -> list[dict[str, str]]:
    return [
        {"code": f"warning_{index}", "message": "bounded warning"}
        for index in range(count)
    ]


def _health_result_with_warning_count(count: int) -> dict[str, object]:
    result = _valid_corpus_result("health_check")
    result["warnings"] = _warnings(count)
    return result


def _attempt_trace_with_warning_count(count: int) -> dict[str, object]:
    entity = "123e4567-e89b-42d3-a456-426614174000"
    timestamp = "2026-07-23T12:34:56.789Z"
    digest = "sha256:" + "a" * 64
    return {
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
        "warnings": _warnings(count),
        "result": None,
        "system_error": None,
        "numerical_failure": None,
        "terminal_reason": None,
    }


def _run_result_with_warning_count(count: int) -> dict[str, object]:
    result = _valid_corpus_result("run_experiment")
    result["warnings"] = _warnings(count)
    return result


def _experiment_status_result_with_warning_count(count: int) -> dict[str, object]:
    entity = "123e4567-e89b-42d3-a456-426614174000"
    timestamp = "2026-07-23T12:34:56.789Z"
    digest = "sha256:" + "a" * 64
    return {
        "tool_contract_version": "modeling-tools/0.1.0",
        "correlation_id": entity,
        "server_time": timestamp,
        "view": "experiment",
        "project": {
            "project_id": entity,
            "display_name": "demo",
            "project_format_version": "modeling-project/0.1.0",
            "project_state": "READY",
            "created_at": timestamp,
        },
        "experiment": {
            "experiment_id": entity,
            "project_id": entity,
            "capability_id": "numerical.root_finding",
            "contract_version": "0.1.0",
            "canonical_input_schema_version": (
                "numerical.root_finding.canonical-input/0.1.0"
            ),
            "canonical_payload": {
                "canonical_input_schema_version": (
                    "numerical.root_finding.canonical-input/0.1.0"
                ),
                "expression_ast": {"kind": "variable", "name": "x"},
                "lower": -1.0,
                "upper": 1.0,
                "absolute_tolerance": 1e-10,
                "relative_tolerance": 1e-10,
                "function_tolerance": 1e-10,
                "max_iterations": 100,
            },
            "canonical_payload_hash": digest,
            "canonicalization_version": "canonical-json/0.1.0",
            "model_snapshot_hash": digest,
            "data_snapshot_references": [],
            "data_snapshot_set_hash": digest,
            "execution_policy": {"timeout_ms": 10000, "seed": None},
            "created_at": timestamp,
        },
        "trace": [_attempt_trace_with_warning_count(count)],
    }


PayloadFactory = Callable[[int], dict[str, object]]
TypedResultModel = type[StrictModel]

_TYPED_WARNING_CASES: tuple[tuple[TypedResultModel, PayloadFactory], ...] = (
    (HealthCheckResult, _health_result_with_warning_count),
    (AttemptTrace, _attempt_trace_with_warning_count),
    (RunExperimentStoppedResult, _run_result_with_warning_count),
)

_SCHEMA_WARNING_CASES: tuple[tuple[str, PayloadFactory], ...] = (
    ("health_check", _health_result_with_warning_count),
    ("get_project_status", _experiment_status_result_with_warning_count),
)

_RUN_TERMINAL_FIELDS: tuple[dict[str, object], ...] = (
    {
        "attempt_status": "SUCCEEDED",
        "result_kind": "success",
        "result_hash": "sha256:" + "a" * 64,
        "result_summary": {
            "root": 0.0,
            "function_value": 0.0,
            "iterations": 0,
            "evaluations": 1,
            "termination_reason": "endpoint_root",
        },
    },
    {
        "attempt_status": "NUMERICAL_FAILURE",
        "result_kind": "numerical_failure",
        "result_hash": "sha256:" + "b" * 64,
        "result_summary": {
            "failure_code": "no_sign_change",
            "iterations": 0,
            "evaluations": 2,
        },
    },
    {
        "attempt_status": "ERRORED",
        "system_error": {
            "error_schema_version": "modeling-error/0.1.0",
            "code": "SECURITY_VIOLATION",
            "message": "forbidden expression",
            "retryable": False,
            "correlation_id": "123e4567-e89b-42d3-a456-426614174000",
            "details": {"rule": "math_expr_forbidden_syntax"},
        },
    },
    {
        "attempt_status": "TIMED_OUT",
        "terminal_reason": "deadline_exceeded",
    },
    {
        "attempt_status": "ABANDONED",
        "terminal_reason": "host_cancelled",
    },
)


def _run_terminal_result_with_warning_count(
    terminal_fields: dict[str, object], count: int
) -> dict[str, object]:
    return {
        "tool_contract_version": "modeling-tools/0.1.0",
        "correlation_id": "123e4567-e89b-42d3-a456-426614174000",
        "server_time": "2026-07-23T12:34:56.789Z",
        "operation_id": "123e4567-e89b-42d3-a456-426614174000",
        "replayed": False,
        "experiment_id": "223e4567-e89b-42d3-a456-426614174000",
        "attempt_id": "323e4567-e89b-42d3-a456-426614174000",
        "capability_id": "numerical.root_finding",
        "contract_version": "0.1.0",
        "implementation_id": "builtin.numerical.root_finding.bisection",
        "implementation_version": "0.1.0",
        "randomness": "not_used",
        "seed": None,
        "warnings": _warnings(count),
        **terminal_fields,
    }


@pytest.mark.parametrize(
    ("model", "make_payload"),
    _TYPED_WARNING_CASES,
    ids=("health_check", "attempt_trace", "run_experiment"),
)
def test_typed_result_rejects_a_fifty_first_warning(
    model: TypedResultModel,
    make_payload: PayloadFactory,
) -> None:
    """Catches any public DTO allowing the global warning-count overflow."""
    model.model_validate_json(json.dumps(make_payload(50)))

    with pytest.raises(PydanticValidationError):
        model.model_validate_json(json.dumps(make_payload(51)))


@pytest.mark.parametrize(
    ("tool", "make_payload"),
    _SCHEMA_WARNING_CASES,
    ids=("health_check", "get_project_status"),
)
def test_packaged_result_schema_rejects_a_fifty_first_warning(
    tool: str,
    make_payload: PayloadFactory,
) -> None:
    """Catches any public Schema advertising an unbounded warning array."""
    validator = SchemaCatalog.load_packaged().validator(tool, "result")
    validator.validate(make_payload(50))

    with pytest.raises(JsonSchemaValidationError):
        validator.validate(make_payload(51))


@pytest.mark.parametrize(
    "terminal_fields",
    _RUN_TERMINAL_FIELDS,
    ids=("succeeded", "numerical_failure", "errored", "timed_out", "abandoned"),
)
def test_run_experiment_schema_rejects_a_fifty_first_warning_in_every_terminal_branch(
    terminal_fields: dict[str, object],
) -> None:
    """Catches removing the warning cap from any separate terminal branch."""
    validator = SchemaCatalog.load_packaged().validator("run_experiment", "result")
    validator.validate(_run_terminal_result_with_warning_count(terminal_fields, 50))

    with pytest.raises(JsonSchemaValidationError):
        validator.validate(_run_terminal_result_with_warning_count(terminal_fields, 51))
