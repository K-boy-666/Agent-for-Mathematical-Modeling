"""B1 stable-contract corpus tests — verify 1.0.0 baseline."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import pytest
from jsonschema import Draft202012Validator

from modeling_core.contracts.errors import TOOL_ERROR_CODES
from modeling_core.contracts.capability import CancellationSignal, ExecutionContext
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.versions import VersionSet
from modeling_core.ports.clock import Clock
from modeling_core.version import M1B_APPLICATION_VERSION
from modeling_capabilities.root_finding.solver import BisectionRootFindingCapability
from modeling_capabilities.root_finding.validator import ResidualRootFindingValidator
from modeling_mcp.adapter import ModelingMcpAdapter
from modeling_core.application.facade import ApplicationFacade
from modeling_core.registry import CapabilityRegistry

ALL_TOOLS = (
    "health_check",
    "create_project",
    "get_project_status",
    "list_capabilities",
    "run_experiment",
    "validate_experiment",
    "register_problem_assets",
    "put_subproblem_mmir",
    "confirm_subproblem_mmir",
    "export_subproblem",
)
KINDS = ("request", "result", "error")
CORPUS_ROOT = Path(__file__).parent / "corpus" / "tools" / "1.0.0"
BASELINE_ROOT = Path(__file__).parent / "baselines"

# Expected $id values for 1.0.0 stable schemas
_COMMON_SCHEMA_IDS = {
    "https://schemas.math-modeling-mcp.local/common/1.0.0/modeling-error.schema.json",
    "https://schemas.math-modeling-mcp.local/common/1.0.0/modeling-project.schema.json",
    "https://schemas.math-modeling-mcp.local/common/1.0.0/modeling-capability.schema.json",
    "https://schemas.math-modeling-mcp.local/common/1.0.0/modeling-validator.schema.json",
    "https://schemas.math-modeling-mcp.local/common/1.0.0/modeling-result.schema.json",
    "https://schemas.math-modeling-mcp.local/common/1.0.0/modeling-validation-report.schema.json",
}

_TOOL_SCHEMA_IDS = {
    f"https://schemas.math-modeling-mcp.local/tools/1.0.0/{tool}.{kind}.schema.json"
    for tool in ALL_TOOLS
    for kind in KINDS
}

_ROOT_FINDING_SCHEMA_IDS = {
    "https://schemas.math-modeling-mcp.local/capabilities/root-finding/1.0.0/input.schema.json",
    "https://schemas.math-modeling-mcp.local/capabilities/root-finding/1.0.0/canonical-input.schema.json",
    "https://schemas.math-modeling-mcp.local/capabilities/root-finding/1.0.0/success-data.schema.json",
    "https://schemas.math-modeling-mcp.local/capabilities/root-finding/1.0.0/failure-data.schema.json",
    "https://schemas.math-modeling-mcp.local/capabilities/root-finding/1.0.0/policy.schema.json",
    "https://schemas.math-modeling-mcp.local/capabilities/root-finding/1.0.0/report.schema.json",
}

ALL_STABLE_IDS = _COMMON_SCHEMA_IDS | _TOOL_SCHEMA_IDS | _ROOT_FINDING_SCHEMA_IDS


class _Clock:
    def monotonic(self) -> float:
        return 0.0

    def utc_now(self) -> object:
        raise AssertionError("solver must not read wall-clock time")


class _Cancellation:
    def is_cancelled(self) -> bool:
        return False


def test_catalog_loads_30_stable_tool_schemas() -> None:
    """Catalog must contain exactly 30 tool schemas (10 tools × 3 kinds)."""
    catalog = SchemaCatalog.load_packaged("1.0.0")
    assert len(catalog.tool_schemas) == 30
    assert catalog.fingerprint.startswith("sha256:")
    assert len(catalog.fingerprint.removeprefix("sha256:")) == 64
    for schema in catalog.tool_schemas.values():
        Draft202012Validator.check_schema(schema)


def test_catalog_loads_6_stable_common_schemas() -> None:
    """Catalog must contain exactly 6 common schemas."""
    catalog = SchemaCatalog.load_packaged("1.0.0")
    assert len(catalog.common_schemas) == 6


def test_all_stable_schema_ids_are_1_0_0() -> None:
    """Every packaged stable schema $id must contain /1.0.0/."""
    catalog = SchemaCatalog.load_packaged("1.0.0")
    for schema in catalog.tool_schemas.values():
        assert "/1.0.0/" in schema["$id"], f"unexpected $id: {schema['$id']}"
    for schema in catalog.common_schemas.values():
        assert "/1.0.0/" in schema["$id"], f"unexpected $id: {schema['$id']}"


def test_stable_tool_ids_match_expected() -> None:
    """Tool schema $id set must match the committed literal expectation."""
    catalog = SchemaCatalog.load_packaged("1.0.0")
    actual = {schema["$id"] for schema in catalog.tool_schemas.values()}
    assert actual == _TOOL_SCHEMA_IDS


def test_stable_common_ids_match_expected() -> None:
    """Common schema $id set must match the committed literal expectation."""
    catalog = SchemaCatalog.load_packaged("1.0.0")
    actual = {schema["$id"] for schema in catalog.common_schemas.values()}
    assert actual == _COMMON_SCHEMA_IDS


def test_version_set_m1b_has_1_0_0_axes() -> None:
    """VersionSet.m1b() must return all 1.0.0 axes and database schema 2."""
    vs = VersionSet.m1b()
    assert vs.application_release == "0.2.0"
    assert vs.application_release == M1B_APPLICATION_VERSION
    assert vs.mcp_protocol_version == "2025-11-25"
    assert vs.tool_contract_version == "modeling-tools/1.0.0"
    assert vs.project_format_version == "modeling-project/1.0.0"
    assert vs.database_schema_version == 2
    assert vs.capability_api_version == "modeling-capability/1.0.0"
    assert vs.error_schema_version == "modeling-error/1.0.0"
    assert vs.result_schema_version == "modeling-result/1.0.0"
    assert vs.validation_report_schema_version == "modeling-validation-report/1.0.0"
    assert vs.canonicalization_version == "canonical-json/1.0.0"
    assert vs.root_finding_contract_version == "numerical.root_finding/1.0.0"
    assert vs.root_finding_canonical_input_version == (
        "numerical.root_finding.canonical-input/1.0.0"
    )
    assert vs.residual_policy_version == "numerical.root_finding.residual/1.0.0"


def test_explicit_stable_adapter_advertises_only_1_0() -> None:
    adapter = ModelingMcpAdapter(
        cast(ApplicationFacade, object()),
        versions=VersionSet.m1b(),
    )

    advertised = json.dumps(
        [tool.model_dump(mode="json") for tool in adapter.list_tools()]
    )
    assert "/1.0.0/" in advertised
    assert "/0.1.0/" not in advertised


def test_explicit_stable_capability_executes_with_one_version_set() -> None:
    versions = VersionSet.m1b()
    capability = BisectionRootFindingCapability(versions=versions)
    canonical_input = capability.normalize_and_validate(
        {"expression": "x - 1", "lower": 0, "upper": 2}
    )
    outcome = capability.execute(
        canonical_input,
        ExecutionContext(
            attempt_id="00000000-0000-4000-8000-000000000001",
            randomness="not_used",
            seed=None,
            deadline=1.0,
            clock=cast(Clock, _Clock()),
            cancellation=cast(CancellationSignal, _Cancellation()),
        ),
    )

    assert (
        capability.descriptor.capability_api_version == versions.capability_api_version
    )
    assert capability.descriptor.contract_version == "1.0.0"
    assert capability.descriptor.validators[0].report_schema_version == (
        versions.validation_report_schema_version
    )
    assert canonical_input.canonical_input_schema_version == (
        versions.root_finding_canonical_input_version
    )
    assert (
        outcome.result_payload.result_schema_version == versions.result_schema_version
    )
    assert outcome.result_payload.contract_version == "1.0.0"

    registry = CapabilityRegistry(versions)
    registry.register_capability(capability)
    registry.register_validator(ResidualRootFindingValidator(versions))
    summary = registry.seal(frozenset({("numerical.root_finding", "1.0.0")}))
    assert summary.capability_count == 1
    assert (
        registry.resolve_validator(
            "numerical.root_finding.residual",
            "numerical.root_finding",
            "1.0.0",
            "1.0.0",
        ).descriptor.policy_version
        == "1.0.0"
    )


def test_tool_names_unchanged_from_0_1() -> None:
    """The 10 tool names must be identical to the 0.1.0 set."""
    from modeling_core.contracts.tools import TOOL_NAMES

    assert TOOL_NAMES == ALL_TOOLS


def test_0_1_catalog_still_loadable() -> None:
    """0.1.0 archival preview contracts must remain loadable."""
    catalog = SchemaCatalog.load_packaged("0.1.0")
    assert len(catalog.tool_schemas) == 30
    assert len(catalog.common_schemas) == 6


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_each_stable_tool_corpus_exercises_required_kinds(tool: str) -> None:
    """Each tool's 1.0.0 corpus must have valid/invalid cases for all 3 kinds."""
    catalog = SchemaCatalog.load_packaged("1.0.0")
    corpus = json.loads((CORPUS_ROOT / f"{tool}.json").read_text(encoding="utf-8"))
    labels = {(case["kind"], case["valid"], case["label"]) for case in corpus}
    for kind in KINDS:
        assert any(case_kind == kind and valid for case_kind, valid, _ in labels), (
            f"missing valid {kind} case for {tool}"
        )
    assert any(not valid and label == "unknown_field" for _, valid, label in labels), (
        f"missing unknown_field case for {tool}"
    )
    assert any(not valid and label == "invalid_type" for _, valid, label in labels), (
        f"missing invalid_type case for {tool}"
    )

    for case in corpus:
        errors = list(
            catalog.validator(tool, case["kind"]).iter_errors(case["instance"])
        )
        assert bool(errors) is not case["valid"], case["label"]


@pytest.mark.parametrize("tool", ALL_TOOLS)
def test_stable_error_corpus_uses_only_tool_allowlist(tool: str) -> None:
    """Error codes in 1.0.0 corpus must be from the tool's allowlist."""
    corpus = json.loads((CORPUS_ROOT / f"{tool}.json").read_text(encoding="utf-8"))
    error_codes = {
        case["instance"]["code"]
        for case in corpus
        if case["kind"] == "error" and case["valid"]
    }
    assert error_codes
    assert error_codes <= TOOL_ERROR_CODES[tool]


def test_get_project_status_cursor_and_limit() -> None:
    """1.0.0 get_project_status must support cursor and limit."""
    catalog = SchemaCatalog.load_packaged("1.0.0")

    # limit must be accepted
    validator = catalog.validator("get_project_status", "request")
    valid_with_limit = {
        "project_id": "00000000-0000-4000-8000-000000000001",
        "view": "summary",
        "limit": 50,
    }
    assert list(validator.iter_errors(valid_with_limit)) == []

    # limit 0 must be rejected
    assert list(validator.iter_errors({**valid_with_limit, "limit": 0}))

    # limit 101 must be rejected
    assert list(validator.iter_errors({**valid_with_limit, "limit": 101}))

    # cursor must be accepted for experiment view
    valid_with_cursor = {
        "project_id": "00000000-0000-4000-8000-000000000001",
        "view": "experiment",
        "experiment_id": "00000000-0000-4000-8000-000000000002",
        "cursor": "opaque-cursor-123",
    }
    assert list(validator.iter_errors(valid_with_cursor)) == []

    # cursor must be rejected for summary view
    assert list(
        validator.iter_errors(
            {
                "project_id": "00000000-0000-4000-8000-000000000001",
                "cursor": "opaque",
            }
        )
    )


def test_run_experiment_mode_rerun_requires_experiment_id() -> None:
    """1.0.0 run_experiment mode="rerun" must require experiment_id."""
    catalog = SchemaCatalog.load_packaged("1.0.0")
    validator = catalog.validator("run_experiment", "request")

    base = {
        "operation_id": "00000000-0000-4000-8000-000000000001",
        "project_id": "00000000-0000-4000-8000-000000000002",
        "capability": {
            "capability_id": "numerical.root_finding",
            "contract_version": "1.0.0",
        },
        "payload": {
            "expression": "x**2 - 4",
            "lower": 0,
            "upper": 3,
        },
    }

    # mode="new" must be accepted
    assert list(validator.iter_errors({**base, "mode": "new"})) == []

    # mode="rerun" without experiment_id must be rejected
    assert list(validator.iter_errors({**base, "mode": "rerun"}))

    # mode="rerun" with experiment_id must be accepted
    assert (
        list(
            validator.iter_errors(
                {
                    **base,
                    "mode": "rerun",
                    "experiment_id": "00000000-0000-4000-8000-000000000003",
                }
            )
        )
        == []
    )

    # mode="new" with experiment_id must be rejected
    assert list(
        validator.iter_errors(
            {
                **base,
                "mode": "new",
                "experiment_id": "00000000-0000-4000-8000-000000000003",
            }
        )
    )


def test_artifact_manifest_in_stable_result() -> None:
    """1.0.0 result schemas must reference 1.0.0 common schemas."""
    catalog = SchemaCatalog.load_packaged("1.0.0")

    for kind in ("result",):
        schema = catalog.for_tool("run_experiment", kind)
        schema_json = json.dumps(schema)
        # Must reference 1.0.0 common schemas, not 0.1.0
        assert "common/1.0.0" in schema_json
        assert "common/0.1.0" not in schema_json

    digest = "a" * 64
    artifact = {
        "artifact_id": f"sha256:{digest}",
        "role": "result",
        "sha256": f"sha256:{digest}",
        "media_type": "application/json",
        "size_bytes": 12,
        "project_relative_path": (
            f".modeling/artifacts/sha256/{digest[:2]}/{digest}.json"
        ),
    }
    run_result = {
        "tool_contract_version": "modeling-tools/1.0.0",
        "correlation_id": "123e4567-e89b-42d3-a456-426614174000",
        "server_time": "2026-07-23T12:34:56.789Z",
        "operation_id": "123e4567-e89b-42d3-a456-426614174000",
        "replayed": False,
        "experiment_id": "223e4567-e89b-42d3-a456-426614174000",
        "attempt_id": "323e4567-e89b-42d3-a456-426614174000",
        "attempt_status": "SUCCEEDED",
        "capability_id": "numerical.root_finding",
        "contract_version": "1.0.0",
        "implementation_id": "builtin.numerical.root_finding.bisection",
        "implementation_version": "0.1.0",
        "randomness": "not_used",
        "seed": None,
        "warnings": [],
        "result_kind": "success",
        "result_hash": f"sha256:{digest}",
        "result_summary": {
            "root": 1.0,
            "function_value": 0.0,
            "iterations": 1,
            "evaluations": 3,
            "termination_reason": "residual_tolerance",
        },
        "artifacts": [artifact],
    }
    validator = catalog.validator("run_experiment", "result")
    assert list(validator.iter_errors(run_result)) == []
    assert list(
        validator.iter_errors({k: v for k, v in run_result.items() if k != "artifacts"})
    )

    report_artifact = {
        **artifact,
        "role": "validation_report",
    }
    validation_result = {
        "tool_contract_version": "modeling-tools/1.0.0",
        "correlation_id": "123e4567-e89b-42d3-a456-426614174000",
        "server_time": "2026-07-23T12:34:56.789Z",
        "operation_id": "123e4567-e89b-42d3-a456-426614174000",
        "replayed": False,
        "validation_id": "223e4567-e89b-42d3-a456-426614174000",
        "attempt_id": "323e4567-e89b-42d3-a456-426614174000",
        "result_hash": f"sha256:{digest}",
        "validator_id": "numerical.root_finding.residual",
        "validator_implementation_id": "builtin.numerical.root_finding.residual",
        "validator_implementation_version": "0.1.0",
        "policy_version": "1.0.0",
        "policy_hash": f"sha256:{digest}",
        "validation_status": "SUCCEEDED",
        "outcome": "PASSED",
        "metrics": {
            "root_within_interval": True,
            "reported_function_value": 0.0,
            "recomputed_function_value": 0.0,
            "absolute_reported_delta": 0.0,
            "absolute_residual": 0.0,
            "function_tolerance": 1e-10,
            "failed_checks": [],
        },
        "validation_report_hash": f"sha256:{digest}",
        "report_artifact": report_artifact,
    }
    validator = catalog.validator("validate_experiment", "result")
    assert list(validator.iter_errors(validation_result)) == []
    assert list(
        validator.iter_errors(
            {k: v for k, v in validation_result.items() if k != "report_artifact"}
        )
    )


def test_baseline_manifests_exist_and_are_valid() -> None:
    """Baseline manifests must exist, be valid JSON, and contain expected keys."""
    for baseline_name in (
        "modeling-tools-1.0.0.json",
        "modeling-capability-1.0.0.json",
    ):
        path = BASELINE_ROOT / baseline_name
        assert path.is_file(), f"baseline {baseline_name} missing"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(manifest, list)
        for entry in manifest:
            assert "path" in entry
            assert "$id" in entry
            assert "sha256" in entry
            assert "kind" in entry
