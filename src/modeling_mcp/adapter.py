from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any, cast

from mcp.types import CallToolResult, TextContent, Tool
from pydantic import BaseModel, TypeAdapter

from modeling_core.application.facade import ApplicationFacade
from modeling_core.contracts.errors import (
    ErrorResponse,
    ModelingError,
    ResourceLimitExceededDetails,
)
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.tools import (
    TOOL_NAMES,
    CreateProjectRequest,
    GetProjectStatusRequest,
    HealthCheckRequest,
    ListCapabilitiesRequest,
    RunExperimentRequest,
    ValidateExperimentRequest,
)

ToolArguments = dict[str, Any]
ToolInvoker = Callable[[ApplicationFacade, ToolArguments], BaseModel]
INLINE_RESPONSE_MAX_BYTES = 262144

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


_DISPATCH: dict[str, ToolInvoker] = {
    "health_check": _invoke_health_check,
    "create_project": _invoke_create_project,
    "get_project_status": _invoke_get_project_status,
    "list_capabilities": _invoke_list_capabilities,
    "run_experiment": _invoke_run_experiment,
    "validate_experiment": _invoke_validate_experiment,
}


class ModelingMcpAdapter:
    """Translate the six public application operations to MCP tools."""

    def __init__(self, facade: ApplicationFacade) -> None:
        self._facade = facade
        self._catalog = SchemaCatalog.load_packaged("0.1.0")
        self._tools = tuple(
            Tool(
                name=name,
                inputSchema=self._catalog.for_tool(name, "request"),
                outputSchema=self._catalog.for_tool(name, "result"),
            )
            for name in TOOL_NAMES
        )

    def list_tools(self) -> list[Tool]:
        return list(self._tools)

    def call_tool(self, name: str, arguments: ToolArguments) -> CallToolResult:
        self._catalog.validator(name, "request").validate(arguments)
        try:
            result = _DISPATCH[name](self._facade, arguments)
        except ModelingError as error:
            structured_error = error.response.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
            self._catalog.validator(name, "error").validate(structured_error)
            return CallToolResult(
                content=[
                    TextContent(type="text", text=_compact_json(structured_error))
                ],
                structuredContent=structured_error,
                isError=True,
            )
        structured = result.model_dump(mode="json", by_alias=True)
        self._catalog.validator(name, "result").validate(structured)
        serialized = _compact_json(structured)
        observed = len(serialized.encode("utf-8"))
        if observed > INLINE_RESPONSE_MAX_BYTES:
            response = ErrorResponse(
                error_schema_version="modeling-error/0.1.0",
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
            structured_error = response.model_dump(
                mode="json", by_alias=True, exclude_none=True
            )
            self._catalog.validator(name, "error").validate(structured_error)
            return CallToolResult(
                content=[
                    TextContent(type="text", text=_compact_json(structured_error))
                ],
                structuredContent=structured_error,
                isError=True,
            )
        return CallToolResult(
            content=[TextContent(type="text", text=serialized)],
            structuredContent=structured,
            isError=False,
        )
