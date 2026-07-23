from __future__ import annotations

import asyncio
import importlib.util
import json
import math
from pathlib import Path
import sys
import tomllib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from server import solve_fixed_root


SERVER = Path(__file__).with_name("server.py")


def assert_root_result(result: dict[str, object] | object) -> None:
    root = getattr(result, "root", None)
    residual = getattr(result, "residual", None)
    iterations = getattr(result, "iterations", None)
    if isinstance(result, dict):
        root = result["root"]
        residual = result["residual"]
        iterations = result["iterations"]
    assert isinstance(root, float) and math.isfinite(root)
    assert isinstance(residual, float)
    assert abs(root * root - 2.0) <= 1e-9
    assert residual == abs(root * root - 2.0)
    assert isinstance(iterations, int) and 1 <= iterations <= 100


def test_solve_fixed_root_directly() -> None:
    result = solve_fixed_root("x*x-2", 0.0, 2.0, 1e-10, 100)
    assert_root_result(result)


def test_root_finding_over_real_stdio_mcp() -> None:
    async def round_trip() -> None:
        parameters = StdioServerParameters(command=sys.executable, args=[str(SERVER)])
        async with stdio_client(parameters) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert [tool.name for tool in tools.tools] == ["root_finding"]
                result = await session.call_tool(
                    "root_finding",
                    arguments={
                        "equation": "x*x-2",
                        "lower": 0.0,
                        "upper": 2.0,
                        "tolerance": 1e-10,
                    },
                )
                assert_root_result(result.structuredContent)

    asyncio.run(round_trip())


def test_codex_config_materialization(tmp_path: Path) -> None:
    script = Path(__file__).with_name("configure_codex.py")
    assert script.is_file(), "the Codex configuration materializer must exist"

    specification = importlib.util.spec_from_file_location("configure_codex", script)
    assert specification is not None and specification.loader is not None
    configure_codex = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(configure_codex)

    repository_root = (tmp_path / "含 空格 的仓库").resolve()
    repository_root.mkdir()
    template_path = Path(__file__).with_name("codex-config.toml")
    destination_path = repository_root / ".codex" / "config.toml"

    first_path = configure_codex.materialize_codex_config(
        repository_root, template_path, destination_path
    )
    first_bytes = first_path.read_bytes()
    second_path = configure_codex.materialize_codex_config(
        repository_root, template_path, destination_path
    )

    assert first_path == destination_path == second_path
    assert first_bytes == second_path.read_bytes()
    rendered = first_bytes.decode("utf-8")
    assert "__M1A0_REPOSITORY_ROOT__" not in rendered

    parsed = tomllib.loads(rendered)
    server = parsed["mcp_servers"]["modeling_spike"]
    assert server["cwd"] == str(repository_root)
    assert server["args"] == [
        "run",
        "--locked",
        "--no-sync",
        "python",
        "spikes/m1a_0/server.py",
    ]
    assert server["required"] is True
    assert server["startup_timeout_sec"] == 10
    assert server["tool_timeout_sec"] == 30
    assert server["enabled_tools"] == ["root_finding"]
    assert server["tools"] == {"root_finding": {"approval_mode": "approve"}}

    quoted_marker = '"__M1A0_REPOSITORY_ROOT__"'
    assert configure_codex.render_codex_config(quoted_marker, repository_root) == json.dumps(
        str(repository_root), ensure_ascii=False
    )
