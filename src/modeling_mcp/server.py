"""Configure and run injected low-level MCP boundary objects."""

from __future__ import annotations

from typing import Any, Protocol, cast

from mcp.server.lowlevel import NotificationOptions
from mcp.types import LATEST_PROTOCOL_VERSION, CallToolResult, Tool

from modeling_mcp.strict_stdio import strict_stdio_server

APPLICATION_VERSION = "0.1.0"
MCP_PROTOCOL_VERSION = "2025-11-25"


class ToolAdapter(Protocol):
    """Structural boundary consumed by low-level MCP handler registration."""

    def list_tools(self) -> list[Tool]: ...

    def call_tool(
        self, name: str, arguments: dict[str, Any]
    ) -> CallToolResult: ...


def configure_mcp_server(adapter: ToolAdapter, server: object) -> None:
    """Register only the six tool handlers on an injected SDK server."""
    if LATEST_PROTOCOL_VERSION != MCP_PROTOCOL_VERSION:
        raise RuntimeError("pinned MCP SDK protocol version is incompatible")

    sdk_server = cast(Any, server)

    @sdk_server.list_tools()  # type: ignore[untyped-decorator]
    async def list_tools() -> list[Tool]:
        return adapter.list_tools()

    @sdk_server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
    async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:
        return adapter.call_tool(name, arguments)


async def run_mcp_server(
    server: object, max_request_bytes: int = 1048576
) -> None:
    """Run an already-configured SDK server on the strict STDIO transport."""
    sdk_server = cast(Any, server)
    initialization_options = sdk_server.create_initialization_options(
        NotificationOptions()
    )
    async with strict_stdio_server(max_request_bytes) as (
        read_stream,
        write_stream,
    ):
        await sdk_server.run(read_stream, write_stream, initialization_options)


__all__ = [
    "APPLICATION_VERSION",
    "MCP_PROTOCOL_VERSION",
    "ToolAdapter",
    "configure_mcp_server",
    "run_mcp_server",
]
