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
    assert len(catalog.tool_schemas) == 18
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
