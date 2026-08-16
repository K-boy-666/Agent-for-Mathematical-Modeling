"""B1 stable-contract corpus tests — verify 1.0.0 baseline."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from modeling_core.contracts.errors import TOOL_ERROR_CODES
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.versions import VersionSet
from modeling_core.version import M1B_APPLICATION_VERSION

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
