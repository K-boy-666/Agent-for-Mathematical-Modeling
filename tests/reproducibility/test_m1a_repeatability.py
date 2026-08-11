from __future__ import annotations

import json
import math
import os
import stat
import subprocess
import threading
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Iterable, Iterator

import pytest

from modeling_harness import verify as verification
from modeling_capabilities.root_finding.solver import (
    BisectionRootFindingCapability,
)
from modeling_capabilities.root_finding.validator import (
    ResidualRootFindingValidator,
)
from modeling_core.application import ModelingApplication
from modeling_core.contracts.tools import (
    CapabilitySelection,
    CreateProjectRequest,
    EnvironmentSummary,
    GetProjectStatusExperimentRequest,
    RootFindingInput,
    RunExperimentRequest,
    RunExperimentSucceededResult,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.registry import CapabilityRegistry
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import bootstrap_storage


_PACKAGE_ROOTS = (
    "modeling_cli",
    "modeling_capabilities",
    "modeling_core",
    "modeling_harness",
    "modeling_infrastructure",
    "modeling_bootstrap",
    "modeling_mcp",
)


def _write_synthetic_package_wheel(
    wheel: Path,
    *,
    roots: tuple[str, ...] = _PACKAGE_ROOTS,
    extras: tuple[str, ...] = (),
) -> None:
    repository = Path(__file__).parents[2]
    with zipfile.ZipFile(wheel, "w") as archive:
        for root in sorted(set(roots)):
            source_root = repository / "src" / root
            for source in source_root.rglob("*"):
                if not source.is_file() or "__pycache__" in source.parts:
                    continue
                if source.suffix in {".pyc", ".pyo"}:
                    continue
                archive.writestr(
                    source.relative_to(repository / "src").as_posix(),
                    source.read_bytes(),
                )
        for extra in extras:
            archive.writestr(extra, b"unsafe")


class FakeClock:
    def __init__(self, start: datetime, monotonic_start: float = 0.0) -> None:
        self._now = start
        self._monotonic = monotonic_start

    def utc_now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic


class FixedIdGenerator:
    def __init__(self, values: Iterable[str]) -> None:
        self._values: Iterator[str] = iter(values)

    def new_uuid4(self) -> str:
        return next(self._values)


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


def _uuid(index: int) -> str:
    return f"10000000-0000-4000-8000-{index:012x}"


def _build_application(project_root: Path) -> ModelingApplication:
    versions = VersionSet.m1a()
    bootstrap_storage(project_root, versions)
    registry = CapabilityRegistry(versions)
    registry.register_capability(BisectionRootFindingCapability())
    registry.register_validator(ResidualRootFindingValidator())
    registry_summary = registry.seal(frozenset())
    return ModelingApplication(
        store=SQLiteProjectStore(project_root, versions),
        registry=registry,
        registry_summary=registry_summary,
        versions=versions,
        clock=FakeClock(datetime(2026, 7, 17, tzinfo=UTC)),
        id_generator=FixedIdGenerator(_uuid(index) for index in range(100, 150)),
        session_id=_uuid(90),
        environment_summary=EnvironmentSummary(
            python_version="3.11.14",
            application_version="0.1.0",
            lock_hash="sha256:" + ("2" * 64),
        ),
        cancellation=_NeverCancelled(),
        default_display_name="M1a repeatability",
    )


def test_distinct_experiments_preserve_deterministic_identity_and_result(
    tmp_path: Path,
) -> None:
    """Catches repeated runs that drift in contracts, hashes, or root value."""
    application = _build_application(tmp_path)
    project = application.create_project(CreateProjectRequest(operation_id=_uuid(1)))

    selection = CapabilitySelection(
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
    )
    payload = RootFindingInput(
        expression="x*x - 2",
        lower=0.0,
        upper=2.0,
    )
    first = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(2),
            project_id=project.project_id,
            mode="new",
            capability=selection,
            payload=payload,
        )
    )
    second = application.run_experiment(
        RunExperimentRequest(
            operation_id=_uuid(3),
            project_id=project.project_id,
            mode="new",
            capability=selection,
            payload=payload,
        )
    )

    assert isinstance(first, RunExperimentSucceededResult)
    assert isinstance(second, RunExperimentSucceededResult)
    assert first.experiment_id != second.experiment_id
    assert first.attempt_status == second.attempt_status == "SUCCEEDED"
    assert first.result_kind == second.result_kind == "success"
    assert (
        first.capability_id,
        first.contract_version,
        first.implementation_id,
        first.implementation_version,
    ) == (
        second.capability_id,
        second.contract_version,
        second.implementation_id,
        second.implementation_version,
    )

    first_trace = application.get_project_status(
        GetProjectStatusExperimentRequest(
            project_id=project.project_id,
            view="experiment",
            experiment_id=first.experiment_id,
        )
    )
    second_trace = application.get_project_status(
        GetProjectStatusExperimentRequest(
            project_id=project.project_id,
            view="experiment",
            experiment_id=second.experiment_id,
        )
    )
    assert (
        first_trace.experiment.canonical_payload_hash,
        first_trace.experiment.model_snapshot_hash,
        first_trace.experiment.data_snapshot_set_hash,
    ) == (
        second_trace.experiment.canonical_payload_hash,
        second_trace.experiment.model_snapshot_hash,
        second_trace.experiment.data_snapshot_set_hash,
    )
    assert math.isclose(
        first.result_summary.root,
        second.result_summary.root,
        rel_tol=0.0,
        abs_tol=1e-12,
    )


def test_source_inventory_is_utf8_ordered_and_changes_with_file_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches trusting Git order, locale sort, or stale file bytes."""
    (tmp_path / "z.txt").write_bytes(b"Z")
    (tmp_path / "é.txt").write_bytes(b"E")
    (tmp_path / "中.txt").write_bytes(b"C")
    (tmp_path / "ignored.tmp").write_bytes(b"ignored")
    git_stdout = "中.txt\0é.txt\0z.txt\0".encode("utf-8")
    calls: list[tuple[list[str], dict[str, object]]] = []
    monkeypatch.setenv("UV_OFFLINE", "0")
    monkeypatch.setenv("A11_GIT_SENTINEL", "preserved")

    def deliberately_unsorted_git_result(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, git_stdout, b"")

    monkeypatch.setattr(subprocess, "run", deliberately_unsorted_git_result)

    first = verification._collect_source_inventory(tmp_path)

    assert [entry.path for entry in first.entries] == ["z.txt", "é.txt", "中.txt"]
    assert [entry.sha256 for entry in first.entries] == [
        "sha256:bbeebd879e1dff6918546dc0c179fdde505f2a21591c9a9c96e36b054ec5af83",
        "sha256:a9f51566bd6705f7ea6ad54bb9deb449f795582d6529a0e22207b8981233ec58",
        "sha256:6b23c0d5f35d1b11f9b683f0b0a617355deb11277d91ae091d399c655b87940d",
    ]
    assert first.fingerprint == (
        "sha256:7e3c8ab668700b27a3471f7b0c8c073f45bbe7858bc727d508373e1d3360bbca"
    )
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [
        "git",
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
    ]
    assert kwargs["cwd"] == tmp_path
    assert kwargs.get("shell", False) is False
    child_environment = kwargs["env"]
    assert isinstance(child_environment, dict)
    assert child_environment["UV_OFFLINE"] == "1"
    assert child_environment["A11_GIT_SENTINEL"] == "preserved"

    (tmp_path / "中.txt").write_bytes(b"D")
    second = verification._collect_source_inventory(tmp_path)

    assert [entry.path for entry in second.entries] == ["z.txt", "é.txt", "中.txt"]
    assert second.entries[0:2] == first.entries[0:2]
    assert second.entries[2].sha256 == (
        "sha256:3f39d5c348e5b79d06e842c114e6cc571583bbf44e4b0ebfda1a01ec05745d43"
    )
    assert second.fingerprint == (
        "sha256:64effa6cf91bdc717c96fdb8e59b8085db9fc7067752d34bd7d36ecda7db9e39"
    )
    assert second.fingerprint != first.fingerprint
    assert len(calls) == 2


def test_source_inventory_rejects_unsafe_ambiguous_or_missing_git_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches trusting hostile Git paths or hashing a nonexistent entry."""
    (tmp_path / "same.txt").write_bytes(b"same")
    (tmp_path / "é.txt").write_bytes(b"nfc")
    outputs = (
        b"missing.txt\0",
        b"../outside.txt\0",
        b"/absolute.txt\0",
        b"same.txt\0same.txt\0",
        "é.txt\0e\u0301.txt\0".encode("utf-8"),
    )

    for stdout in outputs:
        monkeypatch.setattr(
            verification.subprocess,
            "run",
            lambda argv, stdout=stdout, **_: subprocess.CompletedProcess(
                argv, 0, stdout, b""
            ),
        )
        with pytest.raises((OSError, ValueError)):
            verification._collect_source_inventory(tmp_path)


def test_source_inventory_rejects_a_redirected_nonregular_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches following a symlink or reparse parent outside the inventory."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.txt").write_bytes(b"external")
    redirected = tmp_path / "redirected"
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(redirected), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
    else:
        redirected.symlink_to(outside, target_is_directory=True)

    stdout = b"redirected/payload.txt\0"
    monkeypatch.setattr(
        verification.subprocess,
        "run",
        lambda argv, **_: subprocess.CompletedProcess(argv, 0, stdout, b""),
    )

    with pytest.raises(ValueError):
        verification._collect_source_inventory(tmp_path)


def test_source_inventory_handle_never_follows_a_post_validation_redirect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches lstat-to-read replacement hashing bytes outside the repository."""
    owned = tmp_path / "owned"
    owned.mkdir()
    (owned / "payload.txt").write_bytes(b"repository-owned")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "payload.txt").write_bytes(b"external-attacker-bytes")
    backup = tmp_path / "owned-backup"
    validated = threading.Event()
    replaced = threading.Event()
    real_validator = verification._is_regular_inventory_path
    real_subprocess_run = subprocess.run

    def pause_after_validation(
        repository_root: Path,
        relative: verification.PurePosixPath,
    ) -> bool:
        result = real_validator(repository_root, relative)
        validated.set()
        assert replaced.wait(timeout=5)
        return result

    def attacker() -> None:
        assert validated.wait(timeout=5)
        owned.rename(backup)
        if os.name == "nt":
            completed = real_subprocess_run(
                ["cmd", "/c", "mklink", "/J", str(owned), str(outside)],
                capture_output=True,
                text=True,
                check=False,
            )
            assert completed.returncode == 0, completed.stderr or completed.stdout
        else:
            owned.symlink_to(outside, target_is_directory=True)
        replaced.set()

    monkeypatch.setattr(
        verification.subprocess,
        "run",
        lambda argv, **_: subprocess.CompletedProcess(
            argv, 0, b"owned/payload.txt\0", b""
        ),
    )
    monkeypatch.setattr(
        verification,
        "_is_regular_inventory_path",
        pause_after_validation,
    )
    thread = threading.Thread(target=attacker)
    thread.start()
    try:
        with pytest.raises((OSError, ValueError)):
            verification._collect_source_inventory(tmp_path)
    finally:
        thread.join(timeout=5)
        assert not thread.is_alive()
        if owned.exists() or owned.is_symlink():
            if os.name == "nt":
                owned.rmdir()
            else:
                owned.unlink()
        backup.rename(owned)

    monkeypatch.setattr(
        verification,
        "_is_regular_inventory_path",
        real_validator,
    )
    stable = verification._collect_source_inventory(tmp_path)
    assert stable.entries == (
        verification._SourceEntry(
            "owned/payload.txt",
            "sha256:372f6460dcfadcbb9b821776b308b8d324d57222a6414ecf403358a3a6c9a034",
        ),
    )


def test_posix_inventory_hash_uses_nofollow_dirfds_and_reads_the_final_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches reopening a validated path or omitting non-following dirfd traversal."""
    nofollow = 0x0100
    directory = 0x0200
    cloexec = 0x0400
    opened: list[tuple[object, int, int | None]] = []
    reads: list[tuple[int, int]] = []
    closed: list[int] = []
    descriptors = iter((10, 11, 12))
    chunks = iter((b"repository-owned", b""))

    monkeypatch.setattr(verification.os, "O_NOFOLLOW", nofollow, raising=False)
    monkeypatch.setattr(verification.os, "O_DIRECTORY", directory, raising=False)
    monkeypatch.setattr(verification.os, "O_CLOEXEC", cloexec, raising=False)

    def fake_open(
        path: object,
        flags: int,
        *,
        dir_fd: int | None = None,
    ) -> int:
        opened.append((path, flags, dir_fd))
        return next(descriptors)

    def fake_fstat(descriptor: int) -> object:
        mode = stat.S_IFDIR if descriptor == 11 else stat.S_IFREG
        return SimpleNamespace(st_mode=mode)

    def fake_read(descriptor: int, size: int) -> bytes:
        reads.append((descriptor, size))
        return next(chunks)

    monkeypatch.setattr(verification.os, "open", fake_open)
    monkeypatch.setattr(verification.os, "fstat", fake_fstat)
    monkeypatch.setattr(verification.os, "read", fake_read)
    monkeypatch.setattr(verification.os, "close", closed.append)

    digest = verification._hash_posix_inventory_file(
        tmp_path,
        verification.PurePosixPath("owned/payload.txt"),
    )

    assert digest == (
        "sha256:372f6460dcfadcbb9b821776b308b8d324d57222a6414ecf403358a3a6c9a034"
    )
    assert opened == [
        (tmp_path, os.O_RDONLY | directory | cloexec, None),
        ("owned", os.O_RDONLY | directory | nofollow | cloexec, 10),
        ("payload.txt", os.O_RDONLY | nofollow | cloexec, 11),
    ]
    assert reads == [(12, 1024 * 1024), (12, 1024 * 1024)]
    assert closed == [12, 11, 10]


def test_synthetic_wheel_inventory_is_utf8_ordered_and_hashes_real_payload(
    tmp_path: Path,
) -> None:
    """Catches locale ordering or hashing something other than wheel bytes."""
    wheel = tmp_path / "synthetic.whl"
    _write_synthetic_package_wheel(wheel)

    assets = verification._inspect_package_assets(Path(__file__).parents[2], tmp_path)

    assert len(assets) == 85
    assert [asset.path for asset in assets] == sorted(
        (asset.path for asset in assets), key=lambda value: value.encode("utf-8")
    )
    by_path = {asset.path: asset.sha256 for asset in assets}
    assert by_path["modeling_core/__init__.py"] == (
        "sha256:15f7b910cd4839693ed64a189b6f9c617cde14c0299298a98596e7bb18f4ec90"
    )
    assert by_path["modeling_infrastructure/sqlite/schema_v1.sql"] == (
        "sha256:c9595963e1ab665b6035a49bb9ea5b665b8251a36618d5f3d462d24f2ad67461"
    )
    assert sum(not asset.path.endswith(".py") for asset in assets) == 32


def test_wheel_inventory_requires_the_exact_unique_seven_package_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches a duplicate pure-Python root masking an omitted package."""
    roots = tuple(root for root in _PACKAGE_ROOTS if root != "modeling_cli") + (
        "modeling_harness",
    )
    wheel = tmp_path / "duplicate-root.whl"
    _write_synthetic_package_wheel(wheel, roots=roots)
    monkeypatch.setattr(
        verification.tomllib,
        "loads",
        lambda _: {
            "tool": {
                "hatch": {
                    "build": {
                        "targets": {
                            "wheel": {"packages": [f"src/{root}" for root in roots]}
                        }
                    }
                }
            }
        },
    )

    with pytest.raises(ValueError):
        verification._inspect_package_assets(Path(__file__).parents[2], tmp_path)


@pytest.mark.parametrize(
    "unsafe_member",
    [
        "/absolute.txt",
        "C:/escape.txt",
        "\\\\server\\share\\escape.txt",
        "\\rooted\\escape.txt",
        "modeling_core\\payload.py",
        "modeling_core\\..\\escape.txt",
        "../escape.txt",
        "spikes/escape.py",
        "../escape/",
        "C:/escape/",
        "spikes/",
    ],
    ids=[
        "posix-absolute",
        "drive",
        "unc",
        "rooted",
        "backslash",
        "backslash-parent",
        "parent",
        "spikes",
        "parent-directory",
        "drive-directory",
        "spikes-directory",
    ],
)
def test_wheel_inventory_rejects_every_cross_platform_unsafe_member(
    tmp_path: Path,
    unsafe_member: str,
) -> None:
    """Catches unsafe ZIP names being ignored as harmless metadata."""
    wheel = tmp_path / "unsafe.whl"
    _write_synthetic_package_wheel(wheel, extras=(unsafe_member,))

    with pytest.raises(ValueError):
        verification._inspect_package_assets(Path(__file__).parents[2], tmp_path)


def test_wheel_inventory_rejects_multiple_wheels(tmp_path: Path) -> None:
    """Catches selecting one wheel from an ambiguous build output."""
    for name in ("first.whl", "second.whl"):
        with zipfile.ZipFile(tmp_path / name, "w"):
            pass

    with pytest.raises(ValueError):
        verification._inspect_package_assets(Path(__file__).parents[2], tmp_path)


def test_pytest_check_uses_junit_counts_and_rejects_a_required_skip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches terminal-prose counting or a required test being skipped."""
    junit_path = tmp_path / "check.xml"
    spec = verification._CheckSpec(
        check_id="pytest-unit",
        argv=(
            "C:/pinned/uv.exe",
            "run",
            "pytest",
            "tests/unit",
            "-q",
            f"--junitxml={junit_path}",
        ),
        timeout_seconds=5,
        kind="pytest",
    )

    def passing_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        junit_path.write_text(
            '<testsuites name="pytest tests"><testsuite name="pytest" tests="2" '
            'failures="0" errors="0" skipped="0">'
            "<testcase/><testcase/></testsuite></testsuites>",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, "localized output", "")

    monkeypatch.setattr(verification.subprocess, "run", passing_run)
    passed = verification._execute_check(
        spec,
        cwd=tmp_path,
        environment={"UV_OFFLINE": "1"},
    )

    assert passed.status == "PASS"
    assert passed.test_counts == verification._TestCounts(
        total=2,
        passed=2,
        failed=0,
        errors=0,
        skipped=0,
    )

    def skipped_run(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        junit_path.write_text(
            '<testsuite tests="2" failures="0" errors="0" skipped="1">'
            "<testcase/><testcase><skipped/></testcase></testsuite>",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, "2 tests", "")

    monkeypatch.setattr(verification.subprocess, "run", skipped_run)
    skipped = verification._execute_check(
        spec,
        cwd=tmp_path,
        environment={"UV_OFFLINE": "1"},
    )

    assert skipped.status == "FAIL"
    assert skipped.test_counts is not None
    assert skipped.test_counts.skipped == 1
    assert skipped.diagnostic_code == "required-skip"


def test_verification_outcome_keeps_only_a12_incomplete_and_can_transition() -> None:
    """Catches A11 returning success or A12 retaining a synthetic blocker."""
    passed = verification._CheckResult(
        check_id="lock",
        status="PASS",
        duration_ms=1,
        exit_code=0,
        test_counts=None,
        diagnostic_code=None,
    )
    failed = verification._CheckResult(
        check_id="lock",
        status="FAIL",
        duration_ms=1,
        exit_code=1,
        test_counts=None,
        diagnostic_code="nonzero-exit",
    )

    assert verification._verification_outcome(
        (passed,), verification._a12_incomplete_groups()
    ) == ("INCOMPLETE", 2)
    assert verification._verification_outcome((passed,), []) == ("PASSED", 0)
    assert verification._verification_outcome(
        (failed,), verification._a12_incomplete_groups()
    ) == ("FAILED", 1)


def test_fake_private_runner_publishes_exact_a11_profile_without_recursion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches reordered checks, recursive pytest, or partial publication."""
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "uv.lock").write_bytes(b"locked")
    uv = repository / "uv.exe"
    uv.write_bytes(b"pinned uv")
    hostile_golden = tmp_path / "hostile-golden"
    hostile_golden.mkdir()
    monkeypatch.setenv(
        "MODELING_M1A_GOLDEN_EVIDENCE_DIR",
        str(hostile_golden),
    )
    fingerprint_hex = "a" * 64
    source_inventory = verification._SourceInventory(
        entries=(
            verification._SourceEntry(
                path="uv.lock",
                sha256="sha256:" + "b" * 64,
            ),
        ),
        fingerprint="sha256:" + fingerprint_hex,
    )
    monkeypatch.setattr(
        verification,
        "_validate_uv_executable",
        lambda _: uv,
    )
    monkeypatch.setattr(
        verification,
        "_collect_source_inventory",
        lambda _: source_inventory,
    )
    monkeypatch.setattr(
        verification,
        "_inspect_package_assets",
        lambda *_: (
            verification._PackageAsset(
                path="modeling_core/__init__.py",
                sha256="sha256:" + "c" * 64,
            ),
        ),
    )
    observed: list[tuple[verification._CheckSpec, dict[str, str]]] = []

    def fake_runner(
        spec: verification._CheckSpec,
        *,
        cwd: Path,
        environment: dict[str, str],
    ) -> verification._CheckResult:
        assert cwd == repository
        observed.append((spec, dict(environment)))
        if spec.check_id == "stdio-golden":
            staging = Path(environment["MODELING_M1A_GOLDEN_EVIDENCE_DIR"])
            (staging / "stdio-transcript.json").write_text(
                '{"events":[],"schema_version":"m1a-stdio-transcript/0.1.0"}\n',
                encoding="utf-8",
            )
            (staging / "golden-trace.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m1a-golden-trace/0.1.0",
                        "project_id": "00000000-0000-4000-8000-000000000001",
                        "experiment_id": "00000000-0000-4000-8000-000000000002",
                        "attempt_id": "00000000-0000-4000-8000-000000000003",
                        "validation_id": "00000000-0000-4000-8000-000000000004",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        counts = (
            verification._TestCounts(1, 1, 0, 0, 0) if spec.kind == "pytest" else None
        )
        return verification._CheckResult(
            check_id=spec.check_id,
            status="PASS",
            duration_ms=1,
            exit_code=0,
            test_counts=counts,
            diagnostic_code=None,
        )

    exit_code = verification._run_m1a_verification(
        repository,
        check_runner=fake_runner,
    )

    assert exit_code == 2
    assert [spec.check_id for spec, _ in observed] == [
        "uv-lock",
        "ruff-check",
        "ruff-format",
        "mypy",
        "pytest-unit",
        "pytest-contract",
        "pytest-math",
        "pytest-architecture",
        "pytest-integration",
        "pytest-reproducibility",
        "pytest-security",
        "wheel",
        "stdio-golden",
    ]
    internal = (
        repository
        / "build/verification/m1a"
        / f".{fingerprint_hex}.staging"
        / ".internal"
    )
    assert [
        (spec.argv[1:], spec.timeout_seconds, spec.kind) for spec, _ in observed
    ] == [
        (("lock", "--check", "--offline"), 30, "command"),
        (
            ("run", "--locked", "--no-sync", "ruff", "check", "src", "tests"),
            60,
            "command",
        ),
        (
            (
                "run",
                "--locked",
                "--no-sync",
                "ruff",
                "format",
                "--check",
                "src",
                "tests",
            ),
            60,
            "command",
        ),
        (("run", "--locked", "--no-sync", "mypy", "src"), 120, "command"),
        (
            (
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                "tests/unit",
                "-q",
                f"--junitxml={internal / 'pytest-unit.xml'}",
            ),
            180,
            "pytest",
        ),
        (
            (
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                "tests/contract",
                "-q",
                f"--junitxml={internal / 'pytest-contract.xml'}",
            ),
            180,
            "pytest",
        ),
        (
            (
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                "tests/math",
                "-q",
                f"--junitxml={internal / 'pytest-math.xml'}",
            ),
            180,
            "pytest",
        ),
        (
            (
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                "tests/architecture",
                "-q",
                f"--junitxml={internal / 'pytest-architecture.xml'}",
            ),
            180,
            "pytest",
        ),
        (
            (
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                "tests/integration",
                "-q",
                f"--junitxml={internal / 'pytest-integration.xml'}",
            ),
            180,
            "pytest",
        ),
        (
            (
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                "tests/reproducibility",
                "-q",
                f"--junitxml={internal / 'pytest-reproducibility.xml'}",
            ),
            180,
            "pytest",
        ),
        (
            (
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                "tests/security",
                "-q",
                f"--junitxml={internal / 'pytest-security.xml'}",
            ),
            180,
            "pytest",
        ),
        (
            (
                "build",
                "--wheel",
                "--offline",
                "--out-dir",
                str(internal / "wheel"),
            ),
            120,
            "wheel",
        ),
        (
            (
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                "tests/integration/test_stdio_golden_m1a.py::"
                "test_official_client_completes_m1a_golden_chain_records_"
                "protocol_purity_and_closes_child",
                "-q",
                f"--junitxml={internal / 'stdio-golden.xml'}",
            ),
            120,
            "pytest",
        ),
    ]
    assert all(spec.argv[0] == str(uv) for spec, _ in observed)
    assert all(environment["UV_OFFLINE"] == "1" for _, environment in observed)
    assert all(
        "MODELING_M1A_GOLDEN_EVIDENCE_DIR" not in environment
        for spec, environment in observed
        if spec.check_id != "stdio-golden"
    )
    final = repository / "build" / "verification" / "m1a" / fingerprint_hex
    assert sorted(path.name for path in final.iterdir()) == [
        "SUMMARY.md",
        "architecture-report.json",
        "golden-trace.json",
        "package-assets.json",
        "source-inventory.json",
        "stdio-transcript.json",
        "verification-report.json",
    ]
    report = json.loads((final / "verification-report.json").read_text("utf-8"))
    assert set(report) == {
        "schema_version",
        "milestone",
        "status",
        "source_fingerprint",
        "required_skips",
        "environment",
        "checks",
        "artifacts",
        "golden_ids",
        "incomplete_groups",
    }
    assert set(report["environment"]) == {
        "python_version",
        "uv_version",
        "uv_executable_sha256",
        "os_family",
        "os_version",
        "architecture",
        "lock_sha256",
    }
    assert all(
        set(check)
        == {
            "check_id",
            "status",
            "duration_ms",
            "exit_code",
            "test_counts",
            "diagnostic_code",
        }
        for check in report["checks"]
    )
    assert all(
        check["test_counts"] is None
        or set(check["test_counts"])
        == {"total", "passed", "failed", "errors", "skipped"}
        for check in report["checks"]
    )
    assert [check["test_counts"] for check in report["checks"]] == [
        None,
        None,
        None,
        None,
        {"total": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0},
        {"total": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0},
        {"total": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0},
        {"total": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0},
        {"total": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0},
        {"total": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0},
        {"total": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0},
        None,
        {"total": 1, "passed": 1, "failed": 0, "errors": 0, "skipped": 0},
    ]
    assert set(report["golden_ids"]) == {
        "project_id",
        "experiment_id",
        "attempt_id",
        "validation_id",
    }
    assert report["schema_version"] == "m1a-verification-report/0.1.0"
    assert report["milestone"] == "m1a"
    assert report["status"] == "INCOMPLETE"
    assert report["source_fingerprint"] == "sha256:" + fingerprint_hex
    assert report["required_skips"] == 0
    assert report["environment"]["uv_version"] == "0.11.28"
    assert report["environment"]["uv_executable_sha256"] == (
        "sha256:d348d95e3e9a44de63d07242bfe9ee859a917a050972d05bc7de651dc5e016d8"
    )
    assert report["environment"]["lock_sha256"] == (
        "sha256:14493f5f5470ed48c3f103d917ec52ae9005fa3913128031d0fac2a49ac3cc41"
    )
    assert report["golden_ids"] == {
        "project_id": "00000000-0000-4000-8000-000000000001",
        "experiment_id": "00000000-0000-4000-8000-000000000002",
        "attempt_id": "00000000-0000-4000-8000-000000000003",
        "validation_id": "00000000-0000-4000-8000-000000000004",
    }
    assert all(check["status"] == "PASS" for check in report["checks"])
    assert all(check["exit_code"] == 0 for check in report["checks"])
    assert all(check["diagnostic_code"] is None for check in report["checks"])
    assert report["status"] == "INCOMPLETE"
    assert report["required_skips"] == 0
    assert report["incomplete_groups"] == verification._a12_incomplete_groups()
    assert [check["check_id"] for check in report["checks"]] == [
        spec.check_id for spec, _ in observed
    ]
    assert report["artifacts"] == {
        "source_inventory": "source-inventory.json",
        "package_assets": "package-assets.json",
        "architecture_report": "architecture-report.json",
        "stdio_transcript": "stdio-transcript.json",
        "golden_trace": "golden-trace.json",
    }

    transition_hex = "9" * 64
    transition_inventory = verification._SourceInventory(
        entries=source_inventory.entries,
        fingerprint="sha256:" + transition_hex,
    )
    monkeypatch.setattr(
        verification,
        "_collect_source_inventory",
        lambda _: transition_inventory,
    )
    observed.clear()
    transition_exit = verification._run_m1a_verification(
        repository,
        check_runner=fake_runner,
        incomplete_groups=[],
    )
    transition = json.loads(
        (
            repository
            / "build/verification/m1a"
            / transition_hex
            / "verification-report.json"
        ).read_text("utf-8")
    )
    assert transition_exit == 0
    assert transition["status"] == "PASSED"
    assert transition["incomplete_groups"] == []


def test_windows_environment_architecture_has_a_nonempty_stable_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches an empty architecture claim on restricted Windows hosts."""
    monkeypatch.setattr(verification.platform, "machine", lambda: "")
    monkeypatch.setattr(verification.sysconfig, "get_platform", lambda: "win-amd64")

    assert verification._architecture_label() == "AMD64"


def test_failed_golden_check_publishes_redacted_fingerprinted_failed_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches an executed golden failure becoming an exit-2 staging leak."""
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "uv.lock").write_bytes(b"locked")
    uv = repository / "uv.exe"
    uv.write_bytes(b"pinned uv")
    fingerprint_hex = "d" * 64
    inventory = verification._SourceInventory(
        entries=(verification._SourceEntry("uv.lock", "sha256:" + "e" * 64),),
        fingerprint="sha256:" + fingerprint_hex,
    )
    monkeypatch.setattr(verification, "_validate_uv_executable", lambda _: uv)
    monkeypatch.setattr(verification, "_collect_source_inventory", lambda _: inventory)
    monkeypatch.setattr(
        verification,
        "_inspect_package_assets",
        lambda *_: (
            verification._PackageAsset(
                "modeling_core/__init__.py", "sha256:" + "f" * 64
            ),
        ),
    )

    def runner(
        spec: verification._CheckSpec,
        *,
        cwd: Path,
        environment: dict[str, str],
    ) -> verification._CheckResult:
        del cwd, environment
        if spec.check_id == "stdio-golden":
            return verification._CheckResult(
                spec.check_id,
                "FAIL",
                1,
                1,
                None,
                "nonzero-exit",
            )
        counts = (
            verification._TestCounts(1, 1, 0, 0, 0) if spec.kind == "pytest" else None
        )
        return verification._CheckResult(
            spec.check_id,
            "PASS",
            1,
            0,
            counts,
            None,
        )

    exit_code = verification._run_m1a_verification(
        repository,
        check_runner=runner,
    )

    assert exit_code == 1
    evidence_root = repository / "build/verification/m1a"
    final = evidence_root / fingerprint_hex
    assert sorted(path.name for path in final.iterdir()) == [
        "SUMMARY.md",
        "architecture-report.json",
        "golden-trace.json",
        "package-assets.json",
        "source-inventory.json",
        "stdio-transcript.json",
        "verification-report.json",
    ]
    report = json.loads((final / "verification-report.json").read_text("utf-8"))
    assert report["status"] == "FAILED"
    assert report["checks"][-1]["diagnostic_code"] == "nonzero-exit"
    assert not tuple(evidence_root.glob(".*.staging"))
    published_text = "\n".join(
        path.read_text(encoding="utf-8") for path in final.iterdir()
    )
    assert "SECRET_STDERR" not in published_text
    assert ".staging" not in published_text
    assert str(tmp_path) not in published_text


@pytest.mark.parametrize(
    "inspection_error",
    [
        ValueError("multiple wheels: SECRET_MULTIPLE"),
        zipfile.BadZipFile("malformed wheel: SECRET_MALFORMED"),
        ValueError("unsafe wheel member: SECRET_UNSAFE"),
        RuntimeError("encrypted wheel payload: SECRET_ENCRYPTED"),
        NotImplementedError("unsupported compression: SECRET_COMPRESSION"),
    ],
    ids=["multiple", "malformed", "unsafe", "encrypted", "compression"],
)
def test_wheel_inspection_failure_is_an_executed_redacted_failed_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    inspection_error: Exception,
) -> None:
    """Catches post-build inspection escaping as exit 2 with a staging leak."""
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "uv.lock").write_bytes(b"locked")
    uv = repository / "uv.exe"
    uv.write_bytes(b"pinned uv")
    fingerprint_hex = "4" * 64
    inventory = verification._SourceInventory((), "sha256:" + fingerprint_hex)
    monkeypatch.setattr(verification, "_validate_uv_executable", lambda _: uv)
    monkeypatch.setattr(verification, "_collect_source_inventory", lambda _: inventory)

    def reject_assets(*_: object) -> tuple[verification._PackageAsset, ...]:
        raise inspection_error

    monkeypatch.setattr(verification, "_inspect_package_assets", reject_assets)

    def runner(
        spec: verification._CheckSpec,
        *,
        cwd: Path,
        environment: dict[str, str],
    ) -> verification._CheckResult:
        assert cwd == repository
        if spec.check_id == "stdio-golden":
            staging = Path(environment["MODELING_M1A_GOLDEN_EVIDENCE_DIR"])
            (staging / "stdio-transcript.json").write_text(
                '{"events":[],"schema_version":"m1a-stdio-transcript/0.1.0"}\n',
                encoding="utf-8",
            )
            (staging / "golden-trace.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m1a-golden-trace/0.1.0",
                        "project_id": "00000000-0000-4000-8000-000000000001",
                        "experiment_id": "00000000-0000-4000-8000-000000000002",
                        "attempt_id": "00000000-0000-4000-8000-000000000003",
                        "validation_id": "00000000-0000-4000-8000-000000000004",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        counts = (
            verification._TestCounts(1, 1, 0, 0, 0) if spec.kind == "pytest" else None
        )
        return verification._CheckResult(spec.check_id, "PASS", 1, 0, counts, None)

    exit_code = verification._run_m1a_verification(repository, check_runner=runner)

    evidence_root = repository / "build/verification/m1a"
    final = evidence_root / fingerprint_hex
    assert exit_code == 1
    assert sorted(path.name for path in final.iterdir()) == [
        "SUMMARY.md",
        "architecture-report.json",
        "golden-trace.json",
        "package-assets.json",
        "source-inventory.json",
        "stdio-transcript.json",
        "verification-report.json",
    ]
    report = json.loads((final / "verification-report.json").read_text("utf-8"))
    wheel = next(check for check in report["checks"] if check["check_id"] == "wheel")
    assert report["status"] == "FAILED"
    assert wheel == {
        "check_id": "wheel",
        "status": "FAIL",
        "duration_ms": 1,
        "exit_code": 0,
        "test_counts": None,
        "diagnostic_code": "package-inspection-failed",
    }
    assert json.loads((final / "package-assets.json").read_text("utf-8")) == []
    assert not tuple(evidence_root.glob(".*.staging"))
    published = "\n".join(path.read_text("utf-8") for path in final.iterdir())
    assert "SECRET_" not in published


@pytest.mark.parametrize("existing", ["final", "staging"])
def test_verification_refuses_preexisting_final_or_staging_without_running_checks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: str,
) -> None:
    """Catches reuse, recovery, or overwrite of an existing evidence path."""
    repository = tmp_path / "repository"
    repository.mkdir()
    uv = repository / "uv.exe"
    uv.write_bytes(b"pinned")
    fingerprint_hex = "7" * 64
    inventory = verification._SourceInventory((), "sha256:" + fingerprint_hex)
    monkeypatch.setattr(verification, "_validate_uv_executable", lambda _: uv)
    monkeypatch.setattr(verification, "_collect_source_inventory", lambda _: inventory)
    evidence_root = repository / "build/verification/m1a"
    evidence_root.mkdir(parents=True)
    target = (
        evidence_root / fingerprint_hex
        if existing == "final"
        else evidence_root / f".{fingerprint_hex}.staging"
    )
    target.mkdir()
    marker = target / "owner.txt"
    marker.write_text("existing owner", encoding="utf-8")

    def unexpected_runner(*_: object, **__: object) -> verification._CheckResult:
        raise AssertionError("preexisting evidence must fail before checks")

    with pytest.raises(FileExistsError):
        verification._run_m1a_verification(
            repository,
            check_runner=unexpected_runner,
        )
    assert marker.read_text(encoding="utf-8") == "existing owner"


def test_end_of_run_source_drift_publishes_a_failed_original_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches publishing INCOMPLETE after source bytes drift during checks."""
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "uv.lock").write_bytes(b"locked")
    uv = repository / "uv.exe"
    uv.write_bytes(b"pinned")
    initial_hex = "5" * 64
    initial = verification._SourceInventory((), "sha256:" + initial_hex)
    drifted = verification._SourceInventory((), "sha256:" + "6" * 64)
    inventories = iter((initial, drifted, drifted))
    monkeypatch.setattr(verification, "_validate_uv_executable", lambda _: uv)
    monkeypatch.setattr(
        verification, "_collect_source_inventory", lambda _: next(inventories)
    )
    monkeypatch.setattr(verification, "_inspect_package_assets", lambda *_: ())

    def runner(
        spec: verification._CheckSpec,
        *,
        cwd: Path,
        environment: dict[str, str],
    ) -> verification._CheckResult:
        del cwd
        if spec.check_id == "stdio-golden":
            staging = Path(environment["MODELING_M1A_GOLDEN_EVIDENCE_DIR"])
            (staging / "stdio-transcript.json").write_text(
                '{"events":[],"schema_version":"m1a-stdio-transcript/0.1.0"}\n',
                encoding="utf-8",
            )
            (staging / "golden-trace.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m1a-golden-trace/0.1.0",
                        "project_id": "00000000-0000-4000-8000-000000000001",
                        "experiment_id": "00000000-0000-4000-8000-000000000002",
                        "attempt_id": "00000000-0000-4000-8000-000000000003",
                        "validation_id": "00000000-0000-4000-8000-000000000004",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        counts = (
            verification._TestCounts(1, 1, 0, 0, 0) if spec.kind == "pytest" else None
        )
        return verification._CheckResult(spec.check_id, "PASS", 1, 0, counts, None)

    exit_code = verification._run_m1a_verification(
        repository,
        check_runner=runner,
    )

    report_path = (
        repository / "build/verification/m1a" / initial_hex / "verification-report.json"
    )
    report = json.loads(report_path.read_text("utf-8"))
    assert exit_code == 1
    assert report["status"] == "FAILED"
    assert report["source_fingerprint"] == "sha256:" + initial_hex
    assert not tuple((repository / "build/verification/m1a").glob(".*.staging"))


def test_publish_seam_source_drift_cannot_publish_a_stale_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches source drift after report construction but before directory rename."""
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "uv.lock").write_bytes(b"locked")
    uv = repository / "uv.exe"
    uv.write_bytes(b"pinned")
    initial_hex = "2" * 64
    initial = verification._SourceInventory((), "sha256:" + initial_hex)
    drifted = verification._SourceInventory((), "sha256:" + "3" * 64)
    inventory_state = {"current": initial}
    monkeypatch.setattr(verification, "_validate_uv_executable", lambda _: uv)
    monkeypatch.setattr(
        verification,
        "_collect_source_inventory",
        lambda _: inventory_state["current"],
    )
    monkeypatch.setattr(verification, "_inspect_package_assets", lambda *_: ())

    def runner(
        spec: verification._CheckSpec,
        *,
        cwd: Path,
        environment: dict[str, str],
    ) -> verification._CheckResult:
        assert cwd == repository
        if spec.check_id == "stdio-golden":
            staging = Path(environment["MODELING_M1A_GOLDEN_EVIDENCE_DIR"])
            (staging / "stdio-transcript.json").write_text(
                '{"events":[],"schema_version":"m1a-stdio-transcript/0.1.0"}\n',
                encoding="utf-8",
            )
            (staging / "golden-trace.json").write_text(
                json.dumps(
                    {
                        "schema_version": "m1a-golden-trace/0.1.0",
                        "project_id": "00000000-0000-4000-8000-000000000001",
                        "experiment_id": "00000000-0000-4000-8000-000000000002",
                        "attempt_id": "00000000-0000-4000-8000-000000000003",
                        "validation_id": "00000000-0000-4000-8000-000000000004",
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        counts = (
            verification._TestCounts(1, 1, 0, 0, 0) if spec.kind == "pytest" else None
        )
        return verification._CheckResult(spec.check_id, "PASS", 1, 0, counts, None)

    real_publish = verification._atomic_publish_directory
    guard_calls = 0

    def mutate_at_publication(
        staging: Path,
        final: Path,
        *,
        before_publish: Callable[[], None] | None = None,
    ) -> None:
        nonlocal guard_calls
        inventory_state["current"] = drifted
        assert before_publish is not None
        guard_calls += 1
        real_publish(staging, final, before_publish=before_publish)

    monkeypatch.setattr(
        verification,
        "_atomic_publish_directory",
        mutate_at_publication,
    )

    exit_code = verification._run_m1a_verification(repository, check_runner=runner)

    evidence_root = repository / "build/verification/m1a"
    final = evidence_root / initial_hex
    report = json.loads((final / "verification-report.json").read_text("utf-8"))
    assert exit_code == 1
    assert guard_calls == 2
    assert report["status"] == "FAILED"
    assert report["source_fingerprint"] == initial.fingerprint
    assert json.loads((final / "source-inventory.json").read_text("utf-8")) == []
    assert sorted(path.name for path in final.iterdir()) == [
        "SUMMARY.md",
        "architecture-report.json",
        "golden-trace.json",
        "package-assets.json",
        "source-inventory.json",
        "stdio-transcript.json",
        "verification-report.json",
    ]
    assert not tuple(evidence_root.glob(".*.staging"))


def test_atomic_directory_publication_never_replaces_a_race_winner(
    tmp_path: Path,
) -> None:
    """Catches POSIX rename replacing an empty directory after a stale check."""
    staging = tmp_path / ".fingerprint.staging"
    staging.mkdir()
    (staging / "payload.json").write_text("staged", encoding="utf-8")
    final = tmp_path / "fingerprint"
    ready = threading.Event()
    publish = threading.Event()
    failures: list[BaseException] = []

    def publisher() -> None:
        ready.set()
        assert publish.wait(timeout=5)
        try:
            verification._atomic_publish_directory(staging, final)
        except BaseException as error:
            failures.append(error)

    thread = threading.Thread(target=publisher)
    thread.start()
    assert ready.wait(timeout=5)
    final.mkdir()
    publish.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert len(failures) == 1
    assert isinstance(failures[0], FileExistsError)
    assert not tuple(final.iterdir())
    assert (staging / "payload.json").read_text(encoding="utf-8") == "staged"
