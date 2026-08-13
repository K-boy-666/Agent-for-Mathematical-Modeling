"""M1a security boundaries exercised at their public or byte-level seams."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
from typing import Literal, cast

import anyio
import pytest

from modeling_core.application.facade import ApplicationFacade
from modeling_core.contracts.capability import CapabilityInputResourceLimitExceeded
from modeling_core.contracts.common import Warning
from modeling_core.contracts.tools import (
    HealthCheck,
    HealthCheckRequest,
    HealthCheckResult,
)
from modeling_core.contracts.versions import VersionSet
from modeling_capabilities.root_finding.contracts import (
    EvaluationBudget,
    EvaluationBudgetExceeded,
    EvaluationDeadlineExceeded,
    normalize_root_finding_input,
)
from modeling_infrastructure.project_lock import ProjectLock, StorageConflict
from modeling_infrastructure.storage import StorageError, bootstrap_storage
from modeling_harness import verify as verification
from modeling_mcp.adapter import INLINE_RESPONSE_MAX_BYTES, ModelingMcpAdapter
from modeling_mcp.strict_stdio import (
    DEFAULT_MAX_REQUEST_BYTES,
    _bounded_lines,
    _parse_frame,
)


class _ChunkedInput:
    """Small async byte source preserving the transport's real read contract."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def read1(self, size: int) -> bytes:
        chunk, self._payload = self._payload[:size], self._payload[size:]
        return chunk


async def _collect_lines(source: _ChunkedInput) -> tuple[bytes, ...]:
    lines: list[bytes] = []
    stream: AsyncIterator[bytes] = _bounded_lines(source, DEFAULT_MAX_REQUEST_BYTES)  # type: ignore[arg-type]
    async for line in stream:
        lines.append(line)
    return tuple(lines)


class _HealthOnlyFacade:
    def __init__(self, result: HealthCheckResult) -> None:
        self.result = result

    def health_check(self, request: HealthCheckRequest) -> HealthCheckResult:
        del request
        return self.result


class _StaticClock:
    def __init__(self, value: float = 0.0) -> None:
        self._value = value

    def monotonic(self) -> float:
        return self._value


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


def _sized_health_result(
    template: HealthCheckResult, target_bytes: int
) -> HealthCheckResult:
    minimal = template.model_copy(
        update={"checks": (HealthCheck(name="mcp", status="OK", code="x"),)}
    )
    minimal_bytes = len(
        json.dumps(
            minimal.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert minimal_bytes <= target_bytes
    result = template.model_copy(
        update={
            "checks": (
                HealthCheck(
                    name="mcp",
                    status="OK",
                    code="x" * (1 + target_bytes - minimal_bytes),
                ),
            )
        }
    )
    actual_bytes = len(
        json.dumps(
            result.model_dump(mode="json"),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )
    assert actual_bytes == target_bytes
    return result


def _balanced_sum(leaf_count: int) -> str:
    if leaf_count == 1:
        return "x"
    left_count = leaf_count // 2
    return f"({_balanced_sum(left_count)}+{_balanced_sum(leaf_count - left_count)})"


def test_request_larger_than_one_mib_is_rejected_before_newline() -> None:
    """Catches buffering an unbounded request while waiting for its newline."""
    payload = b"x" * (1_048_576 + 1)

    with pytest.raises(ValueError, match="request byte limit"):
        anyio.run(_collect_lines, _ChunkedInput(payload))


def test_request_at_one_mib_is_emitted_only_after_newline() -> None:
    """Catches an inclusive-limit request being rejected or emitted early."""
    payload = b"x" * 1_048_576

    assert anyio.run(_collect_lines, _ChunkedInput(payload + b"\n")) == (
        payload + b"\n",
    )


def test_actual_structured_response_accepts_256_kib_and_rejects_one_more_byte(
    tmp_path: Path,
) -> None:
    """Catches an off-by-one or character-count response budget."""
    from modeling_bootstrap.composition import build_composition

    composition = build_composition(tmp_path)
    template = composition.application.health_check(HealthCheckRequest())
    at_limit = _sized_health_result(template, 262_144)
    over_limit = _sized_health_result(template, 262_145)
    facade = _HealthOnlyFacade(at_limit)
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    accepted = adapter.call_tool("health_check", {})
    facade.result = over_limit
    rejected = adapter.call_tool("health_check", {})

    assert INLINE_RESPONSE_MAX_BYTES == 262_144
    assert accepted.isError is False
    assert len(accepted.content) == 1
    assert len(accepted.content[0].text.encode("utf-8")) == 262_144  # type: ignore[union-attr]
    assert rejected.isError is True
    assert rejected.structuredContent is not None
    assert rejected.structuredContent["code"] == "RESOURCE_LIMIT_EXCEEDED"
    assert rejected.structuredContent["details"] == {
        "resource": "inline_response_bytes",
        "limit": 262_144,
        "observed": 262_145,
    }


@pytest.mark.parametrize(
    ("expression", "resource", "limit", "observed"),
    [
        (" " * 4_096 + "x", "expression_bytes", 4_096, 4_097),
        ("9" * 65, "numeric_literal_chars", 64, 65),
        (_balanced_sum(129), "ast_nodes", 256, 257),
        ("-" * 32 + "x", "ast_depth", 32, 33),
    ],
)
def test_every_parse_time_expression_budget_fails_with_exact_metadata(
    expression: str,
    resource: str,
    limit: int,
    observed: int,
) -> None:
    """Catches any parser budget being removed, weakened, or misclassified."""
    with pytest.raises(CapabilityInputResourceLimitExceeded) as captured:
        normalize_root_finding_input(
            {"expression": expression, "lower": 0.0, "upper": 2.0}
        )

    assert captured.value.resource == resource
    assert captured.value.limit == limit
    assert captured.value.observed == observed


def test_function_evaluation_budget_never_allows_a_twenty_thousand_first_call() -> None:
    """Catches runtime evaluation-count enforcement moving past its hard cap."""
    budget = EvaluationBudget(
        deadline=1.0,
        clock=_StaticClock(),  # type: ignore[arg-type]
        cancellation=_NeverCancelled(),
    )
    for _ in range(20_000):
        budget.begin_evaluation()

    with pytest.raises(EvaluationBudgetExceeded) as captured:
        budget.begin_evaluation()

    assert captured.value.resource == "function_evaluations"
    assert captured.value.limit == 20_000
    assert captured.value.observed is None


def test_transport_accepts_fifty_warnings_and_fails_closed_on_a_forged_fifty_first(
    tmp_path: Path,
) -> None:
    """Catches the adapter returning an over-budget warning collection."""
    from modeling_bootstrap.composition import build_composition

    template = build_composition(tmp_path).application.health_check(
        HealthCheckRequest()
    )
    warnings = tuple(
        Warning(code=f"warning_{index}", message="bounded warning")
        for index in range(51)
    )
    facade = _HealthOnlyFacade(template.model_copy(update={"warnings": warnings[:50]}))
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, facade))

    accepted = adapter.call_tool("health_check", {})
    facade.result = template.model_copy(update={"warnings": warnings})
    rejected = adapter.call_tool("health_check", {})

    assert accepted.isError is False
    assert accepted.structuredContent is not None
    assert len(accepted.structuredContent["warnings"]) == 50
    assert rejected.isError is True
    assert rejected.structuredContent is not None
    assert rejected.structuredContent["code"] == "INTERNAL_ERROR"


def test_project_lock_is_exclusive_and_reusable_after_release(tmp_path: Path) -> None:
    """Catches two writers owning one project or a released handle leaking."""
    path = tmp_path / "project.lock"
    first = ProjectLock(path, "00000000-0000-4000-8000-000000000001")
    second = ProjectLock(path, "00000000-0000-4000-8000-000000000002")

    first.acquire()
    with pytest.raises(StorageConflict) as captured:
        second.acquire()
    assert captured.value.code == "CONFLICT"
    assert captured.value.retryable is True
    assert captured.value.details == {
        "conflict_type": "project_busy",
        "retry_after_ms": 250,
    }

    first.release()
    second.acquire()
    second.release()
    path.rename(tmp_path / "released.lock")


def test_modeling_symlink_junction_or_reparse_point_is_rejected_without_target_write(
    tmp_path: Path,
) -> None:
    """Catches project storage traversing any redirected directory component."""
    target = tmp_path / "outside"
    target.mkdir()
    marker = target / "marker.bin"
    marker.write_bytes(b"must remain unchanged")
    modeling = tmp_path / ".modeling"
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(modeling), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
    else:
        modeling.symlink_to(target, target_is_directory=True)

    with pytest.raises(StorageError) as captured:
        bootstrap_storage(tmp_path, VersionSet.m1a())

    assert captured.value.code == "SECURITY_VIOLATION"
    assert captured.value.details == {"rule": "unsafe_reparse_point"}
    assert marker.read_bytes() == b"must remain unchanged"


@pytest.mark.parametrize(
    "untrusted_path",
    [
        "../escape",
        "C:/absolute/escape",
        "Z:/cross-drive/escape",
        "//server/share/escape",
        "name\x00suffix",
        "file.txt:alternate-stream",
        "CON",
        "trailing.",
        "trailing ",
    ],
    ids=[
        "parent",
        "absolute",
        "cross-drive",
        "unc",
        "nul",
        "ads",
        "reserved-name",
        "trailing-dot",
        "trailing-space",
    ],
)
def test_public_mcp_contract_rejects_every_untrusted_path_surface(
    untrusted_path: str,
) -> None:
    """Catches a path field entering the path-free create-project contract."""
    adapter = ModelingMcpAdapter(cast(ApplicationFacade, object()))

    result = adapter.call_tool(
        "create_project",
        {
            "operation_id": "00000000-0000-4000-8000-000000000010",
            "project_root": untrusted_path,
        },
    )

    assert result.isError is True
    assert result.structuredContent is not None
    assert result.structuredContent["code"] == "INVALID_REQUEST"
    assert result.structuredContent["details"] == {
        "field_path": "/project_root",
        "reason": "unknown_field",
    }


def test_cooperative_deadline_rejects_work_at_the_exact_boundary() -> None:
    """Catches `>` replacing the normative `>=` deadline comparison."""
    before = EvaluationBudget(
        deadline=1.0,
        clock=_StaticClock(0.999_999),  # type: ignore[arg-type]
        cancellation=_NeverCancelled(),
    )
    before.begin_evaluation()
    before.check_node(1)

    at_boundary = EvaluationBudget(
        deadline=1.0,
        clock=_StaticClock(1.0),  # type: ignore[arg-type]
        cancellation=_NeverCancelled(),
    )
    at_boundary.begin_evaluation()
    with pytest.raises(EvaluationDeadlineExceeded):
        at_boundary.check_node(1)


@pytest.mark.parametrize(
    "polluted_frame",
    [
        b'\xef\xbb\xbf{"jsonrpc":"2.0","id":1,"method":"ping"}\n',
        b"INFO server ready\n",
        b'>>> {"jsonrpc":"2.0","id":1,"method":"ping"}\n',
        b"not-json\n",
    ],
    ids=["bom", "log-line", "prompt", "non-frame"],
)
def test_protocol_parser_fails_closed_on_stdout_pollution_fixture(
    polluted_frame: bytes,
) -> None:
    """Catches BOM, prompts, logs, or non-frames being treated as MCP JSON."""
    with pytest.raises(ValueError):
        _parse_frame(polluted_frame, DEFAULT_MAX_REQUEST_BYTES)


@pytest.mark.parametrize(
    "uv_value",
    [None, "uv.exe"],
    ids=["missing", "relative"],
)
def test_harness_rejects_missing_or_relative_uv_before_running_any_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    uv_value: str | None,
) -> None:
    """Catches PATH fallback or a relative executable entering verification."""
    version_calls: list[list[str]] = []

    def unexpected_version_call(argv: list[str], **_: object) -> None:
        version_calls.append(argv)
        raise AssertionError("invalid UV must fail before a version subprocess")

    monkeypatch.setattr(subprocess, "run", unexpected_version_call)
    if uv_value is None:
        monkeypatch.delenv("UV", raising=False)
    else:
        monkeypatch.setenv("UV", uv_value)

    with pytest.raises(ValueError):
        verification._validate_uv_executable(tmp_path)
    assert version_calls == []


def test_harness_rejects_absolute_nonexistent_uv_before_version_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches an absolute but nonexistent UV path passing preflight."""
    version_calls: list[list[str]] = []

    def unexpected_version_call(argv: list[str], **_: object) -> None:
        version_calls.append(argv)
        raise AssertionError("missing UV file must fail before a child process")

    missing_uv = tmp_path / "missing-uv.exe"
    assert missing_uv.is_absolute()
    assert not missing_uv.exists()
    monkeypatch.setenv("UV", str(missing_uv))
    monkeypatch.setattr(subprocess, "run", unexpected_version_call)

    with pytest.raises(ValueError):
        verification._validate_uv_executable(tmp_path)
    assert version_calls == []


def test_harness_rejects_directory_uv_before_version_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a directory satisfying only an existence check for UV."""
    version_calls: list[list[str]] = []

    def unexpected_version_call(argv: list[str], **_: object) -> None:
        version_calls.append(argv)
        raise AssertionError("UV directory must fail before a child process")

    uv_directory = tmp_path / "uv-directory"
    uv_directory.mkdir()
    monkeypatch.setenv("UV", str(uv_directory))
    monkeypatch.setattr(subprocess, "run", unexpected_version_call)

    with pytest.raises(ValueError):
        verification._validate_uv_executable(tmp_path)
    assert version_calls == []


def test_harness_validates_exact_uv_version_with_explicit_offline_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a wrong uv version, implicit env, shell, or missing timeout."""
    executable = tmp_path / "uv.exe"
    executable.write_bytes(b"test executable seam")
    calls: list[tuple[list[str], dict[str, object]]] = []

    def wrong_version(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, "uv 0.11.27\n", "")

    monkeypatch.setenv("UV", str(executable))
    monkeypatch.setenv("UV_OFFLINE", "0")
    monkeypatch.setenv("A11_INHERITED_SENTINEL", "preserved")
    monkeypatch.setattr(subprocess, "run", wrong_version)

    with pytest.raises(ValueError):
        verification._validate_uv_executable(tmp_path)

    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [str(executable), "--version"]
    assert kwargs["cwd"] == tmp_path
    child_environment = cast(dict[str, str], kwargs["env"])
    assert child_environment["UV"] == str(executable)
    assert child_environment["UV_OFFLINE"] == "1"
    assert child_environment["A11_INHERITED_SENTINEL"] == "preserved"
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["check"] is False
    assert kwargs["timeout"] == 10
    assert kwargs.get("shell", False) is False


def test_harness_accepts_only_the_finite_real_pinned_uv_output_grammar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches rejecting pinned build metadata or accepting attacker suffixes."""
    executable = tmp_path / "uv.exe"
    executable.write_bytes(b"test executable seam")
    monkeypatch.setenv("UV", str(executable))

    def pinned_version(
        argv: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            0,
            "uv 0.11.28 (ebf0f43d7 2026-07-07 x86_64-pc-windows-msvc)\n",
            "",
        )

    monkeypatch.setattr(verification.subprocess, "run", pinned_version)
    assert verification._validate_uv_executable(tmp_path) == executable

    def attacker_suffix(
        argv: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            argv,
            0,
            "uv 0.11.28 attacker-controlled-text\n",
            "",
        )

    monkeypatch.setattr(verification.subprocess, "run", attacker_suffix)
    with pytest.raises(ValueError):
        verification._validate_uv_executable(tmp_path)


def test_private_check_runner_fails_closed_on_timeout_and_never_uses_a_shell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches retries, shell execution, or timeout being reported as PASS."""
    observed: list[tuple[list[str], dict[str, object]]] = []

    def time_out(argv: list[str], **kwargs: object) -> None:
        observed.append((argv, kwargs))
        raise subprocess.TimeoutExpired(argv, 3)

    monkeypatch.setattr(subprocess, "run", time_out)
    spec = verification._CheckSpec(
        check_id="timeout-probe",
        argv=("C:/pinned/uv.exe", "lock", "--check", "--offline"),
        timeout_seconds=3,
        kind="command",
    )

    result = verification._execute_check(
        spec,
        cwd=tmp_path,
        environment={"UV_OFFLINE": "1"},
    )

    assert result.status == "FAIL"
    assert result.exit_code is None
    assert result.diagnostic_code == "timeout"
    assert len(observed) == 1
    argv, kwargs = observed[0]
    assert argv == ["C:/pinned/uv.exe", "lock", "--check", "--offline"]
    assert kwargs["cwd"] == tmp_path
    assert kwargs["env"] == {"UV_OFFLINE": "1"}
    assert kwargs["timeout"] == 3
    assert kwargs.get("shell", False) is False


@pytest.mark.parametrize("kind", ["command", "pytest"])
def test_private_check_runner_converts_nonzero_process_to_fixed_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
) -> None:
    """Catches a nonzero child being reported as PASS or losing its exit code."""
    junit = tmp_path / "nonzero.xml"
    argv = ("C:/pinned/uv.exe", "probe")
    if kind == "pytest":
        argv += (f"--junitxml={junit}",)

    def nonzero(
        process_argv: list[str], **_: object
    ) -> subprocess.CompletedProcess[str]:
        if kind == "pytest":
            junit.write_text(
                '<testsuite tests="1" failures="0" errors="0" skipped="0">'
                "<testcase/></testsuite>",
                encoding="utf-8",
            )
        return subprocess.CompletedProcess(
            process_argv,
            7,
            "SECRET_STDOUT",
            "SECRET_STDERR",
        )

    monkeypatch.setattr(verification.subprocess, "run", nonzero)
    spec = verification._CheckSpec(
        check_id=f"nonzero-{kind}",
        argv=argv,
        timeout_seconds=5,
        kind=cast(Literal["command", "pytest", "wheel"], kind),
    )

    result = verification._execute_check(
        spec,
        cwd=tmp_path,
        environment={"UV_OFFLINE": "1"},
    )

    assert result.status == "FAIL"
    assert result.exit_code == 7
    assert result.diagnostic_code == "nonzero-exit"
    if kind == "pytest":
        assert result.test_counts == verification._TestCounts(1, 1, 0, 0, 0)
    else:
        assert result.test_counts is None


def test_harness_prerequisite_failure_preserves_only_a_redacted_diagnostic(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a prerequisite failure disappearing or leaking host details."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("UV", raising=False)

    exit_code = verification.run_verification(verification.Milestone.M1A)

    assert exit_code == 2
    failures = tuple((tmp_path / "build/verification/m1a/failures").iterdir())
    assert len(failures) == 1
    diagnostic_path = failures[0] / "diagnostic.json"
    diagnostic_text = diagnostic_path.read_text(encoding="utf-8")
    assert json.loads(diagnostic_text) == {
        "schema_version": "m1a-verification-diagnostic/0.1.0",
        "milestone": "m1a",
        "diagnostic_code": "prerequisite-or-publication-failure",
    }
    assert str(tmp_path) not in diagnostic_text


def test_coherent_higher_project_format_fails_as_unsupported_without_overwrite(
    tmp_path: Path,
) -> None:
    """Catches a newer project format being mislabeled as corrupt metadata."""
    root = tmp_path
    bootstrap_storage(root, VersionSet.m1a())
    project_json = root / ".modeling" / "project.json"
    database = root / ".modeling" / "state.sqlite3"
    metadata = json.loads(project_json.read_text(encoding="utf-8"))
    metadata["project_format_version"] = "modeling-project/0.2.0"
    project_json.write_text(
        json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    with closing(sqlite3.connect(database)) as connection:
        connection.execute(
            "UPDATE metadata SET value=? WHERE key='project_format_version'",
            ("modeling-project/0.2.0",),
        )
        connection.commit()
    before_project = project_json.read_bytes()
    before_database = database.read_bytes()

    with pytest.raises(StorageError) as captured:
        bootstrap_storage(root, VersionSet.m1a())

    assert captured.value.code == "UNSUPPORTED_VERSION"
    assert captured.value.details == {
        "subject": "project_format",
        "requested_version": "modeling-project/0.2.0",
        "supported_versions": ["modeling-project/0.1.0"],
    }
    assert project_json.read_bytes() == before_project
    assert database.read_bytes() == before_database


def test_higher_sqlite_version_fails_as_unsupported_without_overwrite(
    tmp_path: Path,
) -> None:
    """Catches a newer database being opened, migrated, or mislabeled corrupt."""
    bootstrap_storage(tmp_path, VersionSet.m1a())
    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    before = database.read_bytes()

    with pytest.raises(StorageError) as captured:
        bootstrap_storage(tmp_path, VersionSet.m1a())

    assert captured.value.code == "UNSUPPORTED_VERSION"
    assert captured.value.details == {
        "subject": "database_schema",
        "requested_version": "2",
        "supported_versions": ["1"],
    }
    assert database.read_bytes() == before


def test_degraded_project_allows_only_health_and_preserves_authoritative_bytes(
    tmp_path: Path,
) -> None:
    """Catches any non-health tool proceeding after project-integrity failure."""
    from modeling_bootstrap.composition import build_composition

    bootstrap_storage(tmp_path, VersionSet.m1a())
    project_json = tmp_path / ".modeling" / "project.json"
    database = tmp_path / ".modeling" / "state.sqlite3"
    metadata = json.loads(project_json.read_text(encoding="utf-8"))
    metadata["canonicalization_version"] = "canonical-json/9.9.9"
    project_json.write_text(
        json.dumps(metadata, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    before_project = project_json.read_bytes()
    before_database = database.read_bytes()
    composition = build_composition(tmp_path)
    composition.start()

    health = composition.adapter.call_tool("health_check", {})
    rejected = {
        "create_project": {"operation_id": "00000000-0000-4000-8000-000000000020"},
        "get_project_status": {"project_id": "00000000-0000-4000-8000-000000000021"},
        "list_capabilities": {},
        "run_experiment": {
            "operation_id": "00000000-0000-4000-8000-000000000022",
            "project_id": "00000000-0000-4000-8000-000000000021",
            "mode": "new",
            "capability": {
                "capability_id": "numerical.root_finding",
                "contract_version": "0.1.0",
            },
            "payload": {"expression": "x", "lower": -1.0, "upper": 1.0},
        },
        "validate_experiment": {
            "operation_id": "00000000-0000-4000-8000-000000000023",
            "project_id": "00000000-0000-4000-8000-000000000021",
            "attempt_id": "00000000-0000-4000-8000-000000000024",
            "expected_result_hash": "sha256:" + "a" * 64,
            "validator_id": "numerical.root_finding.residual",
            "policy_version": "0.1.0",
            "policy": {},
        },
    }
    results = {
        tool_name: composition.adapter.call_tool(tool_name, arguments)
        for tool_name, arguments in rejected.items()
    }
    composition.close()

    assert health.isError is False
    assert health.structuredContent is not None
    assert health.structuredContent["status"] == "DEGRADED"
    assert health.structuredContent["project_state"] == "DEGRADED"
    assert health.structuredContent["ready_for_project_creation"] is False
    for tool_name, result in results.items():
        assert result.isError is True, tool_name
        assert result.structuredContent is not None
        assert result.structuredContent["code"] == "PRECONDITION_FAILED", tool_name
        assert result.structuredContent["details"] == {
            "condition": "project_degraded",
            "current_state": "DEGRADED",
        }, tool_name
    assert project_json.read_bytes() == before_project
    assert database.read_bytes() == before_database


def test_diagnostic_snapshot_rejects_unsafe_source_members_without_sensitive_error_text(
    tmp_path: Path,
) -> None:
    """Catches unsafe layout acceptance and path/OS detail disclosure."""
    from modeling_infrastructure.diagnostic_snapshot import (
        DiagnosticSnapshotError,
        materialize_diagnostic_snapshot,
    )

    bootstrap_storage(tmp_path, VersionSet.m1a())
    secret = "credential-super-secret.txt"
    (tmp_path / ".modeling" / secret).write_bytes(b"do not disclose")

    with pytest.raises(DiagnosticSnapshotError) as captured:
        with materialize_diagnostic_snapshot(tmp_path):
            pass

    assert captured.value.code == "snapshot_invalid"
    rendered = f"{captured.value!s}\n{captured.value!r}"
    assert secret not in rendered
    assert str(tmp_path) not in rendered
    assert "do not disclose" not in rendered
