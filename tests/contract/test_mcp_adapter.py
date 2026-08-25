from __future__ import annotations

import copy
import hashlib
import io
import importlib.util
import json
from pathlib import Path
import sys
import tomllib
from typing import cast
from unittest.mock import Mock

import anyio
import pytest
from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    ValidationError,
    validate,
)
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.shared.message import SessionMessage
from mcp.types import (
    LATEST_PROTOCOL_VERSION,
    CallToolRequest,
    CallToolRequestParams,
    CallToolResult,
    JSONRPCMessage,
    TextContent,
    Tool,
)
from pydantic import TypeAdapter

from modeling_core.application.facade import ApplicationFacade
from modeling_core.contracts.canonical_json import canonical_json_bytes
from modeling_core.contracts.errors import ErrorResponse, ModelingError
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.tools import (
    TOOL_NAMES,
    CreateProjectRequest,
    CreateProjectResult,
    GetProjectStatusRequest,
    GetProjectStatusResult,
    HealthCheckRequest,
    HealthCheckResult,
    ListCapabilitiesRequest,
    ListCapabilitiesResult,
    RunExperimentRequest,
    RunExperimentResult,
    RunExperimentSucceededResult,
    ValidateExperimentRequest,
    ValidateExperimentResult,
)
from modeling_mcp import adapter as adapter_module
from modeling_mcp.adapter import ModelingMcpAdapter
from modeling_mcp.server import (
    APPLICATION_VERSION,
    MCP_PROTOCOL_VERSION,
    configure_mcp_server,
)
from modeling_mcp.strict_stdio import strict_stdio_server

CORPUS_ROOT = Path(__file__).parent / "corpus" / "tools" / "0.1.0"


def _corpus_instance(tool: str, kind: str, label: str) -> dict[str, object]:
    cases = json.loads((CORPUS_ROOT / f"{tool}.json").read_text(encoding="utf-8"))
    return next(
        case["instance"]
        for case in cases
        if case["kind"] == kind and case["label"] == label
    )


def _corpus_cases(tool: str, kind: str) -> list[dict[str, object]]:
    cases = json.loads((CORPUS_ROOT / f"{tool}.json").read_text(encoding="utf-8"))
    return [case for case in cases if case["kind"] == kind]


def _schema_references(value: object) -> list[str]:
    references: list[str] = []
    if isinstance(value, dict):
        reference = value.get("$ref")
        if isinstance(reference, str):
            references.append(reference)
        for nested in value.values():
            references.extend(_schema_references(nested))
    elif isinstance(value, list):
        for nested in value:
            references.extend(_schema_references(nested))
    return references


def _call_through_low_level_sdk(
    adapter: ModelingMcpAdapter,
    name: str,
    arguments: dict[str, object],
) -> CallToolResult:
    server = Server[object, object](
        name="math-modeling-mcp",
        version=APPLICATION_VERSION,
    )
    configure_mcp_server(adapter, server)

    async def call() -> CallToolResult:
        handler = server.request_handlers[CallToolRequest]
        response = await handler(
            CallToolRequest(
                params=CallToolRequestParams(name=name, arguments=arguments)
            )
        )
        assert isinstance(response.root, CallToolResult)
        return response.root

    return anyio.run(call)


def test_tools_list_exposes_exactly_the_six_approved_names_in_order() -> None:
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, object()))

    assert tuple(tool.name for tool in adapter.list_tools()) == TOOL_NAMES


def test_advertised_request_and_result_schemas_are_offline_self_contained() -> None:
    catalog = SchemaCatalog.load_packaged()
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, object()))

    for tool in adapter.list_tools():
        corpus_path = CORPUS_ROOT / f"{tool.name}.json"
        if not corpus_path.is_file():
            continue
        for kind, schema in (
            ("request", tool.inputSchema),
            ("result", tool.outputSchema),
        ):
            assert schema is not None
            canonical_schema = catalog.for_tool(tool.name, kind)
            assert schema["$schema"] == canonical_schema["$schema"]
            assert schema["$id"] == canonical_schema["$id"]
            Draft202012Validator.check_schema(schema)
            assert all(
                reference.startswith("#") for reference in _schema_references(schema)
            ), f"{tool.name}.{kind} contains a non-local reference"

            canonical_validator = catalog.validator(tool.name, kind)
            for case in _corpus_cases(tool.name, kind):
                instance = case["instance"]
                if case["valid"]:
                    canonical_validator.validate(instance)
                    validate(instance, schema)
                else:
                    with pytest.raises(ValidationError):
                        canonical_validator.validate(instance)
                    with pytest.raises(ValidationError):
                        validate(instance, schema)


def test_advertisement_preserves_packaged_schemas_and_catalog_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = SchemaCatalog.load_packaged()
    original_tool_schemas = copy.deepcopy(catalog.tool_schemas)
    original_common_schemas = copy.deepcopy(catalog.common_schemas)
    expected_fingerprint = (
        "sha256:257d27c1a3fb3e0df93b0be4b4b61835955b733dbee142faf30d347b5bbe8b2b"
    )
    monkeypatch.setattr(
        SchemaCatalog,
        "load_packaged",
        classmethod(lambda _cls, _version="0.1.0": catalog),
    )

    ModelingMcpAdapter(cast(ApplicationFacade, object()))

    assert catalog.fingerprint == expected_fingerprint
    assert catalog.tool_schemas == original_tool_schemas
    assert catalog.common_schemas == original_common_schemas


def test_advertised_schema_bundler_preserves_existing_namespace_on_collision() -> None:
    common_uri = (
        "https://schemas.math-modeling-mcp.local/common/0.1.0/"
        "modeling-error.schema.json"
    )
    preferred_key = (
        "__mcp_external_" + hashlib.sha256(common_uri.encode("utf-8")).hexdigest()
    )
    root = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://schemas.math-modeling-mcp.local/test/collision.schema.json",
        "type": "object",
        "required": ["entity_id"],
        "properties": {
            "entity_id": {"$ref": f"{common_uri}#/$defs/entityId"},
        },
        "$defs": {preferred_key: {"const": "sentinel"}},
    }
    resources = SchemaCatalog.load_packaged().common_schemas
    bundle = adapter_module._self_contained_advertised_schema(root, resources)

    assert bundle["$defs"][preferred_key] == {"const": "sentinel"}
    assert preferred_key + "_1" in bundle["$defs"]
    validate(
        {"entity_id": "123e4567-e89b-42d3-a456-426614174000"},
        bundle,
    )
    with pytest.raises(ValidationError):
        validate({"entity_id": "not-a-uuid"}, bundle)


@pytest.mark.parametrize(
    "reference",
    [
        "https://schemas.math-modeling-mcp.local/unknown.schema.json#/$defs/id",
        (
            "https://schemas.math-modeling-mcp.local/common/0.1.0/"
            "modeling-error.schema.json#named-anchor"
        ),
    ],
)
def test_advertised_schema_bundler_rejects_unresolvable_references(
    reference: str,
) -> None:
    root = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://schemas.math-modeling-mcp.local/test/invalid-ref.schema.json",
        "$ref": reference,
    }

    with pytest.raises(ValueError, match="advertised schema reference"):
        adapter_module._self_contained_advertised_schema(
            root,
            SchemaCatalog.load_packaged().common_schemas,
        )


def test_modeling_mcp_is_in_the_locked_editable_wheel_configuration() -> None:
    project = tomllib.loads(
        (Path(__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert (
        "src/modeling_mcp"
        in project["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    )
    assert importlib.util.find_spec("modeling_mcp") is not None


def test_valid_health_call_invokes_the_typed_facade_once() -> None:
    expected = HealthCheckResult.model_validate_json(
        json.dumps(_corpus_instance("health_check", "result", "valid_result"))
    )
    facade = Mock(spec=ApplicationFacade)
    facade.health_check.return_value = expected
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = adapter.call_tool("health_check", {})

    facade.health_check.assert_called_once_with(HealthCheckRequest())
    assert result.isError is False
    assert result.structuredContent == expected.model_dump(mode="json")


def test_valid_create_project_call_invokes_the_typed_facade_once() -> None:
    request_data = _corpus_instance("create_project", "request", "valid_request")
    expected_request = CreateProjectRequest.model_validate_json(
        json.dumps(request_data)
    )
    expected_result = CreateProjectResult.model_validate_json(
        json.dumps(_corpus_instance("create_project", "result", "valid_result"))
    )
    facade = Mock(spec=ApplicationFacade)
    facade.create_project.return_value = expected_result
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = _call_through_low_level_sdk(
        adapter,
        "create_project",
        request_data,
    )

    facade.create_project.assert_called_once_with(expected_request)
    assert result.isError is False
    assert result.structuredContent == expected_result.model_dump(mode="json")


def test_valid_get_project_status_call_invokes_the_typed_facade_once() -> None:
    request_data = _corpus_instance("get_project_status", "request", "valid_request")
    expected_request = TypeAdapter(GetProjectStatusRequest).validate_json(
        json.dumps(request_data)
    )
    expected_result = TypeAdapter(GetProjectStatusResult).validate_json(
        json.dumps(_corpus_instance("get_project_status", "result", "valid_result"))
    )
    facade = Mock(spec=ApplicationFacade)
    facade.get_project_status.return_value = expected_result
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = adapter.call_tool("get_project_status", request_data)

    facade.get_project_status.assert_called_once_with(expected_request)
    assert result.isError is False
    assert result.structuredContent == expected_result.model_dump(mode="json")


def test_valid_list_capabilities_call_invokes_the_typed_facade_once() -> None:
    request_data = _corpus_instance("list_capabilities", "request", "valid_request")
    expected_request = TypeAdapter(ListCapabilitiesRequest).validate_json(
        json.dumps(request_data)
    )
    expected_result = TypeAdapter(ListCapabilitiesResult).validate_json(
        json.dumps(_corpus_instance("list_capabilities", "result", "valid_result"))
    )
    facade = Mock(spec=ApplicationFacade)
    facade.list_capabilities.return_value = expected_result
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = adapter.call_tool("list_capabilities", request_data)

    facade.list_capabilities.assert_called_once_with(expected_request)
    assert result.isError is False
    assert result.structuredContent == expected_result.model_dump(mode="json")


def test_valid_run_experiment_call_invokes_the_typed_facade_once() -> None:
    request_data = _corpus_instance("run_experiment", "request", "valid_request")
    expected_request = RunExperimentRequest.model_validate_json(
        json.dumps(request_data)
    )
    expected_result = TypeAdapter(RunExperimentResult).validate_json(
        json.dumps(_corpus_instance("run_experiment", "result", "valid_result"))
    )
    facade = Mock(spec=ApplicationFacade)
    facade.run_experiment.return_value = expected_result
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = adapter.call_tool("run_experiment", request_data)

    facade.run_experiment.assert_called_once_with(expected_request)
    assert result.isError is False
    assert result.structuredContent == expected_result.model_dump(mode="json")


def test_valid_validate_experiment_call_invokes_the_typed_facade_once() -> None:
    request_data = _corpus_instance("validate_experiment", "request", "valid_request")
    expected_request = ValidateExperimentRequest.model_validate_json(
        json.dumps(request_data)
    )
    expected_result = TypeAdapter(ValidateExperimentResult).validate_json(
        json.dumps(_corpus_instance("validate_experiment", "result", "valid_result"))
    )
    facade = Mock(spec=ApplicationFacade)
    facade.validate_experiment.return_value = expected_result
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = adapter.call_tool("validate_experiment", request_data)

    facade.validate_experiment.assert_called_once_with(expected_request)
    assert result.isError is False
    assert result.structuredContent == expected_result.model_dump(mode="json")


def test_modeling_error_returns_exact_tool_specific_structured_error() -> None:
    request_data = _corpus_instance("create_project", "request", "valid_request")
    error_response = ErrorResponse.model_validate_json(
        json.dumps(_corpus_instance("create_project", "error", "valid_error"))
    )
    facade = Mock(spec=ApplicationFacade)
    facade.create_project.side_effect = ModelingError(error_response)
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = _call_through_low_level_sdk(
        adapter,
        "create_project",
        request_data,
    )

    expected = error_response.model_dump(mode="json", exclude_none=True)
    assert result.isError is True
    assert result.structuredContent == expected
    assert json.loads(result.content[0].text) == expected
    SchemaCatalog.load_packaged().validator("create_project", "error").validate(
        result.structuredContent
    )


def test_compatibility_content_is_one_compact_json_text_block() -> None:
    expected = HealthCheckResult.model_validate_json(
        json.dumps(_corpus_instance("health_check", "result", "valid_result"))
    )
    facade = Mock(spec=ApplicationFacade)
    facade.health_check.return_value = expected

    result = ModelingMcpAdapter(cast(ApplicationFacade, facade)).call_tool(
        "health_check", {}
    )

    assert len(result.content) == 1
    assert isinstance(result.content[0], TextContent)
    assert result.content[0].text == json.dumps(
        result.structuredContent, ensure_ascii=False, separators=(",", ":")
    )


def test_numerical_failure_and_failed_validation_are_normal_mcp_results() -> None:
    digest = "sha256:" + "a" * 64
    run_data = _corpus_instance("run_experiment", "result", "valid_result")
    run_data.pop("terminal_reason")
    run_data.update(
        {
            "attempt_status": "NUMERICAL_FAILURE",
            "result_kind": "numerical_failure",
            "result_hash": digest,
            "result_summary": {
                "failure_code": "no_sign_change",
                "iterations": 0,
                "evaluations": 2,
            },
        }
    )
    numerical_failure = TypeAdapter(RunExperimentResult).validate_json(
        json.dumps(run_data)
    )
    validate_data = _corpus_instance("validate_experiment", "result", "valid_result")
    validate_data.pop("terminal_reason")
    validate_data.update(
        {
            "validation_status": "SUCCEEDED",
            "outcome": "FAILED",
            "metrics": {
                "root_within_interval": True,
                "reported_function_value": 1.0,
                "recomputed_function_value": 1.0,
                "absolute_reported_delta": 0.0,
                "absolute_residual": 1.0,
                "function_tolerance": 1e-10,
                "failed_checks": ["residual_exceeds_tolerance"],
            },
            "validation_report_hash": digest,
        }
    )
    failed_validation = TypeAdapter(ValidateExperimentResult).validate_json(
        json.dumps(validate_data)
    )
    facade = Mock(spec=ApplicationFacade)
    facade.run_experiment.return_value = numerical_failure
    facade.validate_experiment.return_value = failed_validation
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    run_result = adapter.call_tool(
        "run_experiment",
        _corpus_instance("run_experiment", "request", "valid_request"),
    )
    validation_result = adapter.call_tool(
        "validate_experiment",
        _corpus_instance("validate_experiment", "request", "valid_request"),
    )

    assert run_result.isError is False
    assert run_result.structuredContent["attempt_status"] == "NUMERICAL_FAILURE"
    assert validation_result.isError is False
    assert validation_result.structuredContent["outcome"] == "FAILED"


def test_facade_result_is_independently_validated_before_return() -> None:
    valid = HealthCheckResult.model_validate_json(
        json.dumps(_corpus_instance("health_check", "result", "valid_result"))
    )
    forged = valid.model_copy(update={"status": "BROKEN"})
    facade = Mock(spec=ApplicationFacade)
    facade.health_check.return_value = forged
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = adapter.call_tool("health_check", {})

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["code"] == "INTERNAL_ERROR"


def test_request_schema_is_validated_before_facade_dispatch() -> None:
    facade = Mock(spec=ApplicationFacade)
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = adapter.call_tool("health_check", {"extra": True})

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["code"] == "INVALID_REQUEST"
    facade.health_check.assert_not_called()


def test_low_level_sdk_returns_structured_invalid_request_for_unknown_field() -> None:
    facade = Mock(spec=ApplicationFacade)
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = _call_through_low_level_sdk(
        adapter,
        "health_check",
        {"extra": True},
    )

    assert result.isError is True
    assert result.structuredContent is not None
    error = ErrorResponse.model_validate(result.structuredContent)
    assert error.code == "INVALID_REQUEST"
    assert error.details.model_dump() == {
        "field_path": "/extra",
        "reason": "unknown_field",
    }
    SchemaCatalog.load_packaged().validator("health_check", "error").validate(
        result.structuredContent
    )
    facade.health_check.assert_not_called()


@pytest.mark.parametrize(
    ("arguments", "field_path", "reason"),
    [
        ({}, "/operation_id", "missing_required"),
        ({"operation_id": 7}, "/operation_id", "invalid_type"),
        ({"operation_id": "not-a-uuid"}, "/operation_id", "invalid_format"),
    ],
)
def test_low_level_sdk_maps_request_schema_failures_to_stable_details(
    arguments: dict[str, object],
    field_path: str,
    reason: str,
) -> None:
    facade = Mock(spec=ApplicationFacade)
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = _call_through_low_level_sdk(
        adapter,
        "create_project",
        arguments,
    )

    assert result.isError is True
    assert result.structuredContent is not None
    error = ErrorResponse.model_validate(result.structuredContent)
    assert error.code == "INVALID_REQUEST"
    assert error.details.model_dump() == {
        "field_path": field_path,
        "reason": reason,
    }
    SchemaCatalog.load_packaged().validator("create_project", "error").validate(
        result.structuredContent
    )
    facade.create_project.assert_not_called()


def test_low_level_sdk_returns_structured_invalid_request_for_unknown_tool() -> None:
    facade = Mock(spec=ApplicationFacade)
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = _call_through_low_level_sdk(adapter, "not_a_tool", {})

    assert result.isError is True
    assert result.structuredContent is not None
    error = ErrorResponse.model_validate(result.structuredContent)
    assert error.code == "INVALID_REQUEST"
    assert error.details.model_dump() == {
        "field_path": "/name",
        "reason": "invalid_format",
    }
    assert "not_a_tool" not in result.content[0].text
    assert not any(getattr(facade, method_name).called for method_name in TOOL_NAMES)


def test_low_level_sdk_maps_dto_validation_failure_to_invalid_request() -> None:
    request_data = _corpus_instance("run_experiment", "request", "valid_request")
    payload = cast(dict[str, object], request_data["payload"])
    payload["max_iterations"] = 100.0
    SchemaCatalog.load_packaged().validator("run_experiment", "request").validate(
        request_data
    )
    facade = Mock(spec=ApplicationFacade)
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = _call_through_low_level_sdk(
        adapter,
        "run_experiment",
        request_data,
    )

    assert result.isError is True
    assert result.structuredContent is not None
    error = ErrorResponse.model_validate(result.structuredContent)
    assert error.code == "INVALID_REQUEST"
    assert error.details.model_dump() == {
        "field_path": "/payload/max_iterations",
        "reason": "invalid_type",
    }
    SchemaCatalog.load_packaged().validator("run_experiment", "error").validate(
        result.structuredContent
    )
    facade.run_experiment.assert_not_called()


def test_low_level_sdk_fails_closed_when_facade_raises_unexpected_error() -> None:
    facade = Mock(spec=ApplicationFacade)
    facade.health_check.side_effect = RuntimeError(
        "secret implementation path C:/private/store.sqlite3"
    )
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = _call_through_low_level_sdk(adapter, "health_check", {})

    assert result.isError is True
    assert result.structuredContent is not None
    error = ErrorResponse.model_validate(result.structuredContent)
    assert error.code == "INTERNAL_ERROR"
    assert error.message == "tool request failed unexpectedly"
    assert "secret" not in result.content[0].text
    assert "private" not in result.content[0].text
    SchemaCatalog.load_packaged().validator("health_check", "error").validate(
        result.structuredContent
    )


def test_low_level_sdk_fails_closed_when_facade_result_breaks_contract() -> None:
    valid = HealthCheckResult.model_validate_json(
        json.dumps(_corpus_instance("health_check", "result", "valid_result"))
    )
    facade = Mock(spec=ApplicationFacade)
    facade.health_check.return_value = valid.model_copy(update={"status": "BROKEN"})
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = _call_through_low_level_sdk(adapter, "health_check", {})

    assert result.isError is True
    assert result.structuredContent is not None
    error = ErrorResponse.model_validate(result.structuredContent)
    assert error.code == "INTERNAL_ERROR"
    assert error.message == "tool request failed unexpectedly"
    assert "BROKEN" not in result.content[0].text
    SchemaCatalog.load_packaged().validator("health_check", "error").validate(
        result.structuredContent
    )


def test_low_level_sdk_fails_closed_when_result_cannot_be_serialized() -> None:
    result_data = _corpus_instance("run_experiment", "result", "valid_result")
    result_data.pop("terminal_reason")
    result_data.update(
        {
            "attempt_status": "SUCCEEDED",
            "result_kind": "success",
            "result_hash": "sha256:" + "a" * 64,
            "result_summary": {
                "root": 1.0,
                "function_value": 0.0,
                "iterations": 1,
                "evaluations": 3,
                "termination_reason": "residual_tolerance",
            },
        }
    )
    valid = cast(
        RunExperimentSucceededResult,
        TypeAdapter(RunExperimentResult).validate_json(json.dumps(result_data)),
    )
    forged_summary = valid.result_summary.model_copy(update={"root": float("nan")})
    facade = Mock(spec=ApplicationFacade)
    facade.run_experiment.return_value = valid.model_copy(
        update={"result_summary": forged_summary}
    )
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = _call_through_low_level_sdk(
        adapter,
        "run_experiment",
        _corpus_instance("run_experiment", "request", "valid_request"),
    )

    assert result.isError is True
    assert result.structuredContent is not None
    error = ErrorResponse.model_validate(result.structuredContent)
    assert error.code == "INTERNAL_ERROR"
    assert error.message == "tool request failed unexpectedly"
    assert "Out of range float values" not in result.content[0].text
    SchemaCatalog.load_packaged().validator("run_experiment", "error").validate(
        result.structuredContent
    )


def test_oversized_schema_valid_result_becomes_bounded_tool_error() -> None:
    result_data = _corpus_instance("list_capabilities", "result", "valid_result")
    result_data["registry"]["capability_count"] = 1
    digest = "sha256:" + "a" * 64
    result_data["capabilities"] = [
        {
            "capability_id": "numerical.root_finding",
            "contract_version": "0.1.0",
            "title": "Root finding",
            "summary": "x" * 262144,
            "category": "numerical",
            "tags": [],
            "determinism": "deterministic",
            "randomness": "not_used",
            "input_schema_hash": digest,
            "canonical_input_schema_version": (
                "numerical.root_finding.canonical-input/0.1.0"
            ),
            "canonical_input_schema_hash": digest,
            "success_schema_hash": digest,
            "failure_schema_hash": digest,
        }
    ]
    oversized = TypeAdapter(ListCapabilitiesResult).validate_json(
        json.dumps(result_data)
    )
    oversized_content = oversized.model_dump(mode="json")
    assert len(canonical_json_bytes(oversized_content)) > 262144
    facade = Mock(spec=ApplicationFacade)
    facade.list_capabilities.return_value = oversized
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = adapter.call_tool("list_capabilities", {})

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["code"] == "RESOURCE_LIMIT_EXCEEDED"
    assert result.structuredContent["details"]["resource"] == ("inline_response_bytes")
    assert result.structuredContent["details"]["limit"] == 262144
    assert result.structuredContent["details"]["observed"] > 262144
    SchemaCatalog.load_packaged().validator("list_capabilities", "error").validate(
        result.structuredContent
    )


def test_decomposed_unicode_is_limited_by_the_exact_returned_utf8_bytes() -> None:
    result_data = _corpus_instance("list_capabilities", "result", "valid_result")
    result_data["registry"]["capability_count"] = 1
    digest = "sha256:" + "a" * 64
    result_data["capabilities"] = [
        {
            "capability_id": "numerical.root_finding",
            "contract_version": "0.1.0",
            "title": "Root finding",
            "summary": "e\u0301" * 100000,
            "category": "numerical",
            "tags": [],
            "determinism": "deterministic",
            "randomness": "not_used",
            "input_schema_hash": digest,
            "canonical_input_schema_version": (
                "numerical.root_finding.canonical-input/0.1.0"
            ),
            "canonical_input_schema_hash": digest,
            "success_schema_hash": digest,
            "failure_schema_hash": digest,
        }
    ]
    oversized = TypeAdapter(ListCapabilitiesResult).validate_json(
        json.dumps(result_data, ensure_ascii=False)
    )
    structured = oversized.model_dump(mode="json")
    compact = json.dumps(structured, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    assert len(canonical_json_bytes(structured)) <= 262144
    assert len(compact) > 262144
    facade = Mock(spec=ApplicationFacade)
    facade.list_capabilities.return_value = oversized
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    result = adapter.call_tool("list_capabilities", {})

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["code"] == "RESOURCE_LIMIT_EXCEEDED"
    assert result.structuredContent["details"]["observed"] == len(compact)
    assert isinstance(result.content[0], TextContent)
    assert json.loads(result.content[0].text) == result.structuredContent


def test_pinned_sdk_exposes_every_class_used_by_the_mcp_boundary() -> None:
    sdk_classes = (
        NotificationOptions,
        Server,
        InitializationOptions,
        SessionMessage,
        CallToolResult,
        JSONRPCMessage,
        TextContent,
        Tool,
    )

    assert all(cls.__module__.startswith("mcp") for cls in sdk_classes)


def _exchange_stdio_frame(
    monkeypatch: pytest.MonkeyPatch,
    frame: bytes,
    *,
    max_request_bytes: int = 1048576,
    response: JSONRPCMessage | None = None,
) -> tuple[SessionMessage | Exception, bytes]:
    stdin = io.TextIOWrapper(io.BytesIO(frame), encoding="utf-8")
    stdout_bytes = io.BytesIO()
    stdout = io.TextIOWrapper(stdout_bytes, encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)

    async def exchange() -> SessionMessage | Exception:
        async with strict_stdio_server(max_request_bytes) as (
            read_stream,
            write_stream,
        ):
            received = await read_stream.receive()
            if response is not None:
                await write_stream.send(SessionMessage(response))
            await write_stream.aclose()
            return received

    received = anyio.run(exchange)
    stdout.flush()
    return received, stdout_bytes.getvalue()


def test_strict_stdio_reads_bytes_and_writes_one_exact_json_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_frame = b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n'
    response = JSONRPCMessage.model_validate(
        {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    )

    received, written = _exchange_stdio_frame(
        monkeypatch, request_frame, response=response
    )

    assert isinstance(received, SessionMessage)
    assert received.message.root.method == "ping"
    expected = response.model_dump_json(by_alias=True, exclude_none=True).encode(
        "utf-8"
    )
    assert written == expected + b"\n"


@pytest.mark.parametrize(
    ("frame", "max_request_bytes"),
    [
        (b'\xef\xbb\xbf{"jsonrpc":"2.0","id":1,"method":"ping"}\n', 1048576),
        (b'{"jsonrpc":"2.0","id":1,"method":"\xff"}\n', 1048576),
        (b"{} \n", 2),
        (
            b'{"jsonrpc":"2.0","id":1,"id":2,"method":"ping"}\n',
            1048576,
        ),
        (
            b'{"jsonrpc":"2.0","id":1,"method":"\\ud800"}\n',
            1048576,
        ),
        (
            b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":NaN}}\n',
            1048576,
        ),
        (
            b'{"jsonrpc":"2.0","id":1,"method":"ping","params":{"x":Infinity}}\n',
            1048576,
        ),
    ],
)
def test_strict_stdio_rejects_nonstrict_frames_before_sdk_use(
    monkeypatch: pytest.MonkeyPatch,
    frame: bytes,
    max_request_bytes: int,
) -> None:
    received, written = _exchange_stdio_frame(
        monkeypatch, frame, max_request_bytes=max_request_bytes
    )

    assert isinstance(received, ValueError)
    assert written == b""


def test_strict_stdio_stops_bounded_read_before_newline_or_eof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    max_request_bytes = 32

    class NeverEndingNoNewlineBuffer:
        def __init__(self) -> None:
            self.read_sizes: list[int] = []
            self.unbounded_read_attempted = False
            self.readline_calls = 0

        def readline(self) -> bytes:
            self.unbounded_read_attempted = True
            self.readline_calls += 1
            if self.readline_calls == 1:
                return b"x" * (max_request_bytes + 2) + b"\n"
            return b""

        def read1(self, size: int = -1) -> bytes:
            self.read_sizes.append(size)
            if len(self.read_sizes) > 1:
                raise AssertionError("transport read beyond the overflow boundary")
            return b"x" * size

    class BinaryInput:
        def __init__(self, buffer: NeverEndingNoNewlineBuffer) -> None:
            self.buffer = buffer

    source = NeverEndingNoNewlineBuffer()
    stdout_bytes = io.BytesIO()
    stdout = io.TextIOWrapper(stdout_bytes, encoding="utf-8")
    monkeypatch.setattr(sys, "stdin", BinaryInput(source))
    monkeypatch.setattr(sys, "stdout", stdout)

    async def receive_overflow() -> SessionMessage | Exception:
        async with strict_stdio_server(max_request_bytes) as (
            read_stream,
            write_stream,
        ):
            received = await read_stream.receive()
            await write_stream.aclose()
            return received

    received = anyio.run(receive_overflow)

    assert isinstance(received, ValueError)
    assert str(received) == "STDIO frame exceeds the request byte limit"
    assert source.unbounded_read_attempted is False
    assert source.read_sizes == [max_request_bytes + 1]


def test_low_level_server_negotiates_pinned_protocol_with_tool_capability_only() -> (
    None
):
    facade = Mock(spec=ApplicationFacade)
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))
    server = Server[object, object](
        name="math-modeling-mcp",
        version=APPLICATION_VERSION,
    )
    configure_mcp_server(adapter, server)

    options = server.create_initialization_options(NotificationOptions())
    capabilities = options.capabilities.model_dump(by_alias=True, exclude_none=True)

    assert APPLICATION_VERSION == "0.2.0"
    assert MCP_PROTOCOL_VERSION == LATEST_PROTOCOL_VERSION == "2025-11-25"
    assert options.server_version == APPLICATION_VERSION
    assert set(capabilities) <= {"experimental", "tools"}
    assert capabilities["tools"] == {"listChanged": False}


def test_entrypoint_help_does_not_import_the_future_composition_root(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from modeling_mcp import __main__ as entrypoint

    def fail_import(_name: str) -> None:
        raise AssertionError("--help must finish before composition is imported")

    monkeypatch.setattr(entrypoint.importlib, "import_module", fail_import)

    with pytest.raises(SystemExit) as exit_info:
        entrypoint.main(["--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "--project-root" in output
