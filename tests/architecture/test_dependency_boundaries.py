from __future__ import annotations

import ast
import inspect
from datetime import datetime
from pathlib import Path
from typing import get_type_hints

from modeling_core.application.facade import ApplicationFacade
from modeling_core.contracts.common import ProjectSummary
from modeling_core.ports.project_store import (
    BeginRunCommand,
    BeginRunResult,
    BeginValidationCommand,
    BeginValidationResult,
    CompleteAttemptCommand,
    CompleteValidationCommand,
    CreateProjectCommand,
    ExperimentTrace,
    ExperimentTraceQuery,
    ProjectStateInspection,
    ProjectStore,
    ProjectWriteResult,
    StoreIntegrityReport,
    StoredRunResult,
    StoredValidationResult,
)


CORE = Path(__file__).parents[2] / "src" / "modeling_core"
FORBIDDEN_IMPORTS = {
    "mcp",
    "sqlite3",
    "modeling_infrastructure",
    "modeling_mcp",
    "modeling_capabilities",
}
HOST_TOKENS = ("Codex", "Claude Code", "TRAE")


def test_core_never_imports_adapters_databases_or_capabilities() -> None:
    violations: list[str] = []
    for path in CORE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                names = [node.module]
            if any(name.split(".")[0] in FORBIDDEN_IMPORTS for name in names):
                violations.append(str(path))
    assert not violations


def test_core_has_no_host_specific_names_in_source_or_annotations() -> None:
    violations = [
        str(path)
        for path in CORE.rglob("*.py")
        if any(token in path.read_text(encoding="utf-8") for token in HOST_TOKENS)
    ]
    assert not violations


def test_project_store_exposes_exact_typed_use_case_methods() -> None:
    methods = {
        name: value
        for name, value in vars(ProjectStore).items()
        if not name.startswith("_") and callable(value)
    }
    assert set(methods) == {
        "inspect_project_state",
        "create_or_replay_project",
        "get_project_summary",
        "get_experiment_trace",
        "begin_run",
        "mark_attempt_running",
        "complete_attempt",
        "begin_validation",
        "mark_validation_running",
        "complete_validation",
        "inspect_integrity",
    }
    assert get_type_hints(methods["inspect_project_state"]) == {
        "return": ProjectStateInspection
    }
    assert get_type_hints(methods["create_or_replay_project"]) == {
        "command": CreateProjectCommand,
        "return": ProjectWriteResult,
    }
    assert get_type_hints(methods["get_project_summary"]) == {
        "project_id": str,
        "return": ProjectSummary,
    }
    assert get_type_hints(methods["get_experiment_trace"]) == {
        "query": ExperimentTraceQuery,
        "return": ExperimentTrace,
    }
    assert get_type_hints(methods["begin_run"]) == {
        "command": BeginRunCommand,
        "return": BeginRunResult,
    }
    assert get_type_hints(methods["mark_attempt_running"]) == {
        "attempt_id": str,
        "started_at": datetime,
        "session_id": str,
        "return": type(None),
    }
    assert get_type_hints(methods["complete_attempt"]) == {
        "command": CompleteAttemptCommand,
        "return": StoredRunResult,
    }
    assert get_type_hints(methods["begin_validation"]) == {
        "command": BeginValidationCommand,
        "return": BeginValidationResult,
    }
    assert get_type_hints(methods["mark_validation_running"]) == {
        "validation_id": str,
        "started_at": datetime,
        "return": type(None),
    }
    assert get_type_hints(methods["complete_validation"]) == {
        "command": CompleteValidationCommand,
        "return": StoredValidationResult,
    }
    assert get_type_hints(methods["inspect_integrity"]) == {
        "deep": bool,
        "return": StoreIntegrityReport,
    }
    assert all(
        annotation is not object
        for method in methods.values()
        for annotation in get_type_hints(method).values()
    )


def test_facade_has_exactly_six_concrete_contract_methods() -> None:
    methods = {
        name: value
        for name, value in vars(ApplicationFacade).items()
        if not name.startswith("_") and callable(value)
    }
    assert set(methods) == {
        "health_check",
        "create_project",
        "get_project_status",
        "list_capabilities",
        "run_experiment",
        "validate_experiment",
    }
    for method in methods.values():
        assert "return" in get_type_hints(method)
        assert "request" in inspect.signature(method).parameters
