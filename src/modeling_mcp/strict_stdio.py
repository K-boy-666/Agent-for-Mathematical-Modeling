"""Strict byte-oriented STDIO transport for the pinned MCP SDK."""

from __future__ import annotations

import codecs
import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import anyio
import anyio.lowlevel
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from mcp.shared.message import SessionMessage
from mcp.types import JSONRPCMessage

from modeling_core.contracts.canonical_json import strict_json_loads

DEFAULT_MAX_REQUEST_BYTES = 1048576

logger = logging.getLogger(__name__)
logger.propagate = False
if not any(isinstance(handler, logging.StreamHandler) for handler in logger.handlers):
    logger.addHandler(logging.StreamHandler(sys.stderr))

StdioStreams = tuple[
    MemoryObjectReceiveStream[SessionMessage | Exception],
    MemoryObjectSendStream[SessionMessage],
]


def _parse_frame(line: bytes, max_request_bytes: int) -> JSONRPCMessage:
    if not line.endswith(b"\n"):
        raise ValueError("STDIO frame must end with a newline")
    frame = line[:-1]
    if len(frame) > max_request_bytes:
        raise ValueError("STDIO frame exceeds the request byte limit")
    if frame.startswith(codecs.BOM_UTF8):
        raise ValueError("STDIO frame must not start with a UTF-8 BOM")
    value = strict_json_loads(frame)
    return JSONRPCMessage.model_validate(value)


async def _bounded_lines(
    stdin: anyio.AsyncFile[bytes],
    max_request_bytes: int,
) -> AsyncIterator[bytes]:
    pending = bytearray()
    while True:
        delimiter = pending.find(b"\n")
        if delimiter >= 0:
            line = bytes(pending[: delimiter + 1])
            del pending[: delimiter + 1]
            yield line
            continue
        if len(pending) > max_request_bytes:
            raise ValueError("STDIO frame exceeds the request byte limit")
        chunk = await stdin.read1(max_request_bytes + 1 - len(pending))
        if not chunk:
            if pending:
                yield bytes(pending)
            return
        pending.extend(chunk)


@asynccontextmanager
async def strict_stdio_server(
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES,
) -> AsyncIterator[StdioStreams]:
    """Yield the SDK stream pair while enforcing strict JSON byte framing."""
    if max_request_bytes < 1:
        raise ValueError("max_request_bytes must be positive")

    stdin: anyio.AsyncFile[bytes] = anyio.wrap_file(sys.stdin.buffer)
    stdout: anyio.AsyncFile[bytes] = anyio.wrap_file(sys.stdout.buffer)

    read_stream_writer, read_stream = anyio.create_memory_object_stream[
        SessionMessage | Exception
    ](0)
    write_stream, write_stream_reader = anyio.create_memory_object_stream[
        SessionMessage
    ](0)

    async def stdin_reader() -> None:
        try:
            async with read_stream_writer:
                try:
                    async for line in _bounded_lines(stdin, max_request_bytes):
                        try:
                            message = _parse_frame(line, max_request_bytes)
                        except Exception as error:
                            logger.warning("rejected STDIO frame: %s", error)
                            await read_stream_writer.send(error)
                            continue
                        await read_stream_writer.send(SessionMessage(message))
                except ValueError as error:
                    logger.warning("rejected STDIO frame: %s", error)
                    await read_stream_writer.send(error)
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async def stdout_writer() -> None:
        try:
            async with write_stream_reader:
                async for session_message in write_stream_reader:
                    frame = session_message.message.model_dump_json(
                        by_alias=True, exclude_none=True
                    ).encode("utf-8") + b"\n"
                    await stdout.write(frame)
                    await stdout.flush()
        except anyio.ClosedResourceError:  # pragma: no cover
            await anyio.lowlevel.checkpoint()

    async with anyio.create_task_group() as task_group:
        task_group.start_soon(stdin_reader)
        task_group.start_soon(stdout_writer)
        yield read_stream, write_stream
