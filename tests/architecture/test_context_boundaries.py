from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).parents[2]

NESTED_RULES = (
    "src/modeling_core/AGENTS.md",
    "src/modeling_capabilities/AGENTS.md",
    "src/modeling_mcp/AGENTS.md",
    "src/modeling_infrastructure/AGENTS.md",
    "src/modeling_bootstrap/AGENTS.md",
    "tests/AGENTS.md",
    "docs/AGENTS.md",
    ".agents/skills/AGENTS.md",
)

SKILLS = (
    "add-capability",
    "numerical-validation",
    "stdio-diagnostics",
    "reproducibility-audit",
    "release-verification",
)

ROUTES = {
    "code": ("AGENTS.md", "architecture/overview.md"),
    "schema": ("AGENTS.md", "contracts/"),
    "sqlite-recovery": (
        "modeling_infrastructure/AGENTS.md",
        "operations/recovery.md",
    ),
    "mcp-stdio": ("modeling_mcp/AGENTS.md", "stdio-diagnostics"),
    "numerical-method": ("modeling_capabilities/AGENTS.md", "numerical-validation"),
    "validator": ("modeling_capabilities/AGENTS.md", "numerical-validation"),
    "release": ("tests/AGENTS.md", "release-verification"),
    "documentation": ("docs/AGENTS.md", "architecture/overview.md"),
}


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _frontmatter(text: str) -> dict[str, str]:
    assert text.startswith("---\n")
    end = text.index("\n---\n", 4)
    pairs = {}
    for line in text[4:end].splitlines():
        key, value = line.split(":", 1)
        pairs[key.strip()] = value.strip()
    return pairs


def _markdown_links(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\[[^]]+\]\(([^)#]+)(?:#[^)]+)?\)", text))


def test_nested_rules_exist_and_remain_directory_scoped() -> None:
    """Catches an ungoverned layer or a nested file pretending to be global."""
    for relative_path in NESTED_RULES:
        path = ROOT / relative_path
        assert path.is_file(), relative_path
        text = path.read_text(encoding="utf-8")
        assert "作用域" in text or "scope" in text.lower(), relative_path
        assert str(ROOT) not in text


def test_root_rules_stay_a_compact_router_instead_of_a_contract_copy() -> None:
    """Catches root instructions absorbing layer contracts or test recipes."""
    text = _read("AGENTS.md")
    assert 100 <= len(text.splitlines()) <= 150
    assert "CREATE TABLE" not in text
    assert "```json" not in text
    assert "pytest " not in text
    assert text.count("modeling verify --milestone m1b") == 1


def test_context_index_routes_each_task_class_to_a_distinct_minimum_read_set() -> None:
    """Catches broad context loading or two task classes sharing an ambiguous route."""
    text = _read("docs/context/index.md")
    rows = {
        cells[0]: cells[1:]
        for line in text.splitlines()
        if line.startswith("|")
        if len(cells := tuple(cell.strip() for cell in line.strip("|").split("|"))) == 4
        and cells[0] in ROUTES
    }
    assert set(rows) == set(ROUTES)
    assert len({rows[key] for key in rows}) == len(rows)
    for task, required_fragments in ROUTES.items():
        joined = " ".join(rows[task])
        assert "AGENTS.md" in joined
        assert all(fragment in joined for fragment in required_fragments), task
    assert "capability context only for the selected capability" in text
    assert "do not load unrelated capability mathematics" in text


def test_context_index_declares_one_conflict_authority_chain() -> None:
    """Catches code or examples silently overriding decisions and Schema shape."""
    text = _read("docs/context/index.md")
    chain = (
        "approved spec/accepted ADR",
        "versioned JSON Schema",
        "contract docs",
        "tests",
        "code",
    )
    positions = [text.index(item) for item in chain]
    assert positions == sorted(positions)
    assert "stop the task" in text
    assert "same increment" in text


def test_repository_skills_are_triggerable_procedures_not_contract_copies() -> None:
    """Catches missing triggers, unverifiable guidance, or competing contracts."""
    for name in SKILLS:
        relative_path = f".agents/skills/{name}/SKILL.md"
        text = _read(relative_path)
        frontmatter = _frontmatter(text)
        assert frontmatter == {
            "name": name,
            "description": frontmatter["description"],
        }
        assert frontmatter["description"].startswith("Use when ")
        assert "## Procedure" in text
        assert "## Verification" in text
        assert "## References" in text
        assert _markdown_links(text), relative_path
        assert "```json" not in text
        assert '"properties"' not in text
        assert "additionalProperties" not in text
        assert "dynamic discovery" not in text.lower()
        assert "dynamic install" not in text.lower()


def test_capability_catalog_is_summary_only_and_links_the_stable_root_contract() -> (
    None
):
    """Catches a capability catalog becoming a plugin market or math duplicate."""
    text = _read("docs/capabilities/index.md")
    assert (
        "| capability_id | contract_version | status | summary | context | contract | tests |"
        in text
    )
    assert text.count("| `numerical.root_finding` | `1.0.0` |") == 1
    for fragment in (
        "../../src/modeling_capabilities/root_finding/context.md",
        "../../src/modeling_capabilities/root_finding/descriptor.py",
        "../contracts/capability-api-v1.md",
        "../contracts/root-finding-v1.md",
        "../../src/modeling_capabilities/root_finding/schemas/1.0.0/",
        "modeling verify --capability numerical.root_finding",
    ):
        assert fragment in text
    assert "External Plugin" not in text
    assert "dynamic" not in text.lower()


def test_all_repository_context_links_resolve_locally() -> None:
    """Catches a minimum-read route that cannot be followed offline."""
    files = [ROOT / "docs/context/index.md", ROOT / "docs/capabilities/index.md"]
    files.extend(ROOT / path for path in NESTED_RULES)
    files.extend(ROOT / f".agents/skills/{name}/SKILL.md" for name in SKILLS)
    missing = []
    for path in files:
        for target in _markdown_links(path.read_text(encoding="utf-8")):
            if "://" not in target and not (path.parent / target).resolve().exists():
                missing.append(f"{path.relative_to(ROOT).as_posix()} -> {target}")
    assert missing == []
