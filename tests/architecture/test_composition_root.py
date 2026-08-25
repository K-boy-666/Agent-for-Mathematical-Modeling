from __future__ import annotations

import ast
from pathlib import Path
from uuid import UUID

from mcp.server.lowlevel import Server

from modeling_bootstrap.composition import build_composition
from modeling_capabilities.root_finding.solver import (
    BisectionRootFindingCapability,
)
from modeling_capabilities.root_finding.validator import (
    ResidualRootFindingValidator,
)
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_mcp.adapter import ModelingMcpAdapter


_CONCRETE_MODULES = {
    "mcp.server.lowlevel": frozenset({"Server"}),
    "modeling_capabilities.root_finding.solver": frozenset(
        {"BisectionRootFindingCapability"}
    ),
    "modeling_capabilities.root_finding.validator": frozenset(
        {"ResidualRootFindingValidator"}
    ),
    "modeling_core.application": frozenset({"ModelingApplication"}),
    "modeling_core.application.service": frozenset({"ModelingApplication"}),
    "modeling_infrastructure.sqlite": frozenset({"SQLiteProjectStore"}),
    "modeling_infrastructure.sqlite.store": frozenset({"SQLiteProjectStore"}),
    "modeling_mcp.adapter": frozenset({"ModelingMcpAdapter"}),
}
_CONCRETE_REFERENCES = frozenset(
    f"{module}.{name}" for module, names in _CONCRETE_MODULES.items() for name in names
)
_PURE_REEXPORTS = {
    "modeling_core/application/__init__.py": frozenset(
        {"modeling_core.application.service.ModelingApplication"}
    ),
    "modeling_infrastructure/sqlite/__init__.py": frozenset(
        {"modeling_infrastructure.sqlite.store.SQLiteProjectStore"}
    ),
}


def _import_bindings(tree: ast.AST) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            for alias in node.names:
                bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name.split(".")[0]
                bindings[bound] = alias.name if alias.asname else bound
    return bindings


def _qualified_reference(node: ast.expr, bindings: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return bindings.get(node.id)
    if isinstance(node, ast.Attribute):
        owner = _qualified_reference(node.value, bindings)
        if owner is not None:
            return f"{owner}.{node.attr}"
    return None


def test_composition_seals_the_exact_builtin_registry_and_sole_store(
    tmp_path: Path,
) -> None:
    """Catches an unsealed, substituted, or multiply assembled production graph."""
    composition = build_composition(tmp_path)

    assert composition.registry.sealed is True
    capability = composition.registry.resolve("numerical.root_finding", "1.0.0")
    validator = composition.registry.resolve_validator(
        "numerical.root_finding.residual",
        "numerical.root_finding",
        "1.0.0",
        "1.0.0",
    )
    assert type(capability.implementation) is BisectionRootFindingCapability
    assert type(validator.implementation) is ResidualRootFindingValidator
    assert type(composition.store) is SQLiteProjectStore
    assert type(composition.adapter) is ModelingMcpAdapter
    assert type(composition.server) is Server
    assert composition.application._store is composition.store
    assert composition.adapter._facade is composition.application
    assert composition.application._session_id == composition.session_id
    assert composition.store._project_lock._session_id == composition.session_id
    assert UUID(composition.session_id).version == 4


def test_concrete_assembly_imports_and_calls_exist_only_at_composition_boundary() -> (
    None
):
    """Catches direct, aliased, or qualified secondary concrete assembly."""
    source_root = Path(__file__).parents[2] / "src"
    composition_boundary = "modeling_bootstrap/composition.py"
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        if relative == composition_boundary:
            continue
        allowed_reexports = _PURE_REEXPORTS.get(relative, frozenset())
        bindings = _import_bindings(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module is not None:
                for alias in node.names:
                    imported = f"{node.module}.{alias.name}"
                    imports_concrete_module = imported in _CONCRETE_MODULES
                    if (
                        imported in _CONCRETE_REFERENCES or imports_concrete_module
                    ) and imported not in allowed_reexports:
                        violations.append(
                            f"{relative}:{node.lineno}: import {imported}"
                        )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _CONCRETE_MODULES:
                        violations.append(
                            f"{relative}:{node.lineno}: import {alias.name}"
                        )
            elif isinstance(node, ast.Call):
                called = _qualified_reference(node.func, bindings)
                if called in _CONCRETE_REFERENCES:
                    violations.append(f"{relative}:{node.lineno}: call {called}")

    assert violations == []
