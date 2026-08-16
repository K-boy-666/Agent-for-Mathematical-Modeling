from __future__ import annotations

import ast
import inspect
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from modeling_harness import verify as verification
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
    "modeling_harness",
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
        "register_problem_assets",
        "put_subproblem_mmir",
        "confirm_subproblem_mmir",
        "export_subproblem",
    }
    for method in methods.values():
        assert "return" in get_type_hints(method)
        assert "request" in inspect.signature(method).parameters


def test_a12_1_snapshot_and_store_tests_do_not_import_modeling_cli_doctor() -> None:
    """Catches A12.1 borrowing the later A12.2 doctor boundary."""
    repository = Path(__file__).parents[2]
    paths = (
        repository / "src/modeling_infrastructure/diagnostic_snapshot.py",
        repository / "tests/contract/test_project_store.py",
    )
    violations: list[str] = []
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = tuple(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module is not None:
                imported = (node.module,)
            else:
                imported = ()
            if any(name == "modeling_cli.doctor" for name in imported):
                violations.append(path.relative_to(repository).as_posix())
    assert violations == []


def test_diagnostic_snapshot_has_no_core_cli_or_source_sqlite_dependency() -> None:
    """Catches a second core port, doctor coupling, or source-lock adapter reuse."""
    module = (
        Path(__file__).parents[2] / "src/modeling_infrastructure/diagnostic_snapshot.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    forbidden = {
        "modeling_cli",
        "modeling_core",
        "modeling_infrastructure.project_lock",
        "modeling_infrastructure.storage",
    }
    assert not {
        name for name in imports if name.split(".")[0] in forbidden or name in forbidden
    }


def test_doctor_has_no_source_sqlite_or_writer_side_effects() -> None:
    """Catches doctor-side SQL, source composition, or a second persistence port."""
    repository = Path(__file__).parents[2]
    module = repository / "src/modeling_cli/doctor.py"
    tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
    imports: set[str] = set()
    calls: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                calls.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                calls.add(node.func.attr)

    assert "sqlite3" not in imports
    source = module.read_text(encoding="utf-8")
    assert "ProjectLock" not in source
    assert calls.isdisjoint({"connect", "execute", "start_writer_session"})


def test_capability_control_errors_are_host_neutral_without_reversing_dependencies() -> (
    None
):
    assert issubclass(EvaluationCancelled, ExecutionCancelled)
    assert issubclass(EvaluationDeadlineExceeded, ExecutionDeadlineExceeded)
    assert issubclass(EvaluationBudgetExceeded, ExecutionResourceLimitExceeded)

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


def test_harness_check_process_is_direct_argv_and_never_a_platform_shell(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Catches a verification check crossing the shell boundary."""
    observed: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        observed.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout="1 passed in 0.01s\n", stderr="")

    spec = verification._CheckSpec(
        check_id="architecture.no-shell",
        argv=("C:/pinned/uv.exe", "run", "pytest", "-q"),
        timeout_seconds=5,
        kind="command",
    )
    monkeypatch.setattr(verification.subprocess, "run", fake_run)

    result = verification._execute_check(
        spec,
        cwd=tmp_path,
        environment={"UV_OFFLINE": "1"},
    )

    assert result.status == "PASS"
    assert len(observed) == 1
    argv, kwargs = observed[0]
    assert argv == ["C:/pinned/uv.exe", "run", "pytest", "-q"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["env"] == {"UV_OFFLINE": "1"}
    assert kwargs["timeout"] == 5
    assert kwargs.get("shell", False) is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is False
