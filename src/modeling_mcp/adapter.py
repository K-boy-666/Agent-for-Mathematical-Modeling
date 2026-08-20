from __future__ import annotations

import copy
import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from typing import Any, Literal, cast
from urllib.parse import urldefrag, urljoin

from jsonschema import (  # type: ignore[import-untyped]
    Draft202012Validator,
    ValidationError as JsonSchemaValidationError,
)
from mcp.types import CallToolResult, TextContent, Tool
from pydantic import BaseModel, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from modeling_core.application.facade import ApplicationFacade
from modeling_core.contracts.errors import (
    ErrorResponse,
    InternalErrorDetails,
    InvalidRequestDetails,
    ModelingError,
    ResourceLimitExceededDetails,
)
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.tools import (
    TOOL_NAMES,
    ConfirmSubproblemMmirRequest,
    CreateProjectRequest,
    ExportSubproblemRequest,
    GetProjectStatusRequest,
    HealthCheckRequest,
    ListCapabilitiesRequest,
    PutSubproblemMmirRequest,
    RegisterProblemAssetsRequest,
    RunExperimentRequest,
    ValidateExperimentRequest,
)
from modeling_core.contracts.versions import VersionSet

ToolArguments = dict[str, Any]
ToolInvoker = Callable[[ApplicationFacade, ToolArguments], BaseModel]
InvalidRequestReason = Literal[
    "missing_required",
    "unknown_field",
    "invalid_type",
    "invalid_format",
    "out_of_range",
    "invalid_combination",
]
INLINE_RESPONSE_MAX_BYTES = 262144
_EXTERNAL_SCHEMA_PREFIX = "__mcp_external_"

_GET_PROJECT_STATUS_REQUEST: TypeAdapter[GetProjectStatusRequest] = TypeAdapter(
    GetProjectStatusRequest
)
_LIST_CAPABILITIES_REQUEST: TypeAdapter[ListCapabilitiesRequest] = TypeAdapter(
    ListCapabilitiesRequest
)


def _compact_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _schema_references(value: object) -> list[str]:
    references: list[str] = []
    if isinstance(value, dict):
        reference = value.get("$ref")
        if reference is not None:
            if not isinstance(reference, str):
                raise ValueError("advertised schema reference must be a string")
            references.append(reference)
        for nested in value.values():
            references.extend(_schema_references(nested))
    elif isinstance(value, list):
        for nested in value:
            references.extend(_schema_references(nested))
    return references


def _reference_target(reference: str, base_uri: str) -> tuple[str, str]:
    document_uri, fragment = urldefrag(urljoin(base_uri, reference))
    if fragment and not fragment.startswith("/"):
        raise ValueError("advertised schema reference uses a non-JSON-Pointer fragment")
    return document_uri, fragment


def _self_contained_advertised_schema(
    schema: JsonObject,
    resources: Mapping[str, JsonObject],
) -> JsonObject:
    """Deep-copy and bundle locally registered resources for MCP clients."""
    bundled = copy.deepcopy(schema)
    root_uri_value = bundled.get("$id", "")
    if not isinstance(root_uri_value, str):
        raise ValueError("advertised schema $id must be a string")
    root_uri = root_uri_value

    discovered: set[str] = set()
    pending: set[str] = set()

    def discover(document: JsonObject, base_uri: str) -> None:
        for reference in _schema_references(document):
            target_uri, _ = _reference_target(reference, base_uri)
            if target_uri in {"", base_uri, root_uri}:
                continue
            if target_uri not in resources:
                raise ValueError(
                    f"advertised schema reference has unknown resource: {target_uri}"
                )
            if target_uri not in discovered:
                pending.add(target_uri)

    discover(bundled, root_uri)
    while pending:
        resource_uri = min(pending)
        pending.remove(resource_uri)
        if resource_uri in discovered:
            continue
        discovered.add(resource_uri)
        discover(resources[resource_uri], resource_uri)

    existing_defs = bundled.get("$defs")
    if existing_defs is not None and not isinstance(existing_defs, dict):
        raise ValueError("advertised schema $defs must be an object")
    occupied = set(existing_defs or {})
    resource_keys: dict[str, str] = {}
    for resource_uri in sorted(discovered):
        preferred = (
            _EXTERNAL_SCHEMA_PREFIX
            + hashlib.sha256(resource_uri.encode("utf-8")).hexdigest()
        )
        resource_key = preferred
        suffix = 1
        while resource_key in occupied:
            resource_key = f"{preferred}_{suffix}"
            suffix += 1
        occupied.add(resource_key)
        resource_keys[resource_uri] = resource_key

    def rewrite(value: object, base_uri: str) -> object:
        if isinstance(value, dict):
            rewritten: dict[str, object] = {}
            for key, nested in value.items():
                if key != "$ref":
                    rewritten[key] = rewrite(nested, base_uri)
                    continue
                if not isinstance(nested, str):
                    raise ValueError("advertised schema reference must be a string")
                target_uri, fragment = _reference_target(nested, base_uri)
                if target_uri in {"", root_uri}:
                    prefix = "#"
                else:
                    resource_key = resource_keys.get(target_uri)
                    if resource_key is None:
                        raise ValueError(
                            "advertised schema reference has unknown resource: "
                            f"{target_uri}"
                        )
                    prefix = f"#/$defs/{resource_key}"
                rewritten[key] = prefix + fragment
            return rewritten
        if isinstance(value, list):
            return [rewrite(nested, base_uri) for nested in value]
        return value

    rewritten_root = cast(JsonObject, rewrite(bundled, root_uri))
    if resource_keys:
        root_defs = rewritten_root.setdefault("$defs", {})
        if not isinstance(root_defs, dict):
            raise ValueError("advertised schema $defs must be an object")
        for resource_uri in sorted(resource_keys):
            resource = copy.deepcopy(resources[resource_uri])
            resource.pop("$id", None)
            root_defs[resource_keys[resource_uri]] = rewrite(resource, resource_uri)

    Draft202012Validator.check_schema(rewritten_root)
    if any(
        not reference.startswith("#")
        for reference in _schema_references(rewritten_root)
    ):
        raise ValueError("advertised schema reference is not document-local")
    return rewritten_root


def _json_pointer(parts: list[object]) -> str:
    return "".join(
        f"/{str(part).replace('~', '~0').replace('/', '~1')}" for part in parts
    )


def _schema_error_location(
    error: JsonSchemaValidationError,
) -> tuple[str, InvalidRequestReason]:
    path: list[object] = list(error.absolute_path)
    if error.validator == "additionalProperties" and isinstance(error.instance, dict):
        properties = (
            error.schema.get("properties", {}) if isinstance(error.schema, dict) else {}
        )
        unexpected = sorted(set(error.instance) - set(properties))
        if unexpected:
            path.append(unexpected[0])
        return _json_pointer(path), "unknown_field"
    if error.validator == "required" and isinstance(error.instance, dict):
        required = error.validator_value
        if isinstance(required, list):
            missing = next(
                (field for field in required if field not in error.instance),
                None,
            )
            if missing is not None:
                path.append(missing)
        return _json_pointer(path), "missing_required"
    if error.validator == "type":
        return _json_pointer(path), "invalid_type"
    if error.validator in {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
    }:
        return _json_pointer(path), "out_of_range"
    if error.validator in {
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "dependentRequired",
        "dependentSchemas",
    }:
        return _json_pointer(path), "invalid_combination"
    return _json_pointer(path), "invalid_format"


def _pydantic_error_location(
    error: PydanticValidationError,
) -> tuple[str, InvalidRequestReason]:
    first = error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    )[0]
    path = _json_pointer(list(first["loc"]))
    error_type = first["type"]
    if error_type == "missing":
        return path, "missing_required"
    if error_type == "extra_forbidden":
        return path, "unknown_field"
    if error_type.endswith("_type") or error_type in {
        "dict_type",
        "list_type",
        "model_type",
        "tuple_type",
    }:
        return path, "invalid_type"
    if error_type in {
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "string_too_short",
        "string_too_long",
        "too_short",
        "too_long",
    }:
        return path, "out_of_range"
    if error_type.startswith("union_") or error_type in {
        "literal_error",
        "missing_sentinel_error",
    }:
        return path, "invalid_combination"
    return path, "invalid_format"


def _invoke_health_check(
    facade: ApplicationFacade, arguments: ToolArguments
) -> BaseModel:
    request = HealthCheckRequest.model_validate_json(_compact_json(arguments))
    return facade.health_check(request)


def _invoke_create_project(
    facade: ApplicationFacade, arguments: ToolArguments
) -> BaseModel:
    request = CreateProjectRequest.model_validate_json(_compact_json(arguments))
    return facade.create_project(request)


def _invoke_get_project_status(
    facade: ApplicationFacade, arguments: ToolArguments
) -> BaseModel:
    request = _GET_PROJECT_STATUS_REQUEST.validate_json(_compact_json(arguments))
    return facade.get_project_status(request)


def _invoke_list_capabilities(
    facade: ApplicationFacade, arguments: ToolArguments
) -> BaseModel:
    request = _LIST_CAPABILITIES_REQUEST.validate_json(_compact_json(arguments))
    return facade.list_capabilities(request)


def _invoke_run_experiment(
    facade: ApplicationFacade, arguments: ToolArguments
) -> BaseModel:
    request = RunExperimentRequest.model_validate_json(_compact_json(arguments))
    return facade.run_experiment(request)


def _invoke_validate_experiment(
    facade: ApplicationFacade, arguments: ToolArguments
) -> BaseModel:
    request = ValidateExperimentRequest.model_validate_json(_compact_json(arguments))
    return facade.validate_experiment(request)


def _invoke_register_problem_assets(
    facade: ApplicationFacade, arguments: ToolArguments
) -> BaseModel:
    request = RegisterProblemAssetsRequest.model_validate_json(_compact_json(arguments))
    return facade.register_problem_assets(request)


def _invoke_put_subproblem_mmir(
    facade: ApplicationFacade, arguments: ToolArguments
) -> BaseModel:
    request = PutSubproblemMmirRequest.model_validate_json(_compact_json(arguments))
    return facade.put_subproblem_mmir(request)


def _invoke_confirm_subproblem_mmir(
    facade: ApplicationFacade, arguments: ToolArguments
) -> BaseModel:
    request = ConfirmSubproblemMmirRequest.model_validate_json(_compact_json(arguments))
    return facade.confirm_subproblem_mmir(request)


def _invoke_export_subproblem(
    facade: ApplicationFacade, arguments: ToolArguments
) -> BaseModel:
    request = ExportSubproblemRequest.model_validate_json(_compact_json(arguments))
    return facade.export_subproblem(request)


_DISPATCH: dict[str, ToolInvoker] = {
    "health_check": _invoke_health_check,
    "create_project": _invoke_create_project,
    "get_project_status": _invoke_get_project_status,
    "list_capabilities": _invoke_list_capabilities,
    "run_experiment": _invoke_run_experiment,
    "validate_experiment": _invoke_validate_experiment,
    "register_problem_assets": _invoke_register_problem_assets,
    "put_subproblem_mmir": _invoke_put_subproblem_mmir,
    "confirm_subproblem_mmir": _invoke_confirm_subproblem_mmir,
    "export_subproblem": _invoke_export_subproblem,
}


class ModelingMcpAdapter:
    """Translate the six public application operations to MCP tools."""

    def __init__(
        self,
        facade: ApplicationFacade,
        versions: VersionSet | None = None,
    ) -> None:
        self._facade = facade
        self._versions = versions or VersionSet.m1a()
        contract_version = self._versions.tool_contract_version.rsplit("/", 1)[1]
        self._catalog = SchemaCatalog.load_packaged(contract_version)
        self._tools = tuple(
            Tool(
                name=name,
                inputSchema=_self_contained_advertised_schema(
                    self._catalog.for_tool(name, "request"),
                    self._catalog.common_schemas,
                ),
                outputSchema=_self_contained_advertised_schema(
                    self._catalog.for_tool(name, "result"),
                    self._catalog.common_schemas,
                ),
            )
            for name in TOOL_NAMES
        )

    def list_tools(self) -> list[Tool]:
        return list(self._tools)

    def _error_result(self, name: str, response: ErrorResponse) -> CallToolResult:
        structured_error = response.model_dump(
            mode="json", by_alias=True, exclude_none=True
        )
        if name in _DISPATCH:
            self._catalog.validator(name, "error").validate(structured_error)
        serialized = _compact_json(structured_error)
        return CallToolResult(
            content=[TextContent(type="text", text=serialized)],
            structuredContent=structured_error,
            isError=True,
        )

    def _invalid_request(
        self,
        name: str,
        correlation_id: str,
        field_path: str,
        reason: InvalidRequestReason,
    ) -> CallToolResult:
        response = ErrorResponse(
            error_schema_version=self._versions.error_schema_version,
            code="INVALID_REQUEST",
            message="request does not match the tool schema",
            retryable=False,
            correlation_id=correlation_id,
            details=InvalidRequestDetails(
                field_path=field_path,
                reason=reason,
            ),
        )
        return self._error_result(name, response)

    def _internal_error(self, name: str, correlation_id: str) -> CallToolResult:
        response = ErrorResponse(
            error_schema_version=self._versions.error_schema_version,
            code="INTERNAL_ERROR",
            message="tool request failed unexpectedly",
            retryable=False,
            correlation_id=correlation_id,
            details=InternalErrorDetails(event_id=str(uuid.uuid4())),
        )
        return self._error_result(name, response)

    def call_tool(self, name: str, arguments: ToolArguments) -> CallToolResult:
        correlation_id = str(uuid.uuid4())
        invoker = _DISPATCH.get(name)
        if invoker is None:
            return self._invalid_request(
                name,
                correlation_id,
                "/name",
                "invalid_format",
            )
        try:
            self._catalog.validator(name, "request").validate(arguments)
        except JsonSchemaValidationError as error:
            field_path, reason = _schema_error_location(error)
            return self._invalid_request(
                name,
                correlation_id,
                field_path,
                reason,
            )
        except Exception:
            return self._internal_error(name, correlation_id)
        try:
            result = invoker(self._facade, arguments)
        except ModelingError as error:
            try:
                return self._error_result(name, error.response)
            except Exception:
                return self._internal_error(name, correlation_id)
        except PydanticValidationError as error:
            field_path, reason = _pydantic_error_location(error)
            return self._invalid_request(
                name,
                correlation_id,
                field_path,
                reason,
            )
        except Exception:
            return self._internal_error(name, correlation_id)
        try:
            structured = result.model_dump(mode="json", by_alias=True)
            self._catalog.validator(name, "result").validate(structured)
            serialized = _compact_json(structured)
            observed = len(serialized.encode("utf-8"))
        except Exception:
            return self._internal_error(name, correlation_id)
        if observed > INLINE_RESPONSE_MAX_BYTES:
            response = ErrorResponse(
                error_schema_version=self._versions.error_schema_version,
                code="RESOURCE_LIMIT_EXCEEDED",
                message="inline response exceeds the byte limit",
                retryable=False,
                correlation_id=cast(str, structured["correlation_id"]),
                details=ResourceLimitExceededDetails(
                    resource="inline_response_bytes",
                    limit=INLINE_RESPONSE_MAX_BYTES,
                    observed=observed,
                ),
            )
            return self._error_result(name, response)
        return CallToolResult(
            content=[TextContent(type="text", text=serialized)],
            structuredContent=structured,
            isError=False,
        )
