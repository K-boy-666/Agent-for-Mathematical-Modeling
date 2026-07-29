"""Fail-closed import-graph guard for the residual validator."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).parents[2] / "src"
_ENTRY = "modeling_capabilities.root_finding.validator"
_ALLOWED_ROOT_FINDING_MODULES = {
    "modeling_capabilities.root_finding.validator",
    "modeling_capabilities.root_finding.descriptor",
    "modeling_capabilities.root_finding.contracts",
    "modeling_capabilities.root_finding.expression",
    "modeling_capabilities.root_finding.expression.syntax",
    (
        "modeling_capabilities.root_finding.expression."
        "validator_evaluator"
    ),
}


def _module_file(module: str) -> Path | None:
    relative = Path(*module.split("."))
    module_file = _SRC / relative.with_suffix(".py")
    if module_file.is_file():
        return module_file
    package_file = _SRC / relative / "__init__.py"
    return package_file if package_file.is_file() else None


def _imports(module: str, path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = module.split(".")[:-node.level]
                imported = ".".join((*base, node.module or ""))
            else:
                imported = node.module or ""
            if imported:
                imported = imported.rstrip(".")
                result.add(imported)
                for alias in node.names:
                    candidate = f"{imported}.{alias.name}"
                    if _module_file(candidate) is not None:
                        result.add(candidate)
    return result


def _local_import_graph(entry: str) -> dict[str, set[str]]:
    pending = [entry]
    visited: set[str] = set()
    graph: dict[str, set[str]] = {}
    while pending:
        module = pending.pop()
        if module in visited:
            continue
        visited.add(module)
        path = _module_file(module)
        assert path is not None, f"local module missing from graph: {module}"
        imports = _imports(module, path)
        graph[module] = imports
        for imported in imports:
            if imported.startswith(("modeling_capabilities.", "modeling_core.")):
                if _module_file(imported) is not None:
                    pending.append(imported)
    return graph


def test_validator_real_import_graph_has_only_explicitly_allowed_modules() -> None:
    graph = _local_import_graph(_ENTRY)
    local_modules = set(graph) | {
        imported for imports in graph.values() for imported in imports
        if imported.startswith(
            ("modeling_capabilities.", "modeling_core.")
        )
    }
    root_finding_modules = {
        module
        for module in local_modules
        if module.startswith("modeling_capabilities.root_finding")
    }
    core_modules = {
        module
        for module in local_modules
        if module.startswith("modeling_core.")
    }
    assert root_finding_modules - _ALLOWED_ROOT_FINDING_MODULES == set()
    assert {
        module
        for module in core_modules
        if not module.startswith("modeling_core.contracts.")
        and module != "modeling_core.ports.clock"
    } == set()
    assert (
        "modeling_capabilities.root_finding.expression.validator_evaluator"
        in local_modules
    )
