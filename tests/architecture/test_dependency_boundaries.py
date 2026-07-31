from __future__ import annotations

import ast
import inspect
from datetime import datetime
from pathlib import Path
from typing import get_type_hints

import pytest

from modeling_core.application.facade import ApplicationFacade
from modeling_capabilities.root_finding.contracts import (
    EvaluationBudgetExceeded,
    EvaluationCancelled,
    EvaluationDeadlineExceeded,
)
from modeling_core.contracts.capability import (
    CapabilityInputRejected,
    CapabilityInputResourceLimitExceeded,
    CapabilitySecurityViolation,
    ExecutionCancelled,
    ExecutionDeadlineExceeded,
    ExecutionResourceLimitExceeded,
)
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
    ProjectStatusSnapshot,
    ProjectStateInspection,
    ProjectStore,
    ProjectWriteResult,
    ValidationSource,
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
        "get_project_status",
        "get_experiment_trace",
        "get_validation_source",
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
    assert get_type_hints(methods["get_project_status"]) == {
        "project_id": str,
        "return": ProjectStatusSnapshot,
    }
    assert get_type_hints(methods["get_experiment_trace"]) == {
        "query": ExperimentTraceQuery,
        "return": ExperimentTrace,
    }
    assert get_type_hints(methods["get_validation_source"]) == {
        "project_id": str,
        "attempt_id": str,
        "return": ValidationSource,
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


def test_capability_control_errors_are_host_neutral_without_reversing_dependencies() -> None:
    assert issubclass(EvaluationCancelled, ExecutionCancelled)
    assert issubclass(
        EvaluationDeadlineExceeded, ExecutionDeadlineExceeded
    )
    assert issubclass(
        EvaluationBudgetExceeded, ExecutionResourceLimitExceeded
    )

    error = EvaluationBudgetExceeded("function_evaluations", 2)
    assert error.resource == "function_evaluations"
    assert error.limit == 2
    assert error.observed is None
    assert str(error) == "function_evaluations limit exceeded: 2"


@pytest.mark.parametrize(
    "arguments",
    [
        ("", 1, None),
        ("resource", -1, None),
        ("resource", True, None),
        ("resource", 1, -1),
        ("resource", 1, False),
    ],
)
def test_host_neutral_resource_error_validates_strict_attributes(
    arguments: tuple[object, object, object],
) -> None:
    with pytest.raises(ValueError):
        ExecutionResourceLimitExceeded(*arguments)


def test_host_neutral_pre_execution_errors_preserve_typed_metadata() -> None:
    rejected = CapabilityInputRejected(
        "/payload/expression",
        "expression_parse_error",
        "expression is malformed",
    )
    security = CapabilitySecurityViolation(
        "math_expr_forbidden_syntax",
        "expression contains forbidden syntax",
    )
    resource = CapabilityInputResourceLimitExceeded(
        "expression_bytes",
        4096,
        4097,
        "expression is too large",
    )

    assert isinstance(rejected, ValueError)
    assert rejected.field_path == "/payload/expression"
    assert rejected.reason == "expression_parse_error"
    assert str(rejected) == "expression is malformed"
    assert isinstance(security, ValueError)
    assert security.rule == "math_expr_forbidden_syntax"
    assert str(security) == "expression contains forbidden syntax"
    assert isinstance(resource, ValueError)
    assert not isinstance(resource, ExecutionResourceLimitExceeded)
    assert resource.resource == "expression_bytes"
    assert resource.limit == 4096
    assert resource.observed == 4097
    assert str(resource) == "expression is too large"


@pytest.mark.parametrize(
    ("factory", "arguments"),
    [
        (CapabilityInputRejected, ("payload", "out_of_range", "diagnostic")),
        (
            CapabilityInputRejected,
            ("/payload/~2bad", "out_of_range", "diagnostic"),
        ),
        (
            CapabilityInputRejected,
            ("/payload", "unknown_reason", "diagnostic"),
        ),
        (CapabilityInputRejected, ("/payload", "out_of_range", "")),
        (CapabilitySecurityViolation, ("unknown_rule", "diagnostic")),
        (
            CapabilitySecurityViolation,
            ("math_expr_forbidden_syntax", ""),
        ),
        (
            CapabilityInputResourceLimitExceeded,
            ("", 1, None, "diagnostic"),
        ),
        (
            CapabilityInputResourceLimitExceeded,
            ("expression_bytes", True, None, "diagnostic"),
        ),
        (
            CapabilityInputResourceLimitExceeded,
            ("expression_bytes", -1, None, "diagnostic"),
        ),
        (
            CapabilityInputResourceLimitExceeded,
            ("expression_bytes", 1, False, "diagnostic"),
        ),
        (
            CapabilityInputResourceLimitExceeded,
            ("expression_bytes", 1, -1, "diagnostic"),
        ),
        (
            CapabilityInputResourceLimitExceeded,
            ("expression_bytes", 1, None, ""),
        ),
    ],
)
def test_host_neutral_pre_execution_errors_reject_invalid_contract_values(
    factory: type[ValueError],
    arguments: tuple[object, ...],
) -> None:
    with pytest.raises(ValueError):
        factory(*arguments)
