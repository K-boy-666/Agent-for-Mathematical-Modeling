from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from modeling_core.contracts.errors import TOOL_ERROR_CODES
from modeling_core.contracts.schema_catalog import SchemaCatalog

TOOLS = (
    "health_check",
    "create_project",
    "get_project_status",
    "list_capabilities",
    "run_experiment",
    "validate_experiment",
)
KINDS = ("request", "result", "error")
CORPUS_ROOT = Path(__file__).parent / "corpus" / "tools" / "0.1.0"


def test_catalog_contains_18_meta_valid_tool_schemas() -> None:
    catalog = SchemaCatalog.load_packaged("0.1.0")
    assert len(catalog.tool_schemas) == 30
    assert catalog.fingerprint.startswith("sha256:")
    for schema in catalog.tool_schemas.values():
        Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("tool", TOOLS)
def test_each_tool_corpus_exercises_required_valid_and_invalid_cases(
    tool: str,
) -> None:
    catalog = SchemaCatalog.load_packaged("0.1.0")
    corpus = json.loads((CORPUS_ROOT / f"{tool}.json").read_text(encoding="utf-8"))
    labels = {(case["kind"], case["valid"], case["label"]) for case in corpus}
    for kind in KINDS:
        assert any(case_kind == kind and valid for case_kind, valid, _ in labels)
    assert any(not valid and label == "unknown_field" for _, valid, label in labels)
    assert any(not valid and label == "invalid_type" for _, valid, label in labels)

    for case in corpus:
        errors = list(
            catalog.validator(tool, case["kind"]).iter_errors(case["instance"])
        )
        assert bool(errors) is not case["valid"], case["label"]


@pytest.mark.parametrize("tool", TOOLS)
def test_error_corpus_uses_only_the_tool_allowlist(tool: str) -> None:
    corpus = json.loads((CORPUS_ROOT / f"{tool}.json").read_text(encoding="utf-8"))
    error_codes = {
        case["instance"]["code"]
        for case in corpus
        if case["kind"] == "error" and case["valid"]
    }
    assert error_codes
    assert error_codes <= TOOL_ERROR_CODES[tool]


def _experiment_result_with_trace(trace: dict[str, object]) -> dict[str, object]:
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
        "trace": [trace],
    }


def _attempt_trace() -> dict[str, object]:
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
        "warnings": [],
        "result": None,
        "system_error": None,
        "numerical_failure": None,
        "terminal_reason": None,
    }


def _validation_trace() -> dict[str, object]:
    entity = "123e4567-e89b-42d3-a456-426614174000"
    timestamp = "2026-07-23T12:34:56.789Z"
    digest = "sha256:" + "a" * 64
    return {
        "record_type": "validation",
        "validation_id": entity,
        "attempt_id": entity,
        "expected_result_hash": digest,
        "result_hash": digest,
        "validator_id": "numerical.root_finding.residual",
        "validator_implementation_id": "builtin.numerical.root_finding.residual",
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("environment_summary", {"unexpected": True}),
        ("warnings", [{}]),
        ("status", "SUCCEEDED"),
    ],
)
def test_attempt_trace_schema_rejects_loose_or_inconsistent_values(
    field: str, value: object
) -> None:
    trace = _attempt_trace()
    trace[field] = value
    errors = list(
        SchemaCatalog.load_packaged("0.1.0")
        .validator("get_project_status", "result")
        .iter_errors(_experiment_result_with_trace(trace))
    )
    assert errors


def test_validation_trace_schema_enforces_succeeded_output_matrix() -> None:
    errors = list(
        SchemaCatalog.load_packaged("0.1.0")
        .validator("get_project_status", "result")
        .iter_errors(_experiment_result_with_trace(_validation_trace()))
    )
    assert errors
