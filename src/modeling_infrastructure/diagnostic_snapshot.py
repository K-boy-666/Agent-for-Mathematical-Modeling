"""Bounded, source-nonmutating diagnostic snapshots for SQLite projects."""

from __future__ import annotations

import ctypes
import errno
import hashlib
import os
import sqlite3
import stat
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterator, Literal, NoReturn, cast

from modeling_infrastructure.project_paths import ProjectPaths, is_reparse_point


SnapshotFailureCode = Literal[
    "snapshot_unstable",
    "snapshot_invalid",
    "snapshot_resource_limit",
    "snapshot_unavailable",
    "snapshot_cleanup_failed",
]
SourceStateHint = Literal["UNINITIALIZED", "INITIALIZED"]

_MESSAGES: dict[SnapshotFailureCode, str] = {
    "snapshot_unstable": "snapshot changed during capture",
    "snapshot_invalid": "snapshot input is invalid",
    "snapshot_resource_limit": "snapshot resource limit exceeded",
    "snapshot_unavailable": "snapshot is unavailable",
    "snapshot_cleanup_failed": "snapshot cleanup failed",
}
_REQUIRED_NAMES = frozenset({"project.json", "state.sqlite3", "project.lock"})
_OPTIONAL_NAMES = frozenset({"state.sqlite3-wal", "state.sqlite3-shm"})
_DIRECTORY_NAMES = frozenset({"artifacts", "staging"})
_ALLOWED_NAMES = _REQUIRED_NAMES | _OPTIONAL_NAMES | _DIRECTORY_NAMES
_PERSISTENT_NAMES = ("project.json", "state.sqlite3", "state.sqlite3-wal")
_SOURCE_PROJECT_JSON_LIMIT = 64 * 1024
_SOURCE_DATABASE_LIMIT = 64 * 1024 * 1024
_SOURCE_WAL_LIMIT = 64 * 1024 * 1024
_TOTAL_COPY_LIMIT = 128 * 1024 * 1024
_OWNED_MAIN_LIMIT = 134_217_728
_OWNED_PEAK_LIMIT = 536_936_512
_BACKUP_PAGES = 256
_BACKUP_CALLBACK_LIMIT = 1_025
_COPY_CHUNK_SIZE = 1024 * 1024
_DEADLINE_SECONDS = 10.0
_FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
_INPUT_NAMES = frozenset(
    {"project.json", "state.sqlite3", "state.sqlite3-wal", "state.sqlite3-shm"}
)
_OUTPUT_NAMES = _REQUIRED_NAMES
_OWNED_ROOT_NAMES = frozenset({".modeling.input", ".modeling.staging", ".modeling"})


class DiagnosticSnapshotError(RuntimeError):
    """Finite, redacted failure returned by diagnostic snapshot capture."""

    def __init__(self, code: SnapshotFailureCode) -> None:
        if code not in _MESSAGES:
            raise ValueError("unknown diagnostic snapshot failure code")
        self._code = code
        super().__init__(_MESSAGES[code])

    @property
    def code(self) -> SnapshotFailureCode:
        return self._code


@dataclass(frozen=True)
class DiagnosticSnapshot:
    """Owned project root materialized for diagnostic-only composition."""

    project_root: Path
    source_state_hint: SourceStateHint


@dataclass(frozen=True)
class _StableFile:
    identity: tuple[int, int]
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class _OwnedFileBinding:
    identity: tuple[int, int]
    size: int
    mtime_ns: int
    sha256: str


@dataclass(frozen=True)
class _LockMetadata:
    identity: tuple[int, int]
    size: int
    mtime_ns: int


@dataclass(frozen=True)
class _Manifest:
    directory_identity: tuple[int, int]
    names: tuple[str, ...]
    persistent: tuple[tuple[str, _StableFile], ...]
    lock: _LockMetadata
    shm_identity: tuple[int, int] | None
    directories: tuple[tuple[str, tuple[int, int]], ...]

    def member(self, name: str) -> _StableFile:
        for member_name, details in self.persistent:
            if member_name == name:
                return details
        raise KeyError(name)


def _raise(code: SnapshotFailureCode, cause: BaseException | None = None) -> NoReturn:
    error = DiagnosticSnapshotError(code)
    if cause is None:
        raise error
    raise error from cause


def _test_seam(phase: str, **context: object) -> None:
    """Deterministic test-only observation seam; never mutates by default."""
    del phase, context


def _check_deadline(started_at: float) -> None:
    if time.monotonic() - started_at >= _DEADLINE_SECONDS:
        _raise("snapshot_resource_limit")


def _bounded_entries(
    directory: Path,
    allowed_names: frozenset[str],
    *,
    started_at: float | None = None,
) -> tuple[Path, ...]:
    entries: list[Path] = []
    try:
        for entry in directory.iterdir():
            if started_at is not None:
                _check_deadline(started_at)
            entries.append(entry)
            if len(entries) > len(allowed_names) or entry.name not in allowed_names:
                _raise("snapshot_invalid")
    except DiagnosticSnapshotError:
        raise
    except OSError as error:
        _raise(_os_failure_code(error), error)
    return tuple(sorted(entries, key=lambda item: item.name.encode("utf-8")))


def _identity(details: os.stat_result) -> tuple[int, int]:
    return details.st_dev, details.st_ino


def _is_reparse(details: os.stat_result) -> bool:
    attributes = getattr(details, "st_file_attributes", 0)
    return stat.S_ISLNK(details.st_mode) or bool(
        attributes & _FILE_ATTRIBUTE_REPARSE_POINT
    )


def _regular_lstat(path: Path, *, changed: bool = False) -> os.stat_result:
    try:
        details = path.lstat()
    except FileNotFoundError as error:
        _raise("snapshot_unstable" if changed else "snapshot_invalid", error)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    if _is_reparse(details) or not stat.S_ISREG(details.st_mode):
        _raise("snapshot_invalid")
    return details


def _directory_lstat(path: Path, *, changed: bool = False) -> os.stat_result:
    try:
        details = path.lstat()
    except FileNotFoundError as error:
        _raise("snapshot_unstable" if changed else "snapshot_invalid", error)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    if _is_reparse(details) or not stat.S_ISDIR(details.st_mode):
        _raise("snapshot_invalid")
    return details


def _os_failure_code(error: OSError) -> SnapshotFailureCode:
    if error.errno in {errno.ENOSPC, getattr(errno, "EDQUOT", -1)}:
        return "snapshot_resource_limit"
    return "snapshot_unavailable"


def _sqlite_failure_code(error: sqlite3.DatabaseError) -> SnapshotFailureCode:
    raw_code = getattr(error, "sqlite_errorcode", None)
    if type(raw_code) is not int:
        return "snapshot_invalid"
    primary_code = raw_code & 0xFF
    if primary_code in {sqlite3.SQLITE_FULL, sqlite3.SQLITE_NOMEM}:
        return "snapshot_resource_limit"
    unavailable = {
        sqlite3.SQLITE_BUSY,
        sqlite3.SQLITE_CANTOPEN,
        sqlite3.SQLITE_IOERR,
        sqlite3.SQLITE_LOCKED,
        sqlite3.SQLITE_PERM,
    }
    if primary_code in unavailable:
        return "snapshot_unavailable"
    return "snapshot_invalid"


def _windows_descriptor(
    path: Path,
    *,
    directory: bool,
    share_delete: bool,
    share_write: bool = True,
    desired_access: int = 0x80000000,
) -> int:
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        desired_access,
        0x00000001
        | (0x00000002 if share_write else 0)
        | (0x00000004 if share_delete else 0),
        None,
        3,
        0x00200000 | 0x08000000 | (0x02000000 if directory else 0),
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle == invalid_handle:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return msvcrt.open_osfhandle(
            cast(int, handle), os.O_RDONLY | getattr(os, "O_BINARY", 0)
        )
    except BaseException:
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = (wintypes.HANDLE,)
        close_handle.restype = wintypes.BOOL
        close_handle(handle)
        raise


def _windows_read_descriptor(path: Path) -> int:
    return _windows_descriptor(path, directory=False, share_delete=True)


def _windows_guarded_file_descriptor(path: Path) -> int:
    return _windows_descriptor(
        path,
        directory=False,
        share_delete=False,
        share_write=False,
    )


def _windows_guarded_delete_file_descriptor(path: Path) -> int:
    return _windows_descriptor(
        path,
        directory=False,
        share_delete=False,
        share_write=False,
        desired_access=0x80000000 | 0x00010000,
    )


def _windows_directory_descriptor(path: Path) -> int:
    return _windows_descriptor(path, directory=True, share_delete=False)


def _windows_delete_directory_descriptor(path: Path) -> int:
    return _windows_descriptor(
        path,
        directory=True,
        share_delete=False,
        desired_access=0x80000000 | 0x00010000,
    )


def _windows_mark_delete_on_close(descriptor: int) -> None:
    import msvcrt
    from ctypes import wintypes

    class _FileDispositionInfo(ctypes.Structure):
        _fields_ = [("delete_file", wintypes.BOOL)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_file_information = kernel32.SetFileInformationByHandle
    set_file_information.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.LPVOID,
        wintypes.DWORD,
    )
    set_file_information.restype = wintypes.BOOL
    information = _FileDispositionInfo(True)
    handle = msvcrt.get_osfhandle(descriptor)
    if not set_file_information(
        handle,
        4,
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise ctypes.WinError(ctypes.get_last_error())


@contextmanager
def _open_source_handle(path: Path) -> Iterator[BinaryIO]:
    descriptor: int | None = None
    stream: BinaryIO | None = None
    try:
        if os.name == "nt":
            descriptor = _windows_read_descriptor(path)
        else:
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            no_follow = getattr(os, "O_NOFOLLOW", None)
            if no_follow is None:
                _raise("snapshot_unavailable")
            descriptor = os.open(path, flags | no_follow)
        stream = cast(BinaryIO, os.fdopen(descriptor, "rb", buffering=0))
        descriptor = None
        yield stream
    finally:
        if stream is not None:
            stream.close()
        elif descriptor is not None:
            os.close(descriptor)


@dataclass
class _DirectoryGuard:
    path: Path
    descriptor: int
    expected_identity: tuple[int, int]

    def validate_path(self) -> None:
        try:
            details = self.path.lstat()
            opened = os.fstat(self.descriptor)
        except FileNotFoundError as error:
            _raise("snapshot_unstable", error)
        except OSError as error:
            _raise(_os_failure_code(error), error)
        if _is_reparse(details) or not stat.S_ISDIR(details.st_mode):
            _raise("snapshot_invalid")
        if (
            _identity(details) != self.expected_identity
            or _identity(opened) != self.expected_identity
            or not stat.S_ISDIR(opened.st_mode)
        ):
            _raise("snapshot_unstable")

    def list_names(self, *, changed: bool, started_at: float) -> tuple[str, ...]:
        self.validate_path()
        entries: list[str] = []
        try:
            target: Path | int = self.path if os.name == "nt" else self.descriptor
            _check_deadline(started_at)
            with os.scandir(target) as iterator:
                while True:
                    _check_deadline(started_at)
                    try:
                        entry = next(iterator)
                    except StopIteration:
                        break
                    _check_deadline(started_at)
                    entries.append(entry.name)
                    if (
                        len(entries) > len(_ALLOWED_NAMES)
                        or entry.name not in _ALLOWED_NAMES
                    ):
                        _raise("snapshot_unstable" if changed else "snapshot_invalid")
                    _check_deadline(started_at)
            _check_deadline(started_at)
        except FileNotFoundError as error:
            _raise("snapshot_unstable", error)
        except DiagnosticSnapshotError:
            raise
        except OSError as error:
            _raise(_os_failure_code(error), error)
        self.validate_path()
        return tuple(sorted(entries, key=lambda item: item.encode("utf-8")))

    def stat_member(self, name: str, *, changed: bool) -> os.stat_result:
        self.validate_path()
        try:
            details = (
                (self.path / name).lstat()
                if os.name == "nt"
                else os.stat(
                    name,
                    dir_fd=self.descriptor,
                    follow_symlinks=False,
                )
            )
        except FileNotFoundError as error:
            _raise("snapshot_unstable" if changed else "snapshot_invalid", error)
        except OSError as error:
            _raise(_os_failure_code(error), error)
        self.validate_path()
        return details

    @contextmanager
    def open_member(self, name: str) -> Iterator[BinaryIO]:
        self.validate_path()
        if os.name == "nt":
            with _open_source_handle(self.path / name) as source_stream:
                self.validate_path()
                yield source_stream
                self.validate_path()
            return
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            _raise("snapshot_unavailable")
        descriptor: int | None = None
        stream: BinaryIO | None = None
        try:
            descriptor = os.open(
                name,
                flags | no_follow,
                dir_fd=self.descriptor,
            )
            stream = cast(BinaryIO, os.fdopen(descriptor, "rb", buffering=0))
            descriptor = None
            self.validate_path()
            yield stream
            self.validate_path()
        finally:
            if stream is not None:
                stream.close()
            elif descriptor is not None:
                os.close(descriptor)


@contextmanager
def _guard_directory(
    path: Path,
    expected_identity: tuple[int, int],
    *,
    parent: _DirectoryGuard | None = None,
    member_name: str | None = None,
) -> Iterator[_DirectoryGuard]:
    descriptor: int | None = None
    try:
        if os.name == "nt":
            descriptor = _windows_directory_descriptor(path)
        else:
            flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
            )
            no_follow = getattr(os, "O_NOFOLLOW", None)
            if no_follow is None:
                _raise("snapshot_unavailable")
            if parent is None:
                descriptor = os.open(path, flags | no_follow)
            else:
                if member_name is None:
                    raise AssertionError("relative directory guard requires a member")
                parent.validate_path()
                descriptor = os.open(
                    member_name,
                    flags | no_follow,
                    dir_fd=parent.descriptor,
                )
                parent.validate_path()
        opened = os.fstat(descriptor)
        if (
            _is_reparse(opened)
            or not stat.S_ISDIR(opened.st_mode)
            or _identity(opened) != expected_identity
        ):
            _raise("snapshot_unstable")
        guard = _DirectoryGuard(path, descriptor, expected_identity)
        guard.validate_path()
        yield guard
        guard.validate_path()
    except DiagnosticSnapshotError:
        raise
    except FileNotFoundError as error:
        _raise("snapshot_unstable", error)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _file_limit(name: str) -> int:
    if name == "project.json":
        return _SOURCE_PROJECT_JSON_LIMIT
    if name == "state.sqlite3":
        return _SOURCE_DATABASE_LIMIT
    if name == "state.sqlite3-wal":
        return _SOURCE_WAL_LIMIT
    raise AssertionError("unexpected persistent member")


def _hash_source_file(
    guard: _DirectoryGuard,
    name: str,
    details: os.stat_result,
    *,
    started_at: float,
) -> str:
    limit = _file_limit(name)
    if details.st_size > limit:
        _raise("snapshot_resource_limit")
    digest = hashlib.sha256()
    observed = 0
    try:
        with guard.open_member(name) as stream:
            opened = os.fstat(stream.fileno())
            if (
                _is_reparse(opened)
                or not stat.S_ISREG(opened.st_mode)
                or _identity(opened) != _identity(details)
            ):
                _raise("snapshot_unstable")
            while True:
                _check_deadline(started_at)
                chunk = stream.read(_COPY_CHUNK_SIZE)
                _check_deadline(started_at)
                if not chunk:
                    break
                observed += len(chunk)
                if observed > limit:
                    _raise("snapshot_resource_limit")
                digest.update(chunk)
            final = os.fstat(stream.fileno())
            if (
                _identity(final) != _identity(details)
                or final.st_size != details.st_size
                or final.st_mtime_ns != details.st_mtime_ns
                or observed != details.st_size
            ):
                _raise("snapshot_unstable")
    except DiagnosticSnapshotError:
        raise
    except FileNotFoundError as error:
        _raise("snapshot_unstable", error)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    return digest.hexdigest()


def _enumerate_source(
    modeling: Path,
    *,
    changed: bool,
    guard: _DirectoryGuard,
    started_at: float,
) -> tuple[os.stat_result, tuple[str, ...]]:
    del modeling
    guard.validate_path()
    directory = os.fstat(guard.descriptor)
    names = guard.list_names(changed=changed, started_at=started_at)
    name_set = frozenset(names)
    if changed and (not _REQUIRED_NAMES <= name_set or not name_set <= _ALLOWED_NAMES):
        _raise("snapshot_unstable")
    if not changed and (
        not _REQUIRED_NAMES <= name_set or not name_set <= _ALLOWED_NAMES
    ):
        _raise("snapshot_invalid")
    return directory, names


def _capture_manifest(
    modeling: Path,
    *,
    guard: _DirectoryGuard,
    started_at: float,
    changed: bool,
) -> _Manifest:
    _check_deadline(started_at)
    directory, names = _enumerate_source(
        modeling,
        changed=changed,
        guard=guard,
        started_at=started_at,
    )
    records: list[tuple[str, _StableFile]] = []
    for name in _PERSISTENT_NAMES:
        if name not in names:
            continue
        details = guard.stat_member(name, changed=changed)
        if _is_reparse(details) or not stat.S_ISREG(details.st_mode):
            _raise("snapshot_invalid")
        digest = _hash_source_file(
            guard,
            name,
            details,
            started_at=started_at,
        )
        records.append(
            (
                name,
                _StableFile(
                    identity=_identity(details),
                    size=details.st_size,
                    mtime_ns=details.st_mtime_ns,
                    sha256=digest,
                ),
            )
        )
    lock_details = guard.stat_member("project.lock", changed=changed)
    if _is_reparse(lock_details) or not stat.S_ISREG(lock_details.st_mode):
        _raise("snapshot_invalid")
    if not 1 <= lock_details.st_size <= 64:
        _raise("snapshot_unstable" if changed else "snapshot_invalid")
    shm_identity: tuple[int, int] | None = None
    if "state.sqlite3-shm" in names:
        shm_details = guard.stat_member("state.sqlite3-shm", changed=changed)
        if _is_reparse(shm_details) or not stat.S_ISREG(shm_details.st_mode):
            _raise("snapshot_invalid")
        shm_identity = _identity(shm_details)
    directories: list[tuple[str, tuple[int, int]]] = []
    for name in sorted(_DIRECTORY_NAMES, key=lambda item: item.encode("utf-8")):
        if name not in names:
            continue
        details = guard.stat_member(name, changed=changed)
        if _is_reparse(details) or not stat.S_ISDIR(details.st_mode):
            _raise("snapshot_invalid")
        directories.append((name, _identity(details)))
    _check_deadline(started_at)
    return _Manifest(
        directory_identity=_identity(directory),
        names=names,
        persistent=tuple(records),
        lock=_LockMetadata(
            identity=_identity(lock_details),
            size=lock_details.st_size,
            mtime_ns=lock_details.st_mtime_ns,
        ),
        shm_identity=shm_identity,
        directories=tuple(directories),
    )


def _hash_owned_file(path: Path, *, started_at: float) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as stream:
            while True:
                _check_deadline(started_at)
                chunk = stream.read(_COPY_CHUNK_SIZE)
                _check_deadline(started_at)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
    except DiagnosticSnapshotError:
        raise
    except FileNotFoundError as error:
        _raise("snapshot_unstable", error)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    return size, digest.hexdigest()


def _copy_persistent_member(
    source_guard: _DirectoryGuard,
    name: str,
    destination: Path,
    expected: _StableFile,
    *,
    started_at: float,
) -> tuple[int, str]:
    copied = 0
    digest = hashlib.sha256()
    try:
        source_details = source_guard.stat_member(name, changed=True)
        if _is_reparse(source_details) or not stat.S_ISREG(source_details.st_mode):
            _raise("snapshot_invalid")
        if (
            _identity(source_details) != expected.identity
            or source_details.st_size != expected.size
            or source_details.st_mtime_ns != expected.mtime_ns
        ):
            _raise("snapshot_unstable")
        with (
            source_guard.open_member(name) as input_stream,
            destination.open("xb") as output_stream,
        ):
            opened = os.fstat(input_stream.fileno())
            if _identity(opened) != expected.identity:
                _raise("snapshot_unstable")
            chunk_index = 0
            while True:
                _check_deadline(started_at)
                chunk = input_stream.read(_COPY_CHUNK_SIZE)
                _check_deadline(started_at)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > _file_limit(name):
                    _raise("snapshot_resource_limit")
                output_stream.write(chunk)
                digest.update(chunk)
                _test_seam(
                    "during_copy",
                    member=name,
                    chunk_index=chunk_index,
                )
                chunk_index += 1
            output_stream.flush()
            os.fsync(output_stream.fileno())
            final = os.fstat(input_stream.fileno())
            if (
                _identity(final) != expected.identity
                or final.st_size != expected.size
                or final.st_mtime_ns != expected.mtime_ns
            ):
                _raise("snapshot_unstable")
    except DiagnosticSnapshotError:
        raise
    except FileNotFoundError as error:
        _raise("snapshot_unstable", error)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    actual_size, actual_hash = _hash_owned_file(destination, started_at=started_at)
    if (
        copied != expected.size
        or actual_size != expected.size
        or digest.hexdigest() != expected.sha256
        or actual_hash != expected.sha256
    ):
        _raise("snapshot_unstable")
    return actual_size, actual_hash


def _verify_copied_members(
    modeling: Path,
    manifest: _Manifest,
    *,
    started_at: float,
) -> None:
    for name, expected in manifest.persistent:
        path = modeling / name
        details = _regular_lstat(path, changed=True)
        size, digest = _hash_owned_file(path, started_at=started_at)
        if (
            details.st_size != expected.size
            or size != expected.size
            or digest != expected.sha256
        ):
            _raise("snapshot_unstable")


def _copy_owned_project_json(
    source: Path,
    destination: Path,
    expected: _OwnedFileBinding,
    *,
    started_at: float,
) -> _OwnedFileBinding:
    _require_owned_file_binding(source, expected, started_at=started_at)
    copied = 0
    digest = hashlib.sha256()
    try:
        with source.open("rb") as input_stream, destination.open("xb") as output_stream:
            while True:
                _check_deadline(started_at)
                chunk = input_stream.read(_COPY_CHUNK_SIZE)
                _check_deadline(started_at)
                if not chunk:
                    break
                copied += len(chunk)
                if copied > _SOURCE_PROJECT_JSON_LIMIT:
                    _raise("snapshot_resource_limit")
                output_stream.write(chunk)
                digest.update(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
    except DiagnosticSnapshotError:
        raise
    except OSError as error:
        _raise(_os_failure_code(error), error)
    _require_owned_file_binding(source, expected, started_at=started_at)
    details = _regular_lstat(destination, changed=True)
    binding = _capture_owned_file_binding(
        destination,
        expected_identity=_identity(details),
        started_at=started_at,
    )
    if (
        copied != expected.size
        or binding.size != expected.size
        or digest.hexdigest() != expected.sha256
        or binding.sha256 != expected.sha256
    ):
        _raise("snapshot_unstable")
    return binding


def _owned_tree_size(
    root: Path,
    *,
    started_at: float,
    extra_bytes: int = 0,
) -> int:
    total = 0

    def add_directory(directory: Path, *, input_root: bool) -> None:
        nonlocal total
        allowed = _INPUT_NAMES if input_root else _OUTPUT_NAMES
        entries = _bounded_entries(
            directory,
            allowed,
            started_at=started_at,
        )
        for path in entries:
            _check_deadline(started_at)
            details = path.lstat()
            if _is_reparse(details) or not stat.S_ISREG(details.st_mode):
                _raise("snapshot_invalid")
            if input_root:
                if path.name == "state.sqlite3-shm" and details.st_size != 0:
                    _raise("snapshot_unstable")
                if (
                    path.name == "state.sqlite3"
                    and details.st_size > _SOURCE_DATABASE_LIMIT
                ):
                    _raise("snapshot_resource_limit")
                if (
                    path.name == "state.sqlite3-wal"
                    and details.st_size > _SOURCE_WAL_LIMIT
                ):
                    _raise("snapshot_resource_limit")
            else:
                limits = {
                    "project.json": _SOURCE_PROJECT_JSON_LIMIT,
                    "project.lock": 64,
                    "state.sqlite3": _OWNED_MAIN_LIMIT,
                }
                if details.st_size > limits[path.name]:
                    _raise("snapshot_resource_limit")
            total += details.st_size
            if total + extra_bytes > _OWNED_PEAK_LIMIT:
                _raise("snapshot_resource_limit")

    try:
        _check_deadline(started_at)
        if root.name.startswith("modeling-diagnostic-"):
            children = _bounded_entries(
                root,
                _OWNED_ROOT_NAMES,
                started_at=started_at,
            )
            for child in children:
                details = child.lstat()
                if _is_reparse(details) or not stat.S_ISDIR(details.st_mode):
                    _raise("snapshot_invalid")
                add_directory(child, input_root=child.name == ".modeling.input")
        else:
            add_directory(root, input_root=root.name == ".modeling.input")
    except DiagnosticSnapshotError:
        raise
    except OSError as error:
        _raise(_os_failure_code(error), error)
    if total + extra_bytes > _OWNED_PEAK_LIMIT:
        _raise("snapshot_resource_limit")
    return total


def _execute_rows(
    connection: sqlite3.Connection,
    statement: str,
    *,
    started_at: float,
) -> list[tuple[object, ...]]:
    _check_deadline(started_at)
    try:
        rows = connection.execute(statement).fetchall()
    except BaseException:
        _check_deadline(started_at)
        raise
    _check_deadline(started_at)
    return rows


def _single_integer(
    connection: sqlite3.Connection,
    statement: str,
    *,
    started_at: float,
) -> int:
    rows = _execute_rows(connection, statement, started_at=started_at)
    if len(rows) != 1 or len(rows[0]) != 1 or type(rows[0][0]) is not int:
        _raise("snapshot_invalid")
    return rows[0][0]


@dataclass
class _BackupProgress:
    started_at: float
    check_bounds: Callable[[], object]
    max_pages: int = _OWNED_MAIN_LIMIT // 512
    callbacks: int = 0
    total: int | None = None
    remaining: int | None = None
    done: bool = False

    def __call__(self, status: int, remaining: int, total: int) -> None:
        _check_deadline(self.started_at)
        self.callbacks += 1
        if self.callbacks > _BACKUP_CALLBACK_LIMIT:
            _raise("snapshot_resource_limit")
        if any(type(value) is not int for value in (status, remaining, total)):
            _raise("snapshot_invalid")
        if self.done:
            _raise("snapshot_invalid")
        primary = status & 0xFF
        if primary in {
            sqlite3.SQLITE_BUSY,
            sqlite3.SQLITE_LOCKED,
            sqlite3.SQLITE_CANTOPEN,
            sqlite3.SQLITE_IOERR,
            sqlite3.SQLITE_PERM,
        }:
            _raise("snapshot_unavailable")
        if primary in {sqlite3.SQLITE_FULL, sqlite3.SQLITE_NOMEM}:
            _raise("snapshot_resource_limit")
        if primary not in {sqlite3.SQLITE_OK, sqlite3.SQLITE_DONE}:
            _raise("snapshot_invalid")
        if total < 0 or remaining < 0 or remaining > total:
            _raise("snapshot_invalid")
        if self.total is None:
            self.total = total
        elif total != self.total:
            _raise("snapshot_invalid")
        if self.remaining is not None and remaining > self.remaining:
            _raise("snapshot_invalid")
        self.remaining = remaining
        if total > self.max_pages:
            _raise("snapshot_resource_limit")
        if primary == sqlite3.SQLITE_DONE:
            if remaining != 0:
                _raise("snapshot_invalid")
            self.done = True
        self.check_bounds()
        _check_deadline(self.started_at)

    def require_complete(self) -> None:
        _check_deadline(self.started_at)
        if not self.done:
            _raise("snapshot_invalid")


def _require_absent(path: Path) -> None:
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        _raise(_os_failure_code(error), error)
    _raise("snapshot_invalid")


def _validate_raw_database(modeling: Path) -> int:
    database = modeling / "state.sqlite3"
    try:
        with database.open("rb") as stream:
            header = stream.read(18)
            if header[:16] != b"SQLite format 3\0" or len(header) != 18:
                _raise("snapshot_invalid")
            encoded_page_size = int.from_bytes(header[16:18], "big")
            page_size = 65_536 if encoded_page_size == 1 else encoded_page_size
            if page_size < 512 or page_size > 65_536 or page_size & (page_size - 1):
                _raise("snapshot_invalid")
        wal = modeling / "state.sqlite3-wal"
        if wal.exists() and wal.stat().st_size:
            with wal.open("rb") as stream:
                header = stream.read(4)
            if header not in {b"7\x7f\x06\x82", b"7\x7f\x06\x83"}:
                _raise("snapshot_invalid")
    except DiagnosticSnapshotError:
        raise
    except OSError as error:
        _raise(_os_failure_code(error), error)
    return page_size


def _validate_owned_database_identity(
    path: Path,
    expected_identity: tuple[int, int],
) -> os.stat_result:
    try:
        details = path.lstat()
    except FileNotFoundError as error:
        _raise("snapshot_invalid", error)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    if (
        _is_reparse(details)
        or not stat.S_ISREG(details.st_mode)
        or _identity(details) != expected_identity
        or details.st_nlink != 1
    ):
        _raise("snapshot_invalid")
    return details


def _capture_owned_file_binding(
    path: Path,
    *,
    expected_identity: tuple[int, int],
    started_at: float,
    changed: bool = False,
) -> _OwnedFileBinding:
    descriptor: int | None = None
    try:
        try:
            before = _validate_owned_database_identity(path, expected_identity)
        except DiagnosticSnapshotError as error:
            if changed and error.code == "snapshot_invalid":
                _raise("snapshot_unstable", error)
            raise
        descriptor = _windows_guarded_file_descriptor(path)
        opened = os.fstat(descriptor)
        if (
            _is_reparse(opened)
            or not stat.S_ISREG(opened.st_mode)
            or _identity(opened) != expected_identity
            or opened.st_nlink != 1
        ):
            _raise("snapshot_unstable" if changed else "snapshot_invalid")
        digest = hashlib.sha256()
        observed = 0
        os.lseek(descriptor, 0, os.SEEK_SET)
        while True:
            _check_deadline(started_at)
            chunk = os.read(descriptor, _COPY_CHUNK_SIZE)
            _check_deadline(started_at)
            if not chunk:
                break
            observed += len(chunk)
            digest.update(chunk)
        try:
            after = _validate_owned_database_identity(path, expected_identity)
        except DiagnosticSnapshotError as error:
            if changed and error.code == "snapshot_invalid":
                _raise("snapshot_unstable", error)
            raise
        final = os.fstat(descriptor)
        if (
            _identity(final) != expected_identity
            or final.st_nlink != 1
            or before.st_size != opened.st_size
            or opened.st_size != final.st_size
            or final.st_size != after.st_size
            or before.st_mtime_ns != opened.st_mtime_ns
            or opened.st_mtime_ns != final.st_mtime_ns
            or final.st_mtime_ns != after.st_mtime_ns
            or observed != final.st_size
        ):
            _raise("snapshot_unstable")
        return _OwnedFileBinding(
            identity=expected_identity,
            size=final.st_size,
            mtime_ns=final.st_mtime_ns,
            sha256=digest.hexdigest(),
        )
    except DiagnosticSnapshotError:
        raise
    except FileNotFoundError as error:
        _raise("snapshot_unstable", error)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _require_owned_file_binding(
    path: Path,
    expected: _OwnedFileBinding,
    *,
    started_at: float,
) -> None:
    actual = _capture_owned_file_binding(
        path,
        expected_identity=expected.identity,
        started_at=started_at,
        changed=True,
    )
    if (
        actual.size != expected.size
        or actual.mtime_ns != expected.mtime_ns
        or actual.sha256 != expected.sha256
    ):
        _raise("snapshot_unstable")


@dataclass
class _OwnedWalGuard:
    path: Path
    descriptor: int
    expected: _OwnedFileBinding

    def validate_identity(self) -> os.stat_result:
        try:
            details = self.path.lstat()
            opened = os.fstat(self.descriptor)
        except FileNotFoundError as error:
            _raise("snapshot_unstable", error)
        except OSError as error:
            _raise(_os_failure_code(error), error)
        if _is_reparse(details) or not stat.S_ISREG(details.st_mode):
            _raise("snapshot_invalid")
        if _identity(details) != self.expected.identity:
            _raise("snapshot_unstable")
        if details.st_nlink != 1:
            _raise("snapshot_unstable")
        if (
            _is_reparse(opened)
            or not stat.S_ISREG(opened.st_mode)
            or _identity(opened) != self.expected.identity
            or opened.st_nlink != 1
        ):
            _raise("snapshot_unstable")
        return opened

    def validate_original_bytes(self, *, started_at: float) -> None:
        before = self.validate_identity()
        digest = hashlib.sha256()
        observed = 0
        try:
            os.lseek(self.descriptor, 0, os.SEEK_SET)
            while True:
                _check_deadline(started_at)
                chunk = os.read(self.descriptor, _COPY_CHUNK_SIZE)
                _check_deadline(started_at)
                if not chunk:
                    break
                observed += len(chunk)
                digest.update(chunk)
        except DiagnosticSnapshotError:
            raise
        except OSError as error:
            _raise(_os_failure_code(error), error)
        after = self.validate_identity()
        if (
            before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or observed != after.st_size
            or after.st_size != self.expected.size
            or after.st_mtime_ns != self.expected.mtime_ns
            or digest.hexdigest() != self.expected.sha256
        ):
            _raise("snapshot_unstable")


@contextmanager
def _guard_owned_wal(
    path: Path,
    expected: _OwnedFileBinding,
    *,
    started_at: float,
) -> Iterator[_OwnedWalGuard]:
    descriptor: int | None = None
    try:
        try:
            details = path.lstat()
        except FileNotFoundError as error:
            _raise("snapshot_unstable", error)
        except OSError as error:
            _raise(_os_failure_code(error), error)
        if _is_reparse(details) or not stat.S_ISREG(details.st_mode):
            _raise("snapshot_invalid")
        if _identity(details) != expected.identity:
            _raise("snapshot_unstable")
        if details.st_nlink != 1:
            _raise("snapshot_unstable")
        descriptor = _windows_guarded_file_descriptor(path)
        guard = _OwnedWalGuard(path, descriptor, expected)
        guard.validate_original_bytes(started_at=started_at)
        yield guard
        guard.validate_identity()
    except DiagnosticSnapshotError:
        raise
    except FileNotFoundError as error:
        _raise("snapshot_unstable", error)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _create_empty_owned_sentinel(
    path: Path,
    *,
    started_at: float,
) -> _OwnedFileBinding:
    try:
        with path.open("xb") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        details = _regular_lstat(path, changed=True)
        if details.st_size != 0 or details.st_nlink != 1:
            _raise("snapshot_invalid")
        binding = _capture_owned_file_binding(
            path,
            expected_identity=_identity(details),
            started_at=started_at,
        )
    except DiagnosticSnapshotError:
        raise
    except OSError as error:
        _raise(_os_failure_code(error), error)
    if binding.size != 0 or binding.sha256 != _EMPTY_SHA256:
        _raise("snapshot_invalid")
    return binding


def _delete_empty_owned_sentinel(
    path: Path,
    expected: _OwnedFileBinding,
) -> None:
    descriptor: int | None = None
    try:
        details = path.lstat()
        if (
            _is_reparse(details)
            or not stat.S_ISREG(details.st_mode)
            or _identity(details) != expected.identity
            or details.st_nlink != 1
            or details.st_size != 0
            or expected.size != 0
            or expected.sha256 != _EMPTY_SHA256
        ):
            raise RuntimeError("owned sentinel changed before cleanup")
        descriptor = _windows_guarded_delete_file_descriptor(path)
        opened = os.fstat(descriptor)
        if (
            _is_reparse(opened)
            or not stat.S_ISREG(opened.st_mode)
            or _identity(opened) != expected.identity
            or opened.st_nlink != 1
            or opened.st_size != 0
        ):
            raise RuntimeError("owned sentinel identity changed during cleanup")
        _windows_mark_delete_on_close(descriptor)
    except BaseException as error:
        _raise("snapshot_cleanup_failed", error)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        path.lstat()
    except FileNotFoundError:
        return
    except OSError as error:
        _raise("snapshot_cleanup_failed", error)
    _raise("snapshot_cleanup_failed")


def _raise_normalization_failure(error: BaseException) -> NoReturn:
    if isinstance(error, DiagnosticSnapshotError):
        raise error
    if isinstance(error, MemoryError):
        _raise("snapshot_resource_limit", error)
    if isinstance(error, sqlite3.DatabaseError):
        _raise(_sqlite_failure_code(error), error)
    if isinstance(error, OSError):
        _raise(_os_failure_code(error), error)
    _raise("snapshot_invalid", error)


def _normalize_read_only_database(
    input_root: Path,
    output_root: Path,
    *,
    input_database: _OwnedFileBinding,
    input_wal: _OwnedFileBinding,
    input_shm: _OwnedFileBinding,
    synthetic_wal: bool,
    page_size: int,
    started_at: float,
) -> _OwnedFileBinding:
    input_database_path = input_root / "state.sqlite3"
    input_wal_path = input_root / "state.sqlite3-wal"
    input_shm_path = input_root / "state.sqlite3-shm"
    output_database_path = output_root / "state.sqlite3"
    input_connection: sqlite3.Connection | None = None
    memory_connection: sqlite3.Connection | None = None
    output_binding: _OwnedFileBinding | None = None
    pending: BaseException | None = None
    maximum_pages = _OWNED_MAIN_LIMIT // page_size
    try:
        with (
            _guard_owned_wal(
                input_database_path,
                input_database,
                started_at=started_at,
            ) as database_guard,
            _guard_owned_wal(
                input_wal_path,
                input_wal,
                started_at=started_at,
            ) as wal_guard,
            _guard_owned_wal(
                input_shm_path,
                input_shm,
                started_at=started_at,
            ) as shm_guard,
        ):
            try:
                _check_deadline(started_at)
                input_connection = sqlite3.connect(
                    f"{input_database_path.as_uri()}?mode=ro",
                    uri=True,
                    timeout=0.25,
                )
                _execute_rows(
                    input_connection,
                    "PRAGMA query_only=ON",
                    started_at=started_at,
                )
                if (
                    _single_integer(
                        input_connection,
                        "PRAGMA query_only",
                        started_at=started_at,
                    )
                    != 1
                ):
                    _raise("snapshot_invalid")
                _test_seam(
                    "after_readonly_input_open",
                    input_root=input_root,
                    input_database=input_database_path,
                    output_root=output_root,
                    output_database=output_database_path,
                )
                database_guard.validate_identity()
                wal_guard.validate_identity()
                shm_guard.validate_identity()
                _owned_tree_size(input_root.parent, started_at=started_at)
                _test_seam("before_consolidation", staging=output_root)
                _check_deadline(started_at)
                memory_connection = sqlite3.connect(":memory:", timeout=0.25)
                _check_deadline(started_at)
                _test_seam(
                    "before_readonly_backup",
                    input_root=input_root,
                    output_root=output_root,
                    input_database=input_database_path,
                    output_database=output_database_path,
                )
                progress: _BackupProgress
                progress = _BackupProgress(
                    started_at=started_at,
                    check_bounds=lambda: _owned_tree_size(
                        input_root.parent,
                        started_at=started_at,
                        extra_bytes=(progress.total or 0) * page_size,
                    ),
                    max_pages=maximum_pages,
                )
                input_connection.backup(
                    memory_connection,
                    pages=_BACKUP_PAGES,
                    progress=progress,
                    sleep=0.0,
                )
                progress.require_complete()
                _test_seam(
                    "after_readonly_backup",
                    input_root=input_root,
                    output_root=output_root,
                    input_database=input_database_path,
                    output_database=output_database_path,
                )
                _owned_tree_size(input_root.parent, started_at=started_at)

                memory_page_size = _single_integer(
                    memory_connection,
                    "PRAGMA page_size",
                    started_at=started_at,
                )
                page_count = _single_integer(
                    memory_connection,
                    "PRAGMA page_count",
                    started_at=started_at,
                )
                logical_size = memory_page_size * page_count
                if memory_page_size != page_size:
                    _raise("snapshot_invalid")
                if page_count < 0 or logical_size > _OWNED_MAIN_LIMIT:
                    _raise("snapshot_resource_limit")
                _owned_tree_size(
                    input_root.parent,
                    started_at=started_at,
                    extra_bytes=logical_size,
                )
                _test_seam(
                    "after_memory_page_validation",
                    output_database=output_database_path,
                    page_size=memory_page_size,
                    page_count=page_count,
                )

                _check_deadline(started_at)
                try:
                    serialized = memory_connection.serialize()
                except (MemoryError, OSError, sqlite3.DatabaseError):
                    raise
                except Exception as error:
                    _raise("snapshot_invalid", error)
                _check_deadline(started_at)
                if type(serialized) is not bytes:
                    _raise("snapshot_invalid")
                serialized_size = len(serialized)
                if serialized_size > _OWNED_MAIN_LIMIT:
                    _raise("snapshot_resource_limit")
                if serialized_size != logical_size:
                    _raise("snapshot_invalid")
                serialized_sha256 = hashlib.sha256(serialized).hexdigest()
                _owned_tree_size(
                    input_root.parent,
                    started_at=started_at,
                    extra_bytes=logical_size + serialized_size,
                )
                _test_seam(
                    "after_serialize",
                    output_database=output_database_path,
                    page_size=memory_page_size,
                    page_count=page_count,
                    serialized_size=serialized_size,
                    serialized_sha256=serialized_sha256,
                )

                _check_deadline(started_at)
                _test_seam(
                    "before_output_create",
                    output_database=output_database_path,
                )
                _check_deadline(started_at)
                output_identity: tuple[int, int]
                written = 0
                output_digest = hashlib.sha256()
                try:
                    with output_database_path.open("xb") as output_stream:
                        opened = os.fstat(output_stream.fileno())
                        if (
                            _is_reparse(opened)
                            or not stat.S_ISREG(opened.st_mode)
                            or opened.st_nlink != 1
                            or opened.st_size != 0
                        ):
                            _raise("snapshot_invalid")
                        output_identity = _identity(opened)
                        view = memoryview(serialized)
                        for offset in range(0, serialized_size, _COPY_CHUNK_SIZE):
                            _check_deadline(started_at)
                            chunk = view[offset : offset + _COPY_CHUNK_SIZE]
                            count = output_stream.write(chunk)
                            if count != len(chunk):
                                _raise("snapshot_unavailable")
                            written += count
                            if written > _OWNED_MAIN_LIMIT:
                                _raise("snapshot_resource_limit")
                            output_digest.update(chunk)
                            _owned_tree_size(
                                input_root.parent,
                                started_at=started_at,
                                extra_bytes=logical_size + serialized_size,
                            )
                            _test_seam(
                                "during_output_write",
                                output_database=output_database_path,
                                chunk_index=offset // _COPY_CHUNK_SIZE,
                            )
                        _check_deadline(started_at)
                        output_stream.flush()
                        os.fsync(output_stream.fileno())
                        _check_deadline(started_at)
                except FileExistsError as error:
                    _raise("snapshot_invalid", error)
                _check_deadline(started_at)
                _test_seam(
                    "after_fsync",
                    output_database=output_database_path,
                )
                output_binding = _capture_owned_file_binding(
                    output_database_path,
                    expected_identity=output_identity,
                    started_at=started_at,
                    changed=True,
                )
                if (
                    written != serialized_size
                    or output_digest.hexdigest() != serialized_sha256
                    or output_binding.size != serialized_size
                    or output_binding.sha256 != serialized_sha256
                ):
                    _raise("snapshot_unstable")
                _owned_tree_size(
                    input_root.parent,
                    started_at=started_at,
                    extra_bytes=logical_size + serialized_size,
                )
            except BaseException as error:
                pending = error
            finally:
                if input_connection is not None:
                    try:
                        input_connection.close()
                    except BaseException as error:
                        pending = error
                    input_connection = None
                try:
                    database_guard.validate_original_bytes(started_at=started_at)
                    wal_guard.validate_original_bytes(started_at=started_at)
                    shm_guard.validate_original_bytes(started_at=started_at)
                    _test_seam(
                        "after_readonly_input_close",
                        input_root=input_root,
                        output_root=output_root,
                        input_database=input_database_path,
                        output_database=output_database_path,
                    )
                except BaseException as error:
                    pending = error
    except BaseException as error:
        if pending is None:
            pending = error
    finally:
        if input_connection is not None:
            try:
                input_connection.close()
            except BaseException as error:
                pending = error
        if memory_connection is not None:
            try:
                memory_connection.close()
            except BaseException as error:
                pending = error
        try:
            _check_deadline(started_at)
            _owned_tree_size(input_root.parent, started_at=started_at)
        except BaseException as error:
            pending = error

    try:
        if synthetic_wal:
            _delete_empty_owned_sentinel(input_wal_path, input_wal)
        _delete_empty_owned_sentinel(input_shm_path, input_shm)
    except BaseException as error:
        _raise("snapshot_cleanup_failed", error)

    if pending is not None:
        _raise_normalization_failure(pending)
    if output_binding is None:
        _raise("snapshot_invalid")
    return output_binding


def _supports_handle_bound_snapshot() -> bool:
    return os.name == "nt"


def _require_owned_layout(
    modeling: Path,
    *,
    expected_project_json: _OwnedFileBinding,
    expected_database: _OwnedFileBinding,
    started_at: float,
) -> None:
    _check_deadline(started_at)
    _owned_tree_size(modeling, started_at=started_at)
    try:
        names = {
            path.name
            for path in _bounded_entries(
                modeling,
                _OUTPUT_NAMES,
                started_at=started_at,
            )
        }
        if names != _REQUIRED_NAMES:
            _raise("snapshot_invalid")
        _regular_lstat(modeling / "project.lock")
        _require_owned_file_binding(
            modeling / "project.json",
            expected_project_json,
            started_at=started_at,
        )
        _require_owned_file_binding(
            modeling / "state.sqlite3",
            expected_database,
            started_at=started_at,
        )
        database_details = _validate_owned_database_identity(
            modeling / "state.sqlite3",
            expected_database.identity,
        )
        if (modeling / "project.lock").read_bytes() != b"\0":
            _raise("snapshot_invalid")
        if database_details.st_size > _OWNED_MAIN_LIMIT:
            _raise("snapshot_resource_limit")
    except DiagnosticSnapshotError:
        raise
    except OSError as error:
        _raise(_os_failure_code(error), error)
    _check_deadline(started_at)


def _prepare_initialized_snapshot(
    paths: ProjectPaths,
    owned_root: Path,
    *,
    owned_children: dict[str, tuple[int, int]],
    source_guard: _DirectoryGuard,
    started_at: float,
) -> DiagnosticSnapshot:
    source = paths.modeling
    input_root = owned_root / ".modeling.input"
    staging = owned_root / ".modeling.staging"
    published = owned_root / ".modeling"
    manifest_a = _capture_manifest(
        source,
        guard=source_guard,
        started_at=started_at,
        changed=False,
    )
    _test_seam("after_manifest_a", source=source)
    try:
        input_root.mkdir(mode=0o700)
        staging.mkdir(mode=0o700)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    owned_children[input_root.name] = _identity(_directory_lstat(input_root))
    owned_children[staging.name] = _identity(_directory_lstat(staging))
    total = sum(details.size for _, details in manifest_a.persistent)
    if total > _TOTAL_COPY_LIMIT:
        _raise("snapshot_resource_limit")
    for name, details in manifest_a.persistent:
        _copy_persistent_member(
            source_guard,
            name,
            input_root / name,
            details,
            started_at=started_at,
        )
    _test_seam("after_raw_copy", staging=input_root)
    _owned_tree_size(owned_root, started_at=started_at)
    _verify_copied_members(input_root, manifest_a, started_at=started_at)
    input_project_json = input_root / "project.json"
    input_project_json_binding = _capture_owned_file_binding(
        input_project_json,
        expected_identity=_identity(_regular_lstat(input_project_json)),
        started_at=started_at,
    )
    _test_seam("before_manifest_b", source=source)
    manifest_b = _capture_manifest(
        source,
        guard=source_guard,
        started_at=started_at,
        changed=True,
    )
    if manifest_a != manifest_b:
        _raise("snapshot_unstable")
    page_size = _validate_raw_database(input_root)
    input_database_path = input_root / "state.sqlite3"
    input_database_binding = _capture_owned_file_binding(
        input_database_path,
        expected_identity=_identity(_regular_lstat(input_database_path)),
        started_at=started_at,
    )
    input_wal_path = input_root / "state.sqlite3-wal"
    synthetic_wal = "state.sqlite3-wal" not in manifest_a.names
    if "state.sqlite3-wal" in manifest_a.names:
        input_wal_binding = _capture_owned_file_binding(
            input_wal_path,
            expected_identity=_identity(_regular_lstat(input_wal_path)),
            started_at=started_at,
        )
    else:
        _require_absent(input_wal_path)
        input_wal_binding = _create_empty_owned_sentinel(
            input_wal_path,
            started_at=started_at,
        )
    input_shm_path = input_root / "state.sqlite3-shm"
    _require_absent(input_shm_path)
    input_shm_binding = _create_empty_owned_sentinel(
        input_shm_path,
        started_at=started_at,
    )
    if {
        path.name
        for path in _bounded_entries(
            input_root,
            _INPUT_NAMES,
            started_at=started_at,
        )
    } != _INPUT_NAMES:
        _raise("snapshot_invalid")

    output_project_json_binding = _copy_owned_project_json(
        input_project_json,
        staging / "project.json",
        input_project_json_binding,
        started_at=started_at,
    )
    try:
        (staging / "project.lock").write_bytes(b"\0")
    except OSError as error:
        _raise(_os_failure_code(error), error)
    output_database_binding = _normalize_read_only_database(
        input_root,
        staging,
        input_database=input_database_binding,
        input_wal=input_wal_binding,
        input_shm=input_shm_binding,
        synthetic_wal=synthetic_wal,
        page_size=page_size,
        started_at=started_at,
    )
    try:
        input_descriptor, input_members = _bind_cleanup_directory(
            input_root,
            owned_children[input_root.name],
        )
        _cleanup_bound_directory(
            input_root,
            owned_children[input_root.name],
            input_descriptor,
            input_members,
        )
    except BaseException as error:
        _raise("snapshot_cleanup_failed", error)
    owned_children.pop(input_root.name)
    _test_seam("after_input_cleanup", input_root=input_root, output_root=staging)
    _require_owned_layout(
        staging,
        expected_project_json=output_project_json_binding,
        expected_database=output_database_binding,
        started_at=started_at,
    )
    _test_seam("after_destination_validation", staging=staging)
    _require_owned_layout(
        staging,
        expected_project_json=output_project_json_binding,
        expected_database=output_database_binding,
        started_at=started_at,
    )
    _check_deadline(started_at)
    try:
        os.replace(staging, published)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    expected_published_identity = owned_children.pop(staging.name)
    if (
        _identity(_directory_lstat(published, changed=True))
        != expected_published_identity
    ):
        _raise("snapshot_unstable")
    owned_children[published.name] = expected_published_identity
    _check_deadline(started_at)
    _test_seam("after_publication", published=published)
    _require_owned_layout(
        published,
        expected_project_json=output_project_json_binding,
        expected_database=output_database_binding,
        started_at=started_at,
    )
    _owned_tree_size(owned_root, started_at=started_at)
    return DiagnosticSnapshot(
        project_root=owned_root,
        source_state_hint="INITIALIZED",
    )


def _bind_source(
    project_root: Path,
) -> tuple[
    ProjectPaths,
    bool,
    tuple[int, int],
    tuple[int, int] | None,
]:
    try:
        paths = ProjectPaths.bind(project_root)
    except (FileNotFoundError, NotADirectoryError, ValueError) as error:
        _raise("snapshot_invalid", error)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    root_identity = _identity(_directory_lstat(paths.root))
    try:
        modeling_is_reparse = is_reparse_point(paths.modeling)
    except OSError as error:
        _raise(_os_failure_code(error), error)
    if modeling_is_reparse:
        _raise("snapshot_invalid")
    try:
        paths.modeling.lstat()
    except FileNotFoundError:
        return paths, False, root_identity, None
    except OSError as error:
        _raise(_os_failure_code(error), error)
    modeling_identity = _identity(_directory_lstat(paths.modeling))
    return paths, True, root_identity, modeling_identity


def _create_owned_root() -> Path:
    try:
        return Path(tempfile.mkdtemp(prefix="modeling-diagnostic-"))
    except OSError as error:
        _raise(_os_failure_code(error), error)


def _remove_created_owned_root(
    path: Path,
    expected_identity: tuple[int, int],
    descriptor: int | None,
) -> None:
    owned_descriptor = descriptor
    try:
        if owned_descriptor is None:
            owned_descriptor = _windows_delete_directory_descriptor(path)
        details = path.lstat()
        opened = os.fstat(owned_descriptor)
        if (
            _is_reparse(details)
            or _is_reparse(opened)
            or not stat.S_ISDIR(details.st_mode)
            or not stat.S_ISDIR(opened.st_mode)
            or _identity(details) != expected_identity
            or _identity(opened) != expected_identity
        ):
            raise RuntimeError("created diagnostic root identity changed")
        if _bounded_entries(path, frozenset()):
            raise RuntimeError("created diagnostic root is not empty")
        _windows_mark_delete_on_close(owned_descriptor)
    finally:
        if owned_descriptor is not None:
            os.close(owned_descriptor)
    if path.exists():
        raise RuntimeError("created diagnostic root was not deleted")


def _bind_created_owned_root(path: Path) -> tuple[int, int]:
    try:
        initial = path.lstat()
    except OSError as error:
        _raise("snapshot_cleanup_failed", error)
    if _is_reparse(initial) or not stat.S_ISDIR(initial.st_mode):
        _raise("snapshot_cleanup_failed")
    expected_identity = _identity(initial)
    descriptor: int | None = None
    try:
        descriptor = _windows_delete_directory_descriptor(path)
        opened = os.fstat(descriptor)
        if (
            _is_reparse(opened)
            or not stat.S_ISDIR(opened.st_mode)
            or _identity(opened) != expected_identity
        ):
            _raise("snapshot_unstable")
        details = _directory_lstat(path)
        if (
            _is_reparse(details)
            or not stat.S_ISDIR(details.st_mode)
            or _identity(details) != expected_identity
        ):
            _raise("snapshot_unstable")
        os.close(descriptor)
        descriptor = None
        return expected_identity
    except BaseException as primary:
        cleanup_descriptor = descriptor
        descriptor = None
        try:
            _remove_created_owned_root(
                path,
                expected_identity,
                cleanup_descriptor,
            )
        except BaseException as cleanup_error:
            _raise("snapshot_cleanup_failed", cleanup_error)
        if isinstance(primary, DiagnosticSnapshotError):
            raise primary
        if isinstance(primary, OSError):
            _raise(_os_failure_code(primary), primary)
        raise primary
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _cleanup_owned_file(path: Path, expected_identity: tuple[int, int]) -> None:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = _windows_guarded_delete_file_descriptor(path)
        opened = os.fstat(descriptor)
        if (
            _is_reparse(before)
            or _is_reparse(opened)
            or not stat.S_ISREG(before.st_mode)
            or not stat.S_ISREG(opened.st_mode)
            or _identity(before) != expected_identity
            or _identity(opened) != expected_identity
        ):
            raise RuntimeError("refusing to clean a replaced diagnostic file")
        _windows_mark_delete_on_close(descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise RuntimeError("diagnostic file was not deleted")


def _bind_cleanup_directory(
    path: Path,
    expected_identity: tuple[int, int],
) -> tuple[int, dict[str, tuple[int, int]]]:
    descriptor: int | None = None
    try:
        before = path.lstat()
        descriptor = _windows_delete_directory_descriptor(path)
        opened = os.fstat(descriptor)
        if (
            _is_reparse(before)
            or _is_reparse(opened)
            or not stat.S_ISDIR(before.st_mode)
            or not stat.S_ISDIR(opened.st_mode)
            or _identity(before) != expected_identity
            or _identity(opened) != expected_identity
        ):
            raise RuntimeError("refusing to clean a replaced diagnostic directory")
        allowed_names = (
            _INPUT_NAMES if path.name == ".modeling.input" else _OUTPUT_NAMES
        )
        entries = _bounded_entries(path, allowed_names)
        identities: dict[str, tuple[int, int]] = {}
        for entry in entries:
            if entry.name not in _ALLOWED_NAMES:
                raise RuntimeError("diagnostic directory contains an unsafe member")
            details = entry.lstat()
            if _is_reparse(details) or not stat.S_ISREG(details.st_mode):
                raise RuntimeError("diagnostic directory contains an unsafe member")
            identities[entry.name] = _identity(details)
        result = descriptor, identities
        descriptor = None
        return result
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _cleanup_bound_directory(
    path: Path,
    expected_identity: tuple[int, int],
    descriptor: int,
    identities: dict[str, tuple[int, int]],
) -> None:
    try:
        current = path.lstat()
        opened = os.fstat(descriptor)
        if (
            _is_reparse(current)
            or _is_reparse(opened)
            or not stat.S_ISDIR(current.st_mode)
            or not stat.S_ISDIR(opened.st_mode)
            or _identity(current) != expected_identity
            or _identity(opened) != expected_identity
        ):
            raise RuntimeError("diagnostic child changed during cleanup")
        _test_seam("after_cleanup_child_validation", owned_child=path)
        current = path.lstat()
        if _identity(current) != expected_identity:
            raise RuntimeError("diagnostic child changed during cleanup")
        for name in sorted(identities, key=lambda item: item.encode("utf-8")):
            _cleanup_owned_file(path / name, identities[name])
        allowed_names = (
            _INPUT_NAMES if path.name == ".modeling.input" else _OUTPUT_NAMES
        )
        if _bounded_entries(path, allowed_names):
            raise RuntimeError("diagnostic directory changed during cleanup")
        _windows_mark_delete_on_close(descriptor)
    finally:
        os.close(descriptor)
    try:
        path.lstat()
    except FileNotFoundError:
        return
    raise RuntimeError("diagnostic directory was not deleted")


def _cleanup_owned_root(
    path: Path,
    expected_identity: tuple[int, int],
    expected_children: dict[str, tuple[int, int]],
) -> None:
    if not path.name.startswith("modeling-diagnostic-"):
        raise RuntimeError("refusing to clean an unowned diagnostic root")
    if os.name != "nt":
        raise RuntimeError("handle-bound cleanup is unavailable")
    descriptor: int | None = None
    try:
        descriptor = _windows_delete_directory_descriptor(path)
        details = path.lstat()
        opened = os.fstat(descriptor)
        if (
            _is_reparse(details)
            or _is_reparse(opened)
            or not stat.S_ISDIR(details.st_mode)
            or not stat.S_ISDIR(opened.st_mode)
            or _identity(details) != expected_identity
            or _identity(opened) != expected_identity
        ):
            raise RuntimeError("refusing to clean a replaced diagnostic root")
        children = _bounded_entries(path, _OWNED_ROOT_NAMES)
        if {child.name for child in children} != set(expected_children):
            raise RuntimeError("diagnostic root contains unexpected members")
        bound_children: list[
            tuple[Path, tuple[int, int], int, dict[str, tuple[int, int]]]
        ] = []
        try:
            for child in sorted(children, key=lambda item: item.name.encode("utf-8")):
                child_identity = expected_children[child.name]
                child_descriptor, member_identities = _bind_cleanup_directory(
                    child,
                    child_identity,
                )
                bound_children.append(
                    (child, child_identity, child_descriptor, member_identities)
                )
            _test_seam("after_cleanup_validation", owned_root=path)
            if _identity(path.lstat()) != expected_identity:
                raise RuntimeError("diagnostic root changed during cleanup")
            while bound_children:
                child, child_identity, child_descriptor, member_identities = (
                    bound_children.pop(0)
                )
                _cleanup_bound_directory(
                    child,
                    child_identity,
                    child_descriptor,
                    member_identities,
                )
        finally:
            for _, _, child_descriptor, _ in bound_children:
                os.close(child_descriptor)
        if _identity(path.lstat()) != expected_identity:
            raise RuntimeError("diagnostic root changed during cleanup")
        _windows_mark_delete_on_close(descriptor)
    finally:
        if descriptor is not None:
            os.close(descriptor)
    if path.exists():
        raise RuntimeError("diagnostic root was not deleted")


@contextmanager
def materialize_diagnostic_snapshot(
    project_root: Path,
) -> Iterator[DiagnosticSnapshot]:
    """Yield one verified owned snapshot without opening source SQLite state."""
    if not _supports_handle_bound_snapshot():
        _raise("snapshot_unavailable")
    started_at = time.monotonic()
    paths, initialized, root_identity, modeling_identity = _bind_source(
        Path(project_root)
    )
    _check_deadline(started_at)
    owned_root = _create_owned_root()
    owned_identity = _bind_created_owned_root(owned_root)
    owned_children: dict[str, tuple[int, int]] = {}
    try:
        _check_deadline(started_at)
        try:
            with _guard_directory(paths.root, root_identity) as root_guard:
                if initialized:
                    if modeling_identity is None:
                        raise AssertionError(
                            "initialized source lacks directory identity"
                        )
                    with _guard_directory(
                        paths.modeling,
                        modeling_identity,
                        parent=root_guard,
                        member_name=".modeling",
                    ) as source_guard:
                        diagnostic = _prepare_initialized_snapshot(
                            paths,
                            owned_root,
                            owned_children=owned_children,
                            source_guard=source_guard,
                            started_at=started_at,
                        )
                else:
                    _test_seam(
                        "before_uninitialized_absence_recheck",
                        modeling=paths.modeling,
                    )
                    root_guard.validate_path()
                    try:
                        paths.modeling.lstat()
                    except FileNotFoundError:
                        pass
                    except OSError as error:
                        _raise(_os_failure_code(error), error)
                    else:
                        _raise("snapshot_unstable")
                    root_guard.validate_path()
                    diagnostic = DiagnosticSnapshot(
                        project_root=owned_root,
                        source_state_hint="UNINITIALIZED",
                    )
        except DiagnosticSnapshotError:
            raise
        except sqlite3.DatabaseError as error:
            _raise(_sqlite_failure_code(error), error)
        except OSError as error:
            _raise(_os_failure_code(error), error)
        yield diagnostic
    finally:
        try:
            _test_seam("during_cleanup", owned_root=owned_root)
            _cleanup_owned_root(owned_root, owned_identity, owned_children)
        except BaseException as error:
            _raise("snapshot_cleanup_failed", error)


__all__ = [
    "DiagnosticSnapshot",
    "DiagnosticSnapshotError",
    "SnapshotFailureCode",
    "materialize_diagnostic_snapshot",
]
