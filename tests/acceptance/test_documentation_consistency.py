from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

from modeling_core.contracts.tools import TOOL_NAMES


ROOT = Path(__file__).parents[2]
STABLE_DOCS = (
    Path("README.md"),
    Path("AGENTS.md"),
    Path("docs/context/index.md"),
    Path("docs/product/vision.md"),
    Path("docs/architecture/overview.md"),
    Path("docs/architecture/state-model.md"),
    Path("docs/architecture/security.md"),
    Path("docs/contracts/mcp-tools-v1.md"),
    Path("docs/contracts/capability-api-v1.md"),
    Path("docs/contracts/root-finding-v1.md"),
    Path("docs/operations/recovery.md"),
    Path("docs/operations/schema-evolution.md"),
    Path("docs/operations/release-verification.md"),
    Path("src/modeling_capabilities/root_finding/context.md"),
)
ADR_DOCS = tuple(
    Path("docs/adr") / name
    for name in (
        "0001-modular-monolith.md",
        "0002-ports-adapters-composition-root.md",
        "0003-sqlite-content-addressed-artifacts.md",
        "0004-explicit-built-in-capabilities.md",
        "0005-local-stdio-mcp.md",
        "0006-schema-semver-policy.md",
        "0007-independent-solver-validator.md",
        "0008-single-writer-lock-recovery.md",
    )
)
LINK_RE = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _read(path: Path) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _slug(value: str) -> str:
    value = re.sub(r"<[^>]+>", "", value).replace("`", "").strip().lower()
    value = re.sub(r"[^\w\-\u4e00-\u9fff ]", "", value)
    return re.sub(r"[\s-]+", "-", value).strip("-")


def _anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    anchors: set[str] = set()
    for heading in HEADING_RE.findall(_read(path)):
        base = _slug(heading)
        count = seen.get(base, 0)
        seen[base] = count + 1
        anchors.add(base if count == 0 else f"{base}-{count}")
    return anchors


def test_stable_document_inventory_exists_and_is_nonempty() -> None:
    missing = [
        str(path) for path in (*STABLE_DOCS, *ADR_DOCS) if not (ROOT / path).is_file()
    ]
    assert not missing, f"missing stable documents: {missing}"
    assert all(_read(path).strip() for path in (*STABLE_DOCS, *ADR_DOCS))


def test_local_links_and_heading_anchors_resolve() -> None:
    problems: list[str] = []
    for source in (*STABLE_DOCS, *ADR_DOCS):
        for raw_target in LINK_RE.findall(_read(source)):
            target = raw_target.strip().strip("<>").split(" ", 1)[0]
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            relative, _, fragment = target.partition("#")
            destination = source if not relative else source.parent / unquote(relative)
            resolved = (ROOT / destination).resolve()
            try:
                relative_resolved = resolved.relative_to(ROOT.resolve())
            except ValueError:
                problems.append(f"{source}: link escapes repository: {target}")
                continue
            if not resolved.exists():
                problems.append(f"{source}: missing {relative_resolved}")
            elif (
                fragment
                and resolved.is_file()
                and unquote(fragment) not in _anchors(relative_resolved)
            ):
                problems.append(f"{source}: missing anchor {target}")
    assert not problems, "\n".join(problems)


def test_stable_versions_and_tool_schema_routes_match_executable_assets() -> None:
    tools_doc = _read(Path("docs/contracts/mcp-tools-v1.md"))
    named_tools = {name for name in TOOL_NAMES if f"`{name}`" in tools_doc}
    assert named_tools == set(TOOL_NAMES)
    for name in TOOL_NAMES:
        for role in ("request", "result", "error"):
            assert f"{name}.{role}.schema.json" in tools_doc

    combined = "\n".join(
        _read(path)
        for path in (
            Path("README.md"),
            Path("docs/architecture/overview.md"),
            Path("docs/architecture/state-model.md"),
            Path("docs/contracts/mcp-tools-v1.md"),
        )
    )
    for value in ("0.2.0", "2025-11-25", "modeling-tools/1.0.0", "数据库 Schema `2`"):
        assert value in combined


def test_capability_and_root_contracts_route_every_schema_and_version_axis() -> None:
    capability = _read(Path("docs/contracts/capability-api-v1.md"))
    root = _read(Path("docs/contracts/root-finding-v1.md"))
    for schema in (
        "input.schema.json",
        "canonical-input.schema.json",
        "success-data.schema.json",
        "failure-data.schema.json",
        "policy.schema.json",
        "report.schema.json",
    ):
        assert schema in root
    for term in ("API 版本", "契约版本", "实现版本", "策略版本", "报告版本"):
        assert term in f"{capability}\n{root}"
    assert "Built-in Capability" in capability
    assert "External Plugin" in capability
    assert "不是 External Plugin" in capability


def test_state_security_and_recovery_invariants_are_explicit() -> None:
    state = _read(Path("docs/architecture/state-model.md"))
    for transition in (
        "UNINITIALIZED → STORAGE_READY",
        "STORAGE_READY → READY",
        "PENDING → RUNNING",
        "RUNNING → SUCCEEDED",
        "RUNNING → NUMERICAL_FAILURE",
        "RUNNING → ERRORED",
        "RUNNING → TIMED_OUT",
        "RUNNING → ABANDONED",
    ):
        assert transition in state
    for term in (
        "scope_id",
        "tool_name",
        "operation_id",
        "canonical_request_hash",
        "先发布文件，再提交引用",
    ):
        assert term in state

    security = _read(Path("docs/architecture/security.md"))
    for term in (
        "信任边界",
        "1 MiB",
        "256 KiB",
        "16",
        "64 MiB",
        "10 秒",
        "60 秒",
        "重解析点",
        "单写者锁",
        "STDOUT",
        "秘密",
    ):
        assert term in security

    recovery = _read(Path("docs/operations/recovery.md"))
    for term in ("PENDING", "RUNNING", "IN_PROGRESS", "孤立制品", "不修复", "不迁移"):
        assert term in recovery


def test_adrs_have_complete_accepted_record_shape() -> None:
    for path in ADR_DOCS:
        text = _read(path)
        assert text.startswith("# ")
        assert "- Status: Accepted" in text
        assert "- Date: 2026-07-17" in text
        for heading in (
            "## Context",
            "## Decision",
            "## Consequences",
            "## Rejected Alternatives",
        ):
            assert heading in text, f"{path}: {heading}"


def test_host_scope_roadmap_risks_and_release_authority_are_unambiguous() -> None:
    architecture = _read(Path("docs/architecture/overview.md"))
    vision = _read(Path("docs/product/vision.md"))
    release = _read(Path("docs/operations/release-verification.md"))
    agents = _read(Path("AGENTS.md"))

    assert "Codex 是首个薄适配宿主" in architecture
    assert "Claude Code、TRAE 仅是未来薄适配宿主" in architecture
    for path in (
        *Path("src/modeling_core").rglob("*.py"),
        *Path("src/modeling_infrastructure").rglob("*.py"),
    ):
        assert not re.search(
            r"Codex|Claude Code|TRAE", path.read_text(encoding="utf-8"), re.IGNORECASE
        )

    assert "48 小时非生产可行性探针" in vision
    assert "M1a 完成替代品" in vision and "不是" in vision
    assert "M1 → M2 → M2.5 → M3" in vision
    assert "M1a 仅承诺固定向量与同环境重复执行的 hash smoke" in vision
    assert "B2/M1b" in vision and "完整 RFC 8785" in vision
    for item in (
        "范围增长",
        "宿主耦合",
        "求解器/验证器耦合",
        "状态/制品不一致",
        "协作式超时",
        "Schema 漂移",
        "Windows 路径/进程",
        "证据不可复现",
    ):
        assert item in architecture

    for field in ("`Task`", "`Test result`", "`Git diff summary`", "`Commit hash`"):
        assert field in agents
    assert "uv run --locked --no-sync modeling verify --milestone m1b" in release
    assert "Windows" in release and "Ubuntu" in release and "Codex" in release


def test_external_baselines_and_non_goals_are_owned() -> None:
    contracts = _read(Path("docs/contracts/mcp-tools-v1.md"))
    evolution = _read(Path("docs/operations/schema-evolution.md"))
    release = _read(Path("docs/operations/release-verification.md"))
    combined = f"{contracts}\n{evolution}\n{release}"
    for baseline in (
        "https://modelcontextprotocol.io/specification/2025-11-25/basic/transports",
        "https://github.com/modelcontextprotocol/python-sdk",
        "https://json-schema.org/draft/2020-12",
        "https://www.rfc-editor.org/rfc/rfc8785",
        "uv `0.11.28`",
        "Python `3.11`",
        "actions/checkout@v6",
    ):
        assert baseline in combined

    vision = _read(Path("docs/product/vision.md"))
    for non_goal in (
        "通用硬进程隔离",
        "OCR",
        "UI",
        "多用户服务",
        "自动论文写作",
        "动态插件安装",
        "额外数学能力",
    ):
        assert non_goal in vision
