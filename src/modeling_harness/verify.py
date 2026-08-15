"""Milestone verification command wiring."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import tomllib
from typing import Callable, Literal, cast
import unicodedata
import xml.etree.ElementTree as element_tree
import zipfile

from modeling_core import Milestone
from modeling_core.contracts.canonical_json import canonical_json_bytes, sha256_json


_UV_VERSION = "0.11.28"
_UV_VERSION_TIMEOUT_SECONDS = 10
_UV_VERSION_OUTPUT = re.compile(
    r"uv 0\.11\.28(?: \(ebf0f43d7 2026-07-07 "
    r"(?:x86_64|aarch64)-(?:pc-windows-msvc|unknown-linux-(?:gnu|musl)|apple-darwin)"
    r"\))?\r?\n?\Z"
)
_A12_INCOMPLETE_ITEMS = (
    "doctor-and-tests",
    "root-and-four-nested-agents",
    "context-product-architecture-contract-operations-docs",
    "codex-config-template",
    "acceptance-map-a01-through-a10",
    "readme-and-final-evidence-links",
)
_GOLDEN_NODE = (
    "tests/integration/test_stdio_golden_m1a.py::"
    "test_official_client_completes_m1a_golden_chain_records_protocol_purity_"
    "and_closes_child"
)
_NON_PYTHON_PACKAGE_ASSETS = frozenset(
    {
        "modeling_capabilities/AGENTS.md",
        "modeling_capabilities/root_finding/context.md",
        "modeling_capabilities/root_finding/schemas/0.1.0/canonical-input.schema.json",
        "modeling_capabilities/root_finding/schemas/0.1.0/failure-data.schema.json",
        "modeling_capabilities/root_finding/schemas/0.1.0/input.schema.json",
        "modeling_capabilities/root_finding/schemas/0.1.0/policy.schema.json",
        "modeling_capabilities/root_finding/schemas/0.1.0/report.schema.json",
        "modeling_capabilities/root_finding/schemas/0.1.0/success-data.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-capability.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-error.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-project.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-result.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-validation-report.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-validator.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/create_project.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/create_project.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/create_project.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/get_project_status.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/get_project_status.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/get_project_status.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/health_check.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/health_check.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/health_check.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/run_experiment.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/run_experiment.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/run_experiment.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.result.schema.json",
        "modeling_core/AGENTS.md",
        "modeling_cli/schemas/doctor/0.1.0/report.schema.json",
        "modeling_cli/templates/codex/config.toml",
        "modeling_infrastructure/sqlite/schema_v1.sql",
        "modeling_mcp/AGENTS.md",
    }
)
_PACKAGE_ROOT_PATHS = frozenset(
    {
        "src/modeling_cli",
        "src/modeling_capabilities",
        "src/modeling_core",
        "src/modeling_harness",
        "src/modeling_infrastructure",
        "src/modeling_bootstrap",
        "src/modeling_mcp",
    }
)


@dataclass(frozen=True, slots=True)
class _TestCounts:
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int


@dataclass(frozen=True, slots=True)
class _CheckSpec:
    check_id: str
    argv: tuple[str, ...]
    timeout_seconds: int
    kind: Literal["command", "pytest", "wheel"]


@dataclass(frozen=True, slots=True)
class _CheckResult:
    check_id: str
    status: Literal["PASS", "FAIL"]
    duration_ms: int
    exit_code: int | None
    test_counts: _TestCounts | None
    diagnostic_code: str | None


@dataclass(frozen=True, slots=True)
class _SourceEntry:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class _SourceInventory:
    entries: tuple[_SourceEntry, ...]
    fingerprint: str


class _SourceInventoryDriftError(RuntimeError):
    """Raised when verified source bytes drift at the publication seam."""


@dataclass(frozen=True, slots=True)
class _PackageAsset:
    path: str
    sha256: str


class _WindowsFileTime(ctypes.Structure):
    _fields_ = (("low", ctypes.c_uint32), ("high", ctypes.c_uint32))


class _WindowsFileInformation(ctypes.Structure):
    _fields_ = (
        ("attributes", ctypes.c_uint32),
        ("creation_time", _WindowsFileTime),
        ("access_time", _WindowsFileTime),
        ("write_time", _WindowsFileTime),
        ("volume_serial", ctypes.c_uint32),
        ("size_high", ctypes.c_uint32),
        ("size_low", ctypes.c_uint32),
        ("link_count", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    )


def _offline_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["UV_OFFLINE"] = "1"
    return environment


def _validate_uv_executable(repository_root: Path) -> Path:
    uv_value = os.environ.get("UV")
    if uv_value is None:
        raise ValueError("UV must name the pinned executable")
    executable = Path(uv_value)
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("UV must be an absolute existing regular file")

    completed = subprocess.run(
        [str(executable), "--version"],
        cwd=repository_root,
        env=_offline_environment(),
        timeout=_UV_VERSION_TIMEOUT_SECONDS,
        capture_output=True,
        text=True,
        check=False,
    )
    if (
        completed.returncode != 0
        or _UV_VERSION_OUTPUT.fullmatch(completed.stdout) is None
    ):
        raise ValueError("UV must be exactly uv 0.11.28")
    return executable


def _execute_check(
    spec: _CheckSpec,
    *,
    cwd: Path,
    environment: dict[str, str],
) -> _CheckResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(spec.argv),
            cwd=cwd,
            env=environment,
            timeout=spec.timeout_seconds,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _CheckResult(
            check_id=spec.check_id,
            status="FAIL",
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
            exit_code=None,
            test_counts=None,
            diagnostic_code="timeout",
        )

    test_counts: _TestCounts | None = None
    diagnostic_code: str | None = None
    if spec.kind == "pytest":
        junit_arguments = [
            argument for argument in spec.argv if argument.startswith("--junitxml=")
        ]
        if len(junit_arguments) != 1:
            diagnostic_code = "junit-missing"
        else:
            junit_path = Path(junit_arguments[0].partition("=")[2])
            try:
                root = element_tree.parse(junit_path).getroot()
                suites = (
                    [root] if root.tag == "testsuite" else root.findall("testsuite")
                )
                if root.tag not in {"testsuite", "testsuites"} or not suites:
                    raise ValueError("invalid JUnit root")
                total = sum(int(suite.attrib["tests"]) for suite in suites)
                failed = sum(int(suite.attrib.get("failures", "0")) for suite in suites)
                errors = sum(int(suite.attrib.get("errors", "0")) for suite in suites)
                skipped = sum(int(suite.attrib.get("skipped", "0")) for suite in suites)
                passed_count = total - failed - errors - skipped
                if min(total, passed_count, failed, errors, skipped) < 0:
                    raise ValueError("negative JUnit count")
                test_counts = _TestCounts(
                    total=total,
                    passed=passed_count,
                    failed=failed,
                    errors=errors,
                    skipped=skipped,
                )
            except (OSError, KeyError, ValueError, element_tree.ParseError):
                diagnostic_code = "junit-invalid"
            else:
                if skipped:
                    diagnostic_code = "required-skip"
                elif failed or errors:
                    diagnostic_code = "test-failure"
    if completed.returncode != 0:
        diagnostic_code = "nonzero-exit"
    passed = completed.returncode == 0 and diagnostic_code is None
    return _CheckResult(
        check_id=spec.check_id,
        status="PASS" if passed else "FAIL",
        duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        exit_code=completed.returncode,
        test_counts=test_counts,
        diagnostic_code=diagnostic_code,
    )


def _collect_source_inventory(repository_root: Path) -> _SourceInventory:
    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=repository_root,
        env=_offline_environment(),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not isinstance(completed.stdout, bytes):
        raise ValueError("source inventory unavailable")
    try:
        decoded = completed.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("source inventory paths must be UTF-8") from error
    if decoded and not decoded.endswith("\0"):
        raise ValueError("source inventory is not NUL-delimited")

    observed: dict[str, str] = {}
    entries: list[_SourceEntry] = []
    for raw_path in decoded.removesuffix("\0").split("\0") if decoded else []:
        normalized = unicodedata.normalize("NFC", raw_path)
        raw_parts = normalized.split("/")
        relative = PurePosixPath(normalized)
        if (
            not normalized
            or "\\" in normalized
            or PureWindowsPath(normalized).drive
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in raw_parts)
        ):
            raise ValueError("source inventory contains an unsafe path")
        previous = observed.get(normalized)
        if previous is not None:
            if previous != raw_path:
                raise ValueError("source inventory contains an NFC path collision")
            raise ValueError("source inventory contains a duplicate path")
        observed[normalized] = raw_path
        if not _is_regular_inventory_path(repository_root, relative):
            raise ValueError("source inventory contains a missing or non-file entry")
        entries.append(
            _SourceEntry(
                path=normalized,
                sha256=_hash_inventory_file(repository_root, relative),
            )
        )

    entries.sort(key=lambda entry: entry.path.encode("utf-8"))
    projection = [{"path": entry.path, "sha256": entry.sha256} for entry in entries]
    return _SourceInventory(
        entries=tuple(entries),
        fingerprint=sha256_json(projection),
    )


def _is_regular_inventory_path(repository_root: Path, relative: PurePosixPath) -> bool:
    candidate = repository_root
    metadata: os.stat_result | None = None
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    try:
        for part in relative.parts:
            candidate /= part
            metadata = os.lstat(candidate)
            if stat.S_ISLNK(metadata.st_mode) or (
                getattr(metadata, "st_file_attributes", 0) & reparse_flag
            ):
                return False
    except OSError:
        return False
    return metadata is not None and stat.S_ISREG(metadata.st_mode)


def _hash_inventory_file(repository_root: Path, relative: PurePosixPath) -> str:
    if os.name == "nt":
        return _hash_windows_inventory_file(repository_root, relative)
    return _hash_posix_inventory_file(repository_root, relative)


def _hash_posix_inventory_file(repository_root: Path, relative: PurePosixPath) -> str:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    if nofollow is None or directory is None:
        raise OSError(errno.ENOTSUP, "non-following inventory open is unavailable")
    opened: list[int] = []
    try:
        current = os.open(repository_root, os.O_RDONLY | directory | cloexec)
        opened.append(current)
        for part in relative.parts[:-1]:
            current = os.open(
                part,
                os.O_RDONLY | directory | nofollow | cloexec,
                dir_fd=current,
            )
            opened.append(current)
            if not stat.S_ISDIR(os.fstat(current).st_mode):
                raise ValueError("inventory parent is not a directory")
        file_descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | nofollow | cloexec,
            dir_fd=current,
        )
        opened.append(file_descriptor)
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise ValueError("inventory entry is not a regular file")
        digest = hashlib.sha256()
        while chunk := os.read(file_descriptor, 1024 * 1024):
            digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _hash_windows_inventory_file(repository_root: Path, relative: PurePosixPath) -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(_WindowsFileInformation),
    )
    get_information.restype = ctypes.c_int
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    )
    get_final_path.restype = ctypes.c_uint32
    read_file = kernel32.ReadFile
    read_file.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    )
    read_file.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int

    expected = repository_root.resolve(strict=True).joinpath(*relative.parts)
    handle = create_file(
        str(expected),
        0x80000000,
        0x00000001,
        None,
        3,
        0x00200000,
        None,
    )
    if handle in {None, ctypes.c_void_p(-1).value}:
        error_code = ctypes.get_last_error()
        raise OSError(error_code, "non-following inventory open failed", expected)
    try:
        information = _WindowsFileInformation()
        if not get_information(handle, ctypes.byref(information)):
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "inventory handle metadata failed", expected)
        if information.attributes & (0x00000010 | 0x00000400):
            raise ValueError("inventory entry is not a regular file")

        required = get_final_path(handle, None, 0, 0)
        if required == 0:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "inventory final path query failed", expected)
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = get_final_path(handle, buffer, len(buffer), 0)
        if written == 0 or written >= len(buffer):
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "inventory final path query failed", expected)
        observed = buffer.value
        if observed.startswith("\\\\?\\UNC\\"):
            observed = "\\\\" + observed[8:]
        elif observed.startswith("\\\\?\\"):
            observed = observed[4:]
        if os.path.normcase(os.path.abspath(observed)) != os.path.normcase(
            os.path.abspath(expected)
        ):
            raise ValueError("inventory handle resolved outside the listed path")

        digest = hashlib.sha256()
        read_buffer = ctypes.create_string_buffer(1024 * 1024)
        while True:
            count = ctypes.c_uint32()
            if not read_file(
                handle,
                read_buffer,
                len(read_buffer),
                ctypes.byref(count),
                None,
            ):
                error_code = ctypes.get_last_error()
                raise OSError(error_code, "inventory handle read failed", expected)
            if count.value == 0:
                break
            digest.update(read_buffer.raw[: count.value])
        return "sha256:" + digest.hexdigest()
    finally:
        close_handle(handle)


def _a12_incomplete_groups() -> list[dict[str, object]]:
    return [
        {
            "group_id": "a12-deliverables",
            "status": "INCOMPLETE",
            "items": list(_A12_INCOMPLETE_ITEMS),
        }
    ]


def _verification_outcome(
    checks: tuple[_CheckResult, ...] | list[_CheckResult],
    incomplete_groups: list[dict[str, object]],
) -> tuple[Literal["PASSED", "FAILED", "INCOMPLETE"], int]:
    if any(check.status == "FAIL" for check in checks):
        return "FAILED", 1
    if incomplete_groups:
        return "INCOMPLETE", 2
    return "PASSED", 0


def _inspect_package_assets(
    repository_root: Path, wheel_directory: Path
) -> tuple[_PackageAsset, ...]:
    wheels = tuple(wheel_directory.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("wheel build must produce exactly one wheel")
    configuration = tomllib.loads(
        (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    packages = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    if (
        not isinstance(packages, list)
        or len(packages) != 7
        or any(not isinstance(package, str) for package in packages)
        or frozenset(packages) != _PACKAGE_ROOT_PATHS
    ):
        raise ValueError("wheel must declare the seven M1a package roots")
    package_roots: list[tuple[Path, str]] = []
    for package in packages:
        if not isinstance(package, str):
            raise ValueError("wheel package roots must be strings")
        source_root = repository_root / package
        if source_root.parent != repository_root / "src" or not source_root.is_dir():
            raise ValueError("wheel package root is outside src")
        package_roots.append((source_root, source_root.name))

    expected: set[str] = set()
    for source_root, root_name in package_roots:
        for source_path in source_root.rglob("*"):
            if not source_path.is_file():
                continue
            relative_parts = source_path.relative_to(source_root).parts
            if "__pycache__" in relative_parts or source_path.suffix in {
                ".pyc",
                ".pyo",
            }:
                continue
            expected.add(PurePosixPath(root_name, *relative_parts).as_posix())
    non_python = {path for path in expected if not path.endswith(".py")}
    if non_python != _NON_PYTHON_PACKAGE_ASSETS:
        raise ValueError("non-Python package asset inventory changed")

    payloads: dict[str, bytes] = {}
    root_names = {root_name for _, root_name in package_roots}
    with zipfile.ZipFile(wheels[0]) as archive:
        for member in archive.infolist():
            member_name = unicodedata.normalize("NFC", member.filename)
            windows_member = PureWindowsPath(member_name)
            member_path = PurePosixPath(member_name)
            if (
                "\\" in member_name
                or windows_member.drive
                or windows_member.is_absolute()
                or member_path.is_absolute()
                or ".." in member_path.parts
            ):
                raise ValueError("wheel contains an unsafe member path")
            if "spikes" in member_path.parts:
                raise ValueError("wheel contains excluded spikes")
            if member.is_dir():
                continue
            if member_path.parts and member_path.parts[0] in root_names:
                normalized = member_path.as_posix()
                if normalized in payloads:
                    raise ValueError("wheel contains a duplicate package member")
                payloads[normalized] = archive.read(member)
    if set(payloads) != expected:
        raise ValueError("wheel package payload differs from source packages")
    return tuple(
        _PackageAsset(
            path=path,
            sha256="sha256:" + hashlib.sha256(payloads[path]).hexdigest(),
        )
        for path in sorted(payloads, key=lambda value: value.encode("utf-8"))
    )


def _build_check_specs(uv: Path, internal: Path) -> tuple[_CheckSpec, ...]:
    executable = str(uv)

    def pytest_spec(check_id: str, test_path: str, timeout: int = 180) -> _CheckSpec:
        return _CheckSpec(
            check_id=check_id,
            argv=(
                executable,
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                test_path,
                "-q",
                f"--junitxml={internal / f'{check_id}.xml'}",
            ),
            timeout_seconds=timeout,
            kind="pytest",
        )

    wheel_directory = internal / "wheel"
    return (
        _CheckSpec(
            "uv-lock", (executable, "lock", "--check", "--offline"), 30, "command"
        ),
        _CheckSpec(
            "ruff-check",
            (
                executable,
                "run",
                "--locked",
                "--no-sync",
                "ruff",
                "check",
                "src",
                "tests",
            ),
            60,
            "command",
        ),
        _CheckSpec(
            "ruff-format",
            (
                executable,
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
        _CheckSpec(
            "mypy",
            (executable, "run", "--locked", "--no-sync", "mypy", "src"),
            120,
            "command",
        ),
        pytest_spec("pytest-unit", "tests/unit"),
        pytest_spec("pytest-contract", "tests/contract"),
        pytest_spec("pytest-math", "tests/math"),
        pytest_spec("pytest-architecture", "tests/architecture"),
        pytest_spec("pytest-integration", "tests/integration"),
        pytest_spec("pytest-reproducibility", "tests/reproducibility"),
        pytest_spec("pytest-security", "tests/security"),
        _CheckSpec(
            "wheel",
            (
                executable,
                "build",
                "--wheel",
                "--offline",
                "--out-dir",
                str(wheel_directory),
            ),
            120,
            "wheel",
        ),
        pytest_spec("stdio-golden", _GOLDEN_NODE, 120),
    )


def _json_payload(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"  # type: ignore[arg-type]


def _atomic_replace(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _serialize_check(check: _CheckResult) -> dict[str, object]:
    counts = None
    if check.test_counts is not None:
        counts = {
            "total": check.test_counts.total,
            "passed": check.test_counts.passed,
            "failed": check.test_counts.failed,
            "errors": check.test_counts.errors,
            "skipped": check.test_counts.skipped,
        }
    return {
        "check_id": check.check_id,
        "status": check.status,
        "duration_ms": check.duration_ms,
        "exit_code": check.exit_code,
        "test_counts": counts,
        "diagnostic_code": check.diagnostic_code,
    }


def _environment_report(repository_root: Path, uv: Path) -> dict[str, object]:
    lock = repository_root / "uv.lock"
    if not lock.is_file():
        raise ValueError("uv.lock is missing")
    return {
        "python_version": platform.python_version(),
        "uv_version": _UV_VERSION,
        "uv_executable_sha256": "sha256:" + hashlib.sha256(uv.read_bytes()).hexdigest(),
        "os_family": platform.system(),
        "os_version": platform.version(),
        "architecture": _architecture_label(),
        "lock_sha256": "sha256:" + hashlib.sha256(lock.read_bytes()).hexdigest(),
    }


def _architecture_label() -> str:
    machine = platform.machine().strip()
    if machine:
        return machine
    platform_name = sysconfig.get_platform().strip()
    if not platform_name:
        raise ValueError("platform architecture is unavailable")
    return platform_name.rsplit("-", maxsplit=1)[-1].upper()


def _golden_ids(trace_path: Path) -> dict[str, str]:
    value = json.loads(trace_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("golden trace must be an object")
    if value.get("schema_version") == "m1a-golden-trace-failure/0.1.0":
        return {
            "project_id": "",
            "experiment_id": "",
            "attempt_id": "",
            "validation_id": "",
        }
    result: dict[str, str] = {}
    for key in ("project_id", "experiment_id", "attempt_id", "validation_id"):
        item = value.get(key)
        if not isinstance(item, str):
            raise ValueError("golden trace is missing an identifier")
        result[key] = item
    return result


def _replace_failed_golden_artifacts(staging: Path) -> None:
    transcript = staging / "stdio-transcript.json"
    trace = staging / "golden-trace.json"
    for path in (transcript, trace):
        if path.exists():
            if not path.is_file() or path.is_symlink():
                raise ValueError("failed golden artifact is unsafe")
            path.unlink()
    _atomic_replace(
        transcript,
        _json_payload(
            {
                "schema_version": "m1a-stdio-transcript-failure/0.1.0",
                "status": "UNAVAILABLE",
                "diagnostic_code": "golden-check-failed",
                "events": [],
            }
        ),
    )
    _atomic_replace(
        trace,
        _json_payload(
            {
                "schema_version": "m1a-golden-trace-failure/0.1.0",
                "status": "UNAVAILABLE",
                "diagnostic_code": "golden-check-failed",
            }
        ),
    )


def _summary(report: dict[str, object]) -> bytes:
    checks = cast(list[dict[str, object]], report["checks"])
    lines = [
        "# M1a verification",
        "",
        f"Status: {report['status']}",
        f"Source fingerprint: {report['source_fingerprint']}",
        f"Required skips: {report['required_skips']}",
        "",
        "Checks:",
    ]
    lines.extend(f"- {check['check_id']}: {check['status']}" for check in checks)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _run_m1a_verification(
    repository_root: Path,
    *,
    check_runner: Callable[..., _CheckResult] = _execute_check,
    incomplete_groups: list[dict[str, object]] | None = None,
) -> int:
    uv = _validate_uv_executable(repository_root)
    os.environ["UV_OFFLINE"] = "1"
    environment = _offline_environment()
    environment.pop("MODELING_M1A_GOLDEN_EVIDENCE_DIR", None)
    initial_inventory = _collect_source_inventory(repository_root)
    fingerprint_hex = initial_inventory.fingerprint.removeprefix("sha256:")
    if len(fingerprint_hex) != 64 or any(
        character not in "0123456789abcdef" for character in fingerprint_hex
    ):
        raise ValueError("source fingerprint is invalid")

    evidence_root = repository_root / "build" / "verification" / "m1a"
    evidence_root.mkdir(parents=True, exist_ok=True)
    final = evidence_root / fingerprint_hex
    staging = evidence_root / f".{fingerprint_hex}.staging"
    if final.exists():
        raise FileExistsError("verification evidence already exists")
    staging.mkdir(exist_ok=False)
    internal = staging / ".internal"
    internal.mkdir()
    (internal / "wheel").mkdir()

    specs = _build_check_specs(uv, internal)
    results: list[_CheckResult] = []
    for spec in specs:
        child_environment = dict(environment)
        if spec.check_id == "stdio-golden":
            child_environment["MODELING_M1A_GOLDEN_EVIDENCE_DIR"] = str(staging)
        results.append(
            check_runner(
                spec,
                cwd=repository_root,
                environment=child_environment,
            )
        )

    wheel_index = next(
        index for index, result in enumerate(results) if result.check_id == "wheel"
    )
    wheel_result = results[wheel_index]
    package_assets: tuple[_PackageAsset, ...] = ()
    if wheel_result.status == "PASS":
        try:
            package_assets = _inspect_package_assets(
                repository_root, internal / "wheel"
            )
        except (
            KeyError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            zipfile.BadZipFile,
        ):
            wheel_result = _CheckResult(
                check_id=wheel_result.check_id,
                status="FAIL",
                duration_ms=wheel_result.duration_ms,
                exit_code=wheel_result.exit_code,
                test_counts=wheel_result.test_counts,
                diagnostic_code="package-inspection-failed",
            )
            results[wheel_index] = wheel_result
    transcript_path = staging / "stdio-transcript.json"
    trace_path = staging / "golden-trace.json"
    golden_result = next(
        result for result in results if result.check_id == "stdio-golden"
    )
    if golden_result.status == "FAIL":
        _replace_failed_golden_artifacts(staging)
    elif not transcript_path.is_file() or not trace_path.is_file():
        raise ValueError("dedicated golden evidence is missing")

    architecture = next(
        result for result in results if result.check_id == "pytest-architecture"
    )
    source_document = [
        {"path": entry.path, "sha256": entry.sha256}
        for entry in initial_inventory.entries
    ]
    package_document = [
        {"path": asset.path, "sha256": asset.sha256} for asset in package_assets
    ]
    architecture_document = {
        "schema_version": "m1a-architecture-report/0.1.0",
        "status": architecture.status,
        "check_id": architecture.check_id,
        "test_counts": _serialize_check(architecture)["test_counts"],
    }
    _atomic_replace(staging / "source-inventory.json", _json_payload(source_document))
    _atomic_replace(staging / "package-assets.json", _json_payload(package_document))
    _atomic_replace(
        staging / "architecture-report.json", _json_payload(architecture_document)
    )

    groups = (
        _a12_incomplete_groups() if incomplete_groups is None else incomplete_groups
    )
    status, exit_code = _verification_outcome(results, groups)
    final_inventory = _collect_source_inventory(repository_root)
    if final_inventory != initial_inventory:
        status, exit_code = "FAILED", 1
    required_skips = sum(
        result.test_counts.skipped
        for result in results
        if result.test_counts is not None
    )
    report: dict[str, object] = {
        "schema_version": "m1a-verification-report/0.1.0",
        "milestone": "m1a",
        "status": status,
        "source_fingerprint": initial_inventory.fingerprint,
        "required_skips": required_skips,
        "environment": _environment_report(repository_root, uv),
        "checks": [_serialize_check(result) for result in results],
        "artifacts": {
            "source_inventory": "source-inventory.json",
            "package_assets": "package-assets.json",
            "architecture_report": "architecture-report.json",
            "stdio_transcript": "stdio-transcript.json",
            "golden_trace": "golden-trace.json",
        },
        "golden_ids": _golden_ids(trace_path),
        "incomplete_groups": groups,
    }
    shutil.rmtree(internal)
    _atomic_replace(staging / "verification-report.json", _json_payload(report))
    _atomic_replace(staging / "SUMMARY.md", _summary(report))

    def guard_source_at_publication() -> None:
        current_inventory = _collect_source_inventory(repository_root)
        if status != "FAILED" and current_inventory != initial_inventory:
            raise _SourceInventoryDriftError

    try:
        _atomic_publish_directory(
            staging,
            final,
            before_publish=guard_source_at_publication,
        )
    except _SourceInventoryDriftError:
        status, exit_code = "FAILED", 1
        report["status"] = status
        _atomic_replace(staging / "verification-report.json", _json_payload(report))
        _atomic_replace(staging / "SUMMARY.md", _summary(report))
        _atomic_publish_directory(
            staging,
            final,
            before_publish=guard_source_at_publication,
        )
    return exit_code


def _atomic_publish_directory(
    staging: Path,
    final: Path,
    *,
    before_publish: Callable[[], None] | None = None,
) -> None:
    """Atomically rename a directory while refusing an existing destination."""
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file = kernel32.MoveFileExW
        move_file.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
        move_file.restype = ctypes.c_int
        if before_publish is not None:
            before_publish()
        if move_file(str(staging), str(final), 0):
            return
        error_code = ctypes.get_last_error()
        if error_code in {80, 183}:
            raise FileExistsError(
                error_code, "verification evidence already exists", final
            )
        raise OSError(error_code, "atomic verification publication failed", final)

    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        try:
            renameat2 = libc.renameat2
        except AttributeError as error:
            raise OSError(errno.ENOSYS, "renameat2 is unavailable") from error
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        at_fdcwd = -100
        rename_noreplace = 1
        if before_publish is not None:
            before_publish()
        if (
            renameat2(
                at_fdcwd,
                os.fsencode(staging),
                at_fdcwd,
                os.fsencode(final),
                rename_noreplace,
            )
            == 0
        ):
            return
        error_code = ctypes.get_errno()
        if error_code == errno.EEXIST:
            raise FileExistsError(
                error_code, "verification evidence already exists", final
            )
        raise OSError(error_code, "atomic verification publication failed", final)

    raise OSError(errno.ENOTSUP, "atomic no-replace publication is unsupported")


def _publish_failure_diagnostic(repository_root: Path) -> None:
    failures = repository_root / "build" / "verification" / "m1a" / "failures"
    failures.mkdir(parents=True, exist_ok=True)
    diagnostic = Path(tempfile.mkdtemp(prefix="failure-", dir=failures))
    _atomic_replace(
        diagnostic / "diagnostic.json",
        _json_payload(
            {
                "schema_version": "m1a-verification-diagnostic/0.1.0",
                "milestone": "m1a",
                "diagnostic_code": "prerequisite-or-publication-failure",
            }
        ),
    )


def run_verification(milestone: Milestone) -> int:
    """Run the registered milestone verification profile."""
    print(milestone.value, flush=True)
    if milestone is not Milestone.M1A:
        print("verification milestone is not registered", file=sys.stderr)
        return 2
    repository_root = Path.cwd().resolve()
    try:
        return _run_m1a_verification(repository_root)
    except (OSError, ValueError, subprocess.SubprocessError):
        try:
            _publish_failure_diagnostic(repository_root)
        except OSError:
            pass
        print(
            "verification harness prerequisite or publication failed", file=sys.stderr
        )
        return 2


def _execute(arguments: argparse.Namespace) -> int:
    milestone = cast(Milestone, arguments.milestone)
    return run_verification(milestone)


def add_verify_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the verification subcommand."""
    parser = subparsers.add_parser("verify")
    parser.add_argument(
        "--milestone",
        type=Milestone,
        choices=tuple(Milestone),
        required=True,
    )
    parser.set_defaults(handler=_execute)
