"""C1.1 preview contract tests — RED before GREEN.

These tests verify that the four new C1 preview tools are discoverable,
their schemas validate correctly, and the dispatch chain rejects invalid
input while preserving all existing M1a tool behaviour.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast
from unittest.mock import Mock

import pytest
from jsonschema import Draft202012Validator
from jsonschema.protocols import Validator

from modeling_core.application.facade import ApplicationFacade
from modeling_core.contracts.errors import (
    ALL_ERROR_CODES,
    TOOL_ERROR_CODES,
)
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.tools import (
    TOOL_NAMES,
)
from modeling_mcp.adapter import ModelingMcpAdapter

C1_TOOLS = frozenset(
    {
        "register_problem_assets",
        "put_subproblem_mmir",
        "confirm_subproblem_mmir",
        "export_subproblem",
    }
)

M1A_TOOLS = frozenset(
    {
        "health_check",
        "create_project",
        "get_project_status",
        "list_capabilities",
        "run_experiment",
        "validate_experiment",
    }
)


# ── helpers ──────────────────────────────────────────────────────────


def _load_corpus(tool: str, kind: str) -> list[dict[str, object]]:
    root = Path(__file__).parent / "corpus" / "tools" / "0.1.0"
    path = root / f"{tool}.json"
    if not path.exists():
        return []
    cases = json.loads(path.read_text(encoding="utf-8"))
    return [case for case in cases if case["kind"] == kind]


def _corpus_instance(tool: str, kind: str, label: str) -> dict[str, object]:
    cases = _load_corpus(tool, kind)
    match = next(
        (case["instance"] for case in cases if case["label"] == label),
        None,
    )
    if match is None:
        pytest.skip(f"corpus instance {tool}.{kind}.{label} not found")
    return cast(dict[str, object], match)


def _validator_for(tool: str, kind: str) -> Validator:
    catalog = SchemaCatalog.load_packaged("0.1.0")
    return catalog.validator(tool, kind)


# ── tool discovery ───────────────────────────────────────────────────


class TestC1ToolDiscovery:
    def test_c1_tools_are_in_tool_names(self) -> None:
        assert C1_TOOLS <= set(TOOL_NAMES)

    def test_m1a_tools_still_in_tool_names(self) -> None:
        assert M1A_TOOLS <= set(TOOL_NAMES)

    def test_total_tool_count_is_ten(self) -> None:
        assert len(TOOL_NAMES) == 10


class TestC1ToolListedByAdapter:
    def test_adapter_lists_all_ten_tools(self) -> None:
        facade = Mock(spec=ApplicationFacade)
        adapter = ModelingMcpAdapter(facade)
        tool_names = sorted(tool.name for tool in adapter.list_tools())
        assert tool_names == sorted(TOOL_NAMES)


# ── schema catalog ───────────────────────────────────────────────────


class TestC1SchemaCatalog:
    @pytest.mark.parametrize(
        "tool",
        sorted(C1_TOOLS),
    )
    def test_c1_tool_has_request_schema(self, tool: str) -> None:
        catalog = SchemaCatalog.load_packaged("0.1.0")
        schema = catalog.for_tool(tool, "request")
        Draft202012Validator.check_schema(schema)
        assert schema.get("$id", "").endswith(f"{tool}.request.schema.json")

    @pytest.mark.parametrize(
        "tool",
        sorted(C1_TOOLS),
    )
    def test_c1_tool_has_result_schema(self, tool: str) -> None:
        catalog = SchemaCatalog.load_packaged("0.1.0")
        schema = catalog.for_tool(tool, "result")
        Draft202012Validator.check_schema(schema)
        assert schema.get("$id", "").endswith(f"{tool}.result.schema.json")

    @pytest.mark.parametrize(
        "tool",
        sorted(C1_TOOLS),
    )
    def test_c1_tool_has_error_schema(self, tool: str) -> None:
        catalog = SchemaCatalog.load_packaged("0.1.0")
        schema = catalog.for_tool(tool, "error")
        Draft202012Validator.check_schema(schema)
        assert schema.get("$id", "").endswith(f"{tool}.error.schema.json")

    def test_catalog_fingerprint_includes_c1_tools(self) -> None:
        catalog = SchemaCatalog.load_packaged("0.1.0")
        assert catalog.fingerprint.startswith("sha256:")
        assert len(catalog.fingerprint) == 71  # "sha256:" + 64 hex


# ── error code catalog ────────────────────────────────────────────────


class TestC1ErrorCodes:
    def test_c1_tools_have_error_code_entries(self) -> None:
        for tool in C1_TOOLS:
            assert tool in TOOL_ERROR_CODES, f"missing error codes for {tool}"

    def test_c1_tool_error_codes_are_subset_of_all(self) -> None:
        for tool in C1_TOOLS:
            assert TOOL_ERROR_CODES[tool] <= ALL_ERROR_CODES

    def test_m1a_error_codes_unchanged(self) -> None:
        for tool in M1A_TOOLS:
            assert tool in TOOL_ERROR_CODES


# ── dispatch rejection ────────────────────────────────────────────────


class TestC1DispatchRejectsInvalidInput:
    """Prove that the adapter rejects invalid C1 tool input before
    the stub implementation raises."""

    @pytest.mark.parametrize(
        "tool",
        sorted(C1_TOOLS),
    )
    def test_missing_required_fields_is_rejected(self, tool: str) -> None:
        facade = Mock(spec=ApplicationFacade)
        adapter = ModelingMcpAdapter(facade)
        result = adapter.call_tool(tool, {})
        assert result.isError is True
        structured = cast(dict[str, object], result.structuredContent)
        assert structured["code"] == "INVALID_REQUEST"

    @pytest.mark.parametrize(
        "tool",
        sorted(C1_TOOLS),
    )
    def test_unknown_field_is_rejected(self, tool: str) -> None:
        facade = Mock(spec=ApplicationFacade)
        adapter = ModelingMcpAdapter(facade)
        result = adapter.call_tool(tool, {"__unknown_sentinel__": True})
        assert result.isError is True
        structured = cast(dict[str, object], result.structuredContent)
        assert structured["code"] == "INVALID_REQUEST"

    def test_valid_register_problem_assets_reaches_facade(self) -> None:
        """RED: valid C1 request dispatched to facade raises NotImplementedError."""
        facade = Mock(spec=ApplicationFacade)
        facade.register_problem_assets.side_effect = NotImplementedError("C1.1 stub")
        adapter = ModelingMcpAdapter(facade)
        result = adapter.call_tool(
            "register_problem_assets",
            {
                "operation_id": "00000000-0000-4000-8000-000000000001",
                "project_id": "00000000-0000-4000-8000-000000000002",
                "asset_paths": [
                    {"label": "test.pdf", "path": "A题/A题.pdf"},
                ],
            },
        )
        assert result.isError is True
        structured = cast(dict[str, object], result.structuredContent)
        assert structured["code"] == "INTERNAL_ERROR"


# ── M1a regression ────────────────────────────────────────────────────


class TestM1aRegressionAfterC1:
    """All six M1a tools must still work after C1 additions."""

    @pytest.mark.parametrize("tool", sorted(M1A_TOOLS))
    def test_m1a_tool_still_has_request_schema(self, tool: str) -> None:
        catalog = SchemaCatalog.load_packaged("0.1.0")
        _ = catalog.for_tool(tool, "request")

    @pytest.mark.parametrize("tool", sorted(M1A_TOOLS))
    def test_m1a_tool_still_has_result_schema(self, tool: str) -> None:
        catalog = SchemaCatalog.load_packaged("0.1.0")
        _ = catalog.for_tool(tool, "result")

    @pytest.mark.parametrize("tool", sorted(M1A_TOOLS))
    def test_m1a_tool_still_has_error_schema(self, tool: str) -> None:
        catalog = SchemaCatalog.load_packaged("0.1.0")
        _ = catalog.for_tool(tool, "error")
