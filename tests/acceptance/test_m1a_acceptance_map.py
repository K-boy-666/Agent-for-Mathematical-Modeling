from __future__ import annotations

import re
import tomllib
from importlib.resources import files
from pathlib import Path

from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.tools import TOOL_NAMES


REPOSITORY = Path(__file__).parents[2]
CONTEXT_FILES = {
    "AGENTS.md",
    "README.md",
    "docs/architecture/overview.md",
    "docs/context/index.md",
    "docs/contracts/capability-api-v0.md",
    "docs/contracts/mcp-tools-v0.md",
    "docs/contracts/root-finding-v0.md",
    "docs/operations/bootstrap-and-doctor.md",
    "docs/product/m1-scope.md",
    "docs/templates/codex/config.toml",
    "src/modeling_capabilities/AGENTS.md",
    "src/modeling_core/AGENTS.md",
    "src/modeling_mcp/AGENTS.md",
    "tests/AGENTS.md",
}
NESTED_RULES = {
    "src/modeling_core/AGENTS.md": "modeling_core",
    "src/modeling_capabilities/AGENTS.md": "modeling_capabilities",
    "src/modeling_mcp/AGENTS.md": "modeling_mcp",
    "tests/AGENTS.md": "tests",
}


def _text(relative_path: str) -> str:
    return (REPOSITORY / relative_path).read_text(encoding="utf-8")


def _assert_local_links_resolve(relative_path: str) -> None:
    document = REPOSITORY / relative_path
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text("utf-8")):
        target = target.split("#", 1)[0]
        if not target or "://" in target:
            continue
        assert (document.parent / target).resolve().exists(), (relative_path, target)


def test_m1a_context_config_and_acceptance_map_are_complete() -> None:
    """Catches a missing M1a route, task heading, or trusted Codex setting."""
    assert all((REPOSITORY / path).is_file() for path in CONTEXT_FILES)
    for path in sorted(CONTEXT_FILES):
        if path.endswith(".md"):
            _assert_local_links_resolve(path)

    plan = _text("docs/superpowers/plans/2026-07-17-math-modeling-mcp-m1.md")
    assert len(re.findall(r"^### Task M1a-0:", plan, re.MULTILINE)) == 1
    assert re.findall(r"^### Task A(\d+):", plan, re.MULTILINE) == [
        str(index) for index in range(1, 13)
    ]

    config = tomllib.loads(_text("docs/templates/codex/config.toml"))
    assert config == {
        "mcp_servers": {
            "modeling": {
                "command": "uv",
                "args": [
                    "run",
                    "--locked",
                    "--no-sync",
                    "modeling-mcp",
                    "--project-root",
                    ".",
                ],
                "cwd": ".",
                "required": True,
                "startup_timeout_sec": 10,
                "tool_timeout_sec": 65,
                "enabled_tools": list(TOOL_NAMES),
            }
        }
    }

    readme = _text("README.md")
    assert readme.count("spikes/m1a_0/README.md") == 1
    assert "stable hash smoke only" in readme
    assert "trusted project" in readme


def test_m1a_abstraction_budget_and_exact_context_inventory_are_binding() -> None:
    """Catches scope prose growing a new abstraction or duplicating contracts."""
    found = {
        path.relative_to(REPOSITORY).as_posix()
        for directory in (
            "context",
            "product",
            "architecture",
            "contracts",
            "operations",
        )
        for path in (REPOSITORY / "docs" / directory).rglob("*.md")
    }
    assert found == {
        path
        for path in CONTEXT_FILES
        if path.startswith("docs/") and path.endswith(".md")
    }
    assert {
        path.relative_to(REPOSITORY).as_posix()
        for path in REPOSITORY.rglob("AGENTS.md")
        if ".venv" not in path.parts
    } == {"AGENTS.md", *NESTED_RULES}

    root_rules = _text("AGENTS.md")
    assert 100 <= len(root_rules.splitlines()) <= 150
    for required in (
        "ApplicationFacade",
        "ProjectStore",
        "Built-in Capability",
        "Test result",
        "Git diff summary",
        "Commit hash",
        "uv run --locked --no-sync modeling verify --milestone m1a",
    ):
        assert required in root_rules
    for path, scope in NESTED_RULES.items():
        nested = _text(path)
        assert scope in nested
        assert "本文件只补充根规则" in nested

    architecture = _text("docs/architecture/overview.md")
    for abstraction in (
        "ApplicationFacade",
        "ProjectStore",
        "Clock",
        "IdGenerator",
        "BuiltInCapability",
        "CapabilityValidator",
    ):
        assert abstraction in architecture
    for forbidden in (
        "ExecutionBackend",
        "通用事件发布器",
        "动态插件发现器",
        "服务定位器",
        "任务队列",
        "worker 池",
    ):
        assert forbidden in architecture

    contract_routes = "\n".join(
        _text(path)
        for path in (
            "docs/contracts/mcp-tools-v0.md",
            "docs/contracts/capability-api-v0.md",
            "docs/contracts/root-finding-v0.md",
        )
    )
    assert "```json" not in contract_routes
    assert "src/modeling_core/contracts/schemas/tools/0.1.0/" in contract_routes
    assert "src/modeling_core/contracts/schemas/common/0.1.0/" in contract_routes
    assert "src/modeling_capabilities/root_finding/schemas/0.1.0/" in contract_routes
    assert "src/modeling_capabilities/root_finding/context.md" in contract_routes


def test_a12_runtime_and_nested_context_assets_are_installed_offline_without_core_catalog_drift() -> (
    None
):
    """Catches package-data loss or context work mutating the 0.1 tool catalog."""
    for package in ("modeling_core", "modeling_capabilities", "modeling_mcp"):
        installed = files(package).joinpath("AGENTS.md").read_bytes()
        assert installed == (REPOSITORY / "src" / package / "AGENTS.md").read_bytes()

    installed_config = (
        files("modeling_cli").joinpath("templates", "codex", "config.toml").read_bytes()
    )
    assert (
        installed_config
        == (REPOSITORY / "docs/templates/codex/config.toml").read_bytes()
    )

    catalog = SchemaCatalog.load_packaged("0.1.0")
    assert len(catalog.tool_schemas) == 18
    assert catalog.fingerprint == (
        "sha256:b5f4f432df459ba103334f099796d8ef0b74e311921abacf6f84ea43bc2c2f6a"
    )
