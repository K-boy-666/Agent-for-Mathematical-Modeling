from __future__ import annotations

import errno
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator
from urllib.parse import urlsplit
from urllib.request import url2pathname

import pytest

from modeling_core.contracts.versions import VersionSet
from modeling_infrastructure import diagnostic_snapshot as snapshot_impl
from modeling_infrastructure.diagnostic_snapshot import (
    DiagnosticSnapshotError,
    materialize_diagnostic_snapshot,
)
from modeling_infrastructure.project_lock import ProjectLock
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import bootstrap_storage


EXPECTED_LAYOUT = {"project.json", "project.lock", "state.sqlite3"}
FINITE_CODES = {
    "snapshot_unstable",
    "snapshot_invalid",
    "snapshot_resource_limit",
    "snapshot_unavailable",
    "snapshot_cleanup_failed",
}


def _file_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _file_identity(path: Path) -> tuple[int, int]:
    details = path.lstat()
    return details.st_dev, details.st_ino


def _start_wal_writer(root: Path, value: str = "committed") -> sqlite3.Connection:
    database = root / ".modeling" / "state.sqlite3"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA wal_autocheckpoint=0")
    connection.execute("CREATE TABLE IF NOT EXISTS snapshot_probe(value TEXT NOT NULL)")
    connection.execute("DELETE FROM snapshot_probe")
    connection.execute("INSERT INTO snapshot_probe(value) VALUES (?)", (value,))
    connection.commit()
    assert database.with_name("state.sqlite3-wal").is_file()
    return connection


def _snapshot_error(root: Path) -> DiagnosticSnapshotError:
    with pytest.raises(DiagnosticSnapshotError) as captured:
        with materialize_diagnostic_snapshot(root):
            pass
    return captured.value


def _redirect_directory(path: Path, target: Path) -> None:
    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(path), str(target)],
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
    else:
        path.symlink_to(target, target_is_directory=True)


def test_mode_ro_query_only_is_not_a_zero_byte_mutation_contract_on_wal(
    tmp_path: Path,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    modeling = tmp_path / ".modeling"
    database = modeling / "state.sqlite3"
    before = _file_bytes(modeling)

    with closing(sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)) as reader:
        reader.execute("PRAGMA query_only=ON")
        assert reader.execute("SELECT COUNT(*) FROM metadata").fetchone() == (4,)

    after = _file_bytes(modeling)
    assert after != before
    assert {"state.sqlite3-wal", "state.sqlite3-shm"} & set(after)


def test_diagnostic_snapshot_opens_no_sqlite_connection_or_project_lock_on_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    source_database = (tmp_path / ".modeling" / "state.sqlite3").resolve()
    sqlite_targets: list[Path] = []
    memory_targets = 0
    original_connect = snapshot_impl.sqlite3.connect

    def observed_connect(
        database: object, *args: object, **kwargs: object
    ) -> sqlite3.Connection:
        nonlocal memory_targets
        value = os.fspath(database)
        if value == ":memory:":
            memory_targets += 1
            return original_connect(database, *args, **kwargs)
        target = Path(
            url2pathname(urlsplit(value).path) if kwargs.get("uri") else value
        ).resolve()
        sqlite_targets.append(target)
        assert target != source_database
        return original_connect(database, *args, **kwargs)

    def forbidden_lock(*_: object, **__: object) -> None:
        raise AssertionError("diagnostic capture must not acquire ProjectLock")

    monkeypatch.setattr(snapshot_impl.sqlite3, "connect", observed_connect)
    monkeypatch.setattr(ProjectLock, "acquire", forbidden_lock)

    with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
        assert diagnostic.project_root != tmp_path
        assert len(sqlite_targets) == 1
        assert sqlite_targets[0].is_relative_to(diagnostic.project_root)
        assert memory_targets == 1
        assert {target.name for target in sqlite_targets} == {"state.sqlite3"}


@pytest.mark.parametrize("replaced", ["project-root", "modeling-directory"])
def test_source_directory_replacement_fails_before_redirect_target_content_is_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    replaced: str,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    bootstrap_storage(source_root, VersionSet.m1a())
    external_root = tmp_path / "external"
    external_root.mkdir()
    shutil.copytree(source_root / ".modeling", external_root / ".modeling")
    displaced = tmp_path / f"displaced-{replaced}"
    external_reads = 0
    original_enumerate = snapshot_impl._enumerate_source
    original_open = snapshot_impl._open_source_handle
    attacked = False

    def redirect_then_enumerate(*args: object, **kwargs: object) -> object:
        nonlocal attacked
        if not attacked:
            attacked = True
            if replaced == "project-root":
                source_root.rename(displaced)
                _redirect_directory(source_root, external_root)
            else:
                modeling = source_root / ".modeling"
                modeling.rename(displaced)
                _redirect_directory(modeling, external_root / ".modeling")
        return original_enumerate(*args, **kwargs)

    @contextmanager
    def count_external_reads(path: Path) -> Iterator[object]:
        nonlocal external_reads
        if path.resolve().is_relative_to(external_root.resolve()):
            external_reads += 1
        with original_open(path) as stream:
            yield stream

    monkeypatch.setattr(snapshot_impl, "_enumerate_source", redirect_then_enumerate)
    monkeypatch.setattr(snapshot_impl, "_open_source_handle", count_external_reads)

    error = _snapshot_error(source_root)

    assert error.code in FINITE_CODES
    assert external_reads == 0


@pytest.mark.parametrize("phase", ["after_destination_validation", "after_publication"])
@pytest.mark.parametrize("replacement", ["hardlink", "identity"])
def test_owned_database_identity_swap_fails_before_external_sqlite_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    replacement: str,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    bootstrap_storage(source_root, VersionSet.m1a())
    external_root = tmp_path / "external"
    external_root.mkdir()
    bootstrap_storage(external_root, VersionSet.m1a())
    external_database = external_root / ".modeling" / "state.sqlite3"
    external_identity = _file_identity(external_database)
    external_before = external_database.read_bytes()
    external_sqlite_opens = 0
    original_connect = snapshot_impl.sqlite3.connect

    def swap_owned_database(seam: str, **context: object) -> None:
        if seam != phase:
            return
        root_key = "published" if phase == "after_publication" else "staging"
        target = Path(str(context[root_key])) / "state.sqlite3"
        target.unlink()
        if replacement == "hardlink":
            os.link(external_database, target)
        else:
            shutil.copy2(external_database, target)

    def count_external_sqlite(
        database: object, *args: object, **kwargs: object
    ) -> sqlite3.Connection:
        nonlocal external_sqlite_opens
        target = Path(os.fspath(database))
        if target.exists() and _file_identity(target) == external_identity:
            external_sqlite_opens += 1
        return original_connect(database, *args, **kwargs)

    monkeypatch.setattr(snapshot_impl, "_test_seam", swap_owned_database)
    monkeypatch.setattr(snapshot_impl.sqlite3, "connect", count_external_sqlite)

    error = _snapshot_error(source_root)

    assert error.code == "snapshot_unstable"
    assert external_sqlite_opens == 0
    assert external_database.read_bytes() == external_before


@pytest.mark.parametrize(
    ("phase", "member", "mutation"),
    [
        ("after_destination_validation", "project.json", "inplace"),
        ("after_destination_validation", "state.sqlite3", "inplace"),
        ("after_publication", "project.json", "inplace"),
        ("after_publication", "state.sqlite3", "inplace"),
        ("after_destination_validation", "project.json", "replace"),
        ("after_publication", "project.json", "replace"),
    ],
)
def test_late_owned_byte_drift_fails_snapshot_unstable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    member: str,
    mutation: str,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    bootstrap_storage(source_root, VersionSet.m1a())
    source_before = _file_bytes(source_root / ".modeling")

    def mutate_owned_bytes(seam: str, **context: object) -> None:
        if seam != phase:
            return
        root_key = "published" if phase == "after_publication" else "staging"
        target = Path(str(context[root_key])) / member
        if mutation == "replace":
            replacement = target.with_name(f"{target.name}.replacement")
            replacement.write_bytes(target.read_bytes())
            os.replace(replacement, target)
            return
        with target.open("r+b") as stream:
            first = stream.read(1)
            assert first
            stream.seek(0)
            stream.write(bytes([first[0] ^ 0xFF]))
            stream.flush()
            os.fsync(stream.fileno())

    monkeypatch.setattr(snapshot_impl, "_test_seam", mutate_owned_bytes)

    error = _snapshot_error(source_root)

    assert error.code == "snapshot_unstable"
    assert _file_bytes(source_root / ".modeling") == source_before


def test_reparse_probe_permission_error_is_redacted_snapshot_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source-secret"
    source_root.mkdir()
    secret = "SECRET reparse permission credential"

    def permission_denied(_: Path) -> bool:
        raise PermissionError(errno.EACCES, secret)

    monkeypatch.setattr(snapshot_impl, "is_reparse_point", permission_denied)

    error = _snapshot_error(source_root)

    assert error.code == "snapshot_unavailable"
    assert secret not in str(error)
    assert secret not in repr(error)
    assert str(source_root) not in repr(error)


def test_owned_root_identity_bind_failure_never_leaks_created_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    created: list[Path] = []
    secret = "SECRET owned identity failure"
    original_mkdtemp = snapshot_impl.tempfile.mkdtemp
    original_directory_lstat = snapshot_impl._directory_lstat

    def tracked_mkdtemp(*args: object, **kwargs: object) -> str:
        result = original_mkdtemp(*args, **kwargs)
        created.append(Path(result))
        return result

    def fail_owned_identity(path: Path, *, changed: bool = False) -> os.stat_result:
        if created and path == created[-1]:
            raise PermissionError(errno.EACCES, secret)
        return original_directory_lstat(path, changed=changed)

    monkeypatch.setattr(snapshot_impl.tempfile, "mkdtemp", tracked_mkdtemp)
    monkeypatch.setattr(snapshot_impl, "_directory_lstat", fail_owned_identity)

    error = _snapshot_error(source_root)

    assert error.code in {"snapshot_unavailable", "snapshot_cleanup_failed"}
    assert created and all(not path.exists() for path in created)
    assert secret not in str(error)
    assert secret not in repr(error)


def test_owned_root_descriptor_open_denial_runs_safe_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    created: list[Path] = []
    denied = False
    secret = "SECRET created-root descriptor denial"
    original_mkdtemp = snapshot_impl.tempfile.mkdtemp
    original_descriptor = snapshot_impl._windows_delete_directory_descriptor

    def tracked_mkdtemp(*args: object, **kwargs: object) -> str:
        result = original_mkdtemp(*args, **kwargs)
        created.append(Path(result))
        return result

    def deny_first_bind(path: Path) -> int:
        nonlocal denied
        if created and path == created[-1] and not denied:
            denied = True
            raise PermissionError(errno.EACCES, secret)
        return original_descriptor(path)

    monkeypatch.setattr(snapshot_impl.tempfile, "mkdtemp", tracked_mkdtemp)
    monkeypatch.setattr(
        snapshot_impl,
        "_windows_delete_directory_descriptor",
        deny_first_bind,
    )

    error = _snapshot_error(source_root)

    assert error.code in {"snapshot_unavailable", "snapshot_cleanup_failed"}
    assert denied
    assert created and all(not path.exists() for path in created)
    assert secret not in str(error)
    assert secret not in repr(error)


@pytest.mark.parametrize("failure", ["identity-mismatch", "unsafe-shape"])
def test_owned_root_invalid_bound_identity_runs_safe_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    unsafe_file = tmp_path / "unsafe-file"
    unsafe_file.write_bytes(b"not-a-directory")
    created: list[Path] = []
    original_mkdtemp = snapshot_impl.tempfile.mkdtemp
    original_directory_lstat = snapshot_impl._directory_lstat

    def tracked_mkdtemp(*args: object, **kwargs: object) -> str:
        result = original_mkdtemp(*args, **kwargs)
        created.append(Path(result))
        return result

    def invalid_identity(path: Path, *, changed: bool = False) -> os.stat_result:
        if created and path == created[-1]:
            if failure == "unsafe-shape":
                return unsafe_file.lstat()
            details = original_directory_lstat(path, changed=changed)
            return SimpleNamespace(  # type: ignore[return-value]
                st_mode=details.st_mode,
                st_dev=details.st_dev,
                st_ino=details.st_ino + 1,
                st_file_attributes=0,
            )
        return original_directory_lstat(path, changed=changed)

    monkeypatch.setattr(snapshot_impl.tempfile, "mkdtemp", tracked_mkdtemp)
    monkeypatch.setattr(snapshot_impl, "_directory_lstat", invalid_identity)

    error = _snapshot_error(source_root)

    assert error.code in {"snapshot_unstable", "snapshot_cleanup_failed"}
    assert created and all(not path.exists() for path in created)


def test_uninitialized_absence_is_rechecked_under_bound_root_guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()

    def publish_modeling(phase: str, **_: object) -> None:
        if phase == "before_uninitialized_absence_recheck":
            (source_root / ".modeling").mkdir()

    monkeypatch.setattr(snapshot_impl, "_test_seam", publish_modeling)

    assert _snapshot_error(source_root).code == "snapshot_unstable"


def test_source_enumeration_stops_after_sixth_entry_without_listdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    bootstrap_storage(source_root, VersionSet.m1a())
    modeling = source_root / ".modeling"
    consumed = 0
    original_scandir = snapshot_impl.os.scandir
    original_listdir = snapshot_impl.os.listdir
    names = [
        "project.json",
        "project.lock",
        "state.sqlite3",
        "state.sqlite3-shm",
        "state.sqlite3-wal",
        "unexpected-sixth",
        "must-not-be-consumed",
    ]

    class FakeEntry:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeScandir:
        def __init__(self) -> None:
            self._iterator = iter(names)

        def __enter__(self) -> FakeScandir:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def __iter__(self) -> FakeScandir:
            return self

        def __next__(self) -> FakeEntry:
            nonlocal consumed
            name = next(self._iterator)
            consumed += 1
            return FakeEntry(name)

    def bounded_scandir(path: object) -> object:
        if Path(os.fspath(path)) == modeling:
            return FakeScandir()
        return original_scandir(path)

    def forbidden_listdir(path: object) -> list[str]:
        if Path(os.fspath(path)) == modeling:
            raise AssertionError("source enumeration must stream")
        return original_listdir(path)

    monkeypatch.setattr(snapshot_impl.os, "scandir", bounded_scandir)
    monkeypatch.setattr(snapshot_impl.os, "listdir", forbidden_listdir)

    error = _snapshot_error(source_root)

    assert error.code == "snapshot_invalid"
    assert consumed == 6


def test_source_streaming_enumeration_checks_deadline_before_member_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    bootstrap_storage(source_root, VersionSet.m1a())
    modeling = source_root / ".modeling"
    clock = [0.0]
    consumed = 0
    original_scandir = snapshot_impl.os.scandir
    names = [
        "project.json",
        "project.lock",
        "state.sqlite3",
        "state.sqlite3-shm",
        "state.sqlite3-wal",
        "deadline-sixth",
    ]

    class FakeEntry:
        def __init__(self, name: str) -> None:
            self.name = name

    class DeadlineScandir:
        def __init__(self) -> None:
            self._iterator = iter(names)

        def __enter__(self) -> DeadlineScandir:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def __iter__(self) -> DeadlineScandir:
            return self

        def __next__(self) -> FakeEntry:
            nonlocal consumed
            name = next(self._iterator)
            consumed += 1
            if consumed == 6:
                clock[0] = 11.0
            return FakeEntry(name)

    def deadline_scandir(path: object) -> object:
        if Path(os.fspath(path)) == modeling:
            return DeadlineScandir()
        return original_scandir(path)

    monkeypatch.setattr(snapshot_impl.os, "scandir", deadline_scandir)
    monkeypatch.setattr(snapshot_impl.time, "monotonic", lambda: clock[0])

    error = _snapshot_error(source_root)

    assert error.code == "snapshot_resource_limit"
    assert consumed == 6


def test_owned_and_cleanup_enumeration_stops_at_allowlist_plus_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_iterdir = Path.iterdir

    def exercise(path: Path, limit: int, action: object) -> None:
        observed = 0

        def counted_iterdir(candidate: Path) -> Iterator[Path]:
            nonlocal observed
            for entry in original_iterdir(candidate):
                if candidate == path:
                    observed += 1
                yield entry

        with monkeypatch.context() as isolated:
            isolated.setattr(Path, "iterdir", counted_iterdir)
            with pytest.raises((DiagnosticSnapshotError, RuntimeError)):
                action()  # type: ignore[operator]
        assert observed <= limit + 1

    owned = tmp_path / "modeling-diagnostic-owned-enumeration"
    owned.mkdir()
    for index in range(8):
        (owned / f"child-{index}").mkdir()
    exercise(
        owned,
        3,
        lambda: snapshot_impl._owned_tree_size(
            owned, started_at=snapshot_impl.time.monotonic()
        ),
    )

    for name, limit in ((".modeling.input", 4), (".modeling.staging", 3)):
        directory = tmp_path / name
        directory.mkdir()
        for index in range(8):
            (directory / f"member-{index}").write_bytes(b"x")
        exercise(
            directory,
            limit,
            lambda directory=directory: snapshot_impl._owned_tree_size(
                directory, started_at=snapshot_impl.time.monotonic()
            ),
        )

    for name, limit in ((".modeling.input", 4), (".modeling.staging", 3)):
        case_root = tmp_path / f"cleanup-{limit}"
        case_root.mkdir()
        production_name = case_root / name
        production_name.mkdir()
        for index in range(8):
            (production_name / f"member-{index}").write_bytes(b"x")
        exercise(
            production_name,
            limit,
            lambda production_name=production_name: (
                snapshot_impl._bind_cleanup_directory(
                    production_name, _file_identity(production_name)
                )
            ),
        )

    cleanup_root = tmp_path / "modeling-diagnostic-cleanup-enumeration"
    cleanup_root.mkdir()
    for index in range(8):
        (cleanup_root / f"child-{index}").mkdir()
    exercise(
        cleanup_root,
        3,
        lambda: snapshot_impl._cleanup_owned_root(
            cleanup_root, _file_identity(cleanup_root), {}
        ),
    )


@pytest.mark.parametrize("stage", ["hash", "copy"])
def test_stat_then_open_disappearance_is_snapshot_unstable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    bootstrap_storage(source_root, VersionSet.m1a())
    original_open_member = snapshot_impl._DirectoryGuard.open_member
    project_json_opens = 0
    secret = "SECRET vanished source member"

    @contextmanager
    def disappear_after_stat(
        guard: object,
        name: str,
    ) -> Iterator[object]:
        nonlocal project_json_opens
        if name == "project.json":
            project_json_opens += 1
            target_open = 1 if stage == "hash" else 2
            if project_json_opens == target_open:
                source = source_root / ".modeling" / name
                source.unlink()
                raise FileNotFoundError(errno.ENOENT, secret, str(source))
        with original_open_member(guard, name) as stream:  # type: ignore[arg-type]
            yield stream

    monkeypatch.setattr(
        snapshot_impl._DirectoryGuard,
        "open_member",
        disappear_after_stat,
    )

    error = _snapshot_error(source_root)

    assert error.code == "snapshot_unstable"
    assert secret not in str(error)
    assert secret not in repr(error)


def _assert_guard_blocks_write_truncate_and_replace(path: Path) -> None:
    replacement = path.with_name(f"{path.name}.attack")
    replacement.write_bytes(b"replacement")
    try:
        with pytest.raises(PermissionError):
            os.replace(replacement, path)
        with pytest.raises(PermissionError):
            with path.open("r+b") as stream:
                stream.write(b"x")
        with pytest.raises(PermissionError):
            os.truncate(path, 0)
    finally:
        if replacement.exists():
            replacement.unlink()


@pytest.mark.skipif(os.name != "nt", reason="Windows FILE_SHARE_READ contract")
def test_read_only_backup_guards_block_raw_input_write_and_truncate_after_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    bootstrap_storage(source_root, VersionSet.m1a())
    writer = _start_wal_writer(source_root)
    guarded: set[str] = set()

    def attack_read_only_input(phase: str, **context: object) -> None:
        if phase != "after_readonly_input_open":
            return
        input_root = Path(str(context["input_root"]))
        for name in ("state.sqlite3", "state.sqlite3-wal", "state.sqlite3-shm"):
            _assert_guard_blocks_write_truncate_and_replace(input_root / name)
            guarded.add(name)

    monkeypatch.setattr(snapshot_impl, "_test_seam", attack_read_only_input)
    try:
        with materialize_diagnostic_snapshot(source_root):
            pass
    finally:
        writer.close()

    assert guarded == {"state.sqlite3", "state.sqlite3-wal", "state.sqlite3-shm"}


@pytest.mark.skipif(os.name != "nt", reason="Windows FILE_SHARE_READ contract")
def test_absent_source_wal_uses_guarded_empty_sentinel_that_blocks_create_write_and_truncate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    bootstrap_storage(source_root, VersionSet.m1a())
    source_wal = source_root / ".modeling" / "state.sqlite3-wal"
    assert not source_wal.exists()
    observed = False

    def attack_empty_wal(phase: str, **context: object) -> None:
        nonlocal observed
        if phase != "after_readonly_input_open":
            return
        wal = Path(str(context["input_root"])) / "state.sqlite3-wal"
        assert wal.read_bytes() == b""
        assert (
            hashlib.sha256(wal.read_bytes()).hexdigest()
            == hashlib.sha256(b"").hexdigest()
        )
        _assert_guard_blocks_write_truncate_and_replace(wal)
        observed = True

    monkeypatch.setattr(snapshot_impl, "_test_seam", attack_empty_wal)
    with materialize_diagnostic_snapshot(source_root):
        pass

    assert observed
    assert not source_wal.exists()


def test_guarded_empty_wal_sentinel_preserves_committed_main_database_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    source_wal = tmp_path / ".modeling" / "state.sqlite3-wal"
    assert not source_wal.exists()
    saw_guarded_sentinel = False

    def observe_sentinel(phase: str, **context: object) -> None:
        nonlocal saw_guarded_sentinel
        if phase == "after_readonly_input_open":
            sentinel = Path(str(context["input_root"])) / "state.sqlite3-wal"
            assert sentinel.read_bytes() == b""
            saw_guarded_sentinel = True

    monkeypatch.setattr(snapshot_impl, "_test_seam", observe_sentinel)

    with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
        with closing(
            sqlite3.connect(diagnostic.project_root / ".modeling" / "state.sqlite3")
        ) as connection:
            assert connection.execute("SELECT COUNT(*) FROM metadata").fetchone() == (
                4,
            )

    assert saw_guarded_sentinel


@pytest.mark.skipif(os.name != "nt", reason="Windows FILE_SHARE_READ contract")
def test_guarded_empty_shm_sentinel_forces_private_wal_index_and_blocks_raw_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    writer = _start_wal_writer(tmp_path, "private-index")
    seen = False

    def inspect_shm(phase: str, **context: object) -> None:
        nonlocal seen
        if phase != "after_readonly_input_open":
            return
        shm = Path(str(context["input_root"])) / "state.sqlite3-shm"
        before = hashlib.sha256(shm.read_bytes()).hexdigest()
        assert shm.stat().st_size == 0
        _assert_guard_blocks_write_truncate_and_replace(shm)
        assert shm.stat().st_size == 0
        assert hashlib.sha256(shm.read_bytes()).hexdigest() == before
        seen = True

    monkeypatch.setattr(snapshot_impl, "_test_seam", inspect_shm)
    try:
        with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
            with closing(
                sqlite3.connect(diagnostic.project_root / ".modeling" / "state.sqlite3")
            ) as connection:
                assert connection.execute(
                    "SELECT value FROM snapshot_probe"
                ).fetchall() == [("private-index",)]
    finally:
        writer.close()

    assert seen


def test_held_windows_project_lock_is_never_opened_or_hashed_and_snapshot_succeeds(
    tmp_path: Path,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    lock = ProjectLock(
        tmp_path / ".modeling" / "project.lock",
        "00000000-0000-4000-8000-000000000012",
    )
    lock.acquire()
    try:
        with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
            assert (
                diagnostic.project_root / ".modeling" / "project.lock"
            ).read_bytes() == b"\0"
    finally:
        lock.release()


def test_source_project_lock_open_spy_proves_metadata_only_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    source_lock = (tmp_path / ".modeling" / "project.lock").resolve()
    opened: list[Path] = []
    original = snapshot_impl._open_source_handle

    @contextmanager
    def observed(path: Path) -> Iterator[object]:
        resolved = path.resolve()
        opened.append(resolved)
        assert resolved != source_lock
        with original(path) as stream:
            yield stream

    monkeypatch.setattr(snapshot_impl, "_open_source_handle", observed)
    with materialize_diagnostic_snapshot(tmp_path):
        pass

    assert source_lock not in opened
    assert {path.name for path in opened} == {"project.json", "state.sqlite3"}

    def invalidate_lock_metadata(phase: str, **_: object) -> None:
        if phase == "before_manifest_b":
            source_lock.write_bytes(b"x" * 65)

    monkeypatch.setattr(snapshot_impl, "_test_seam", invalidate_lock_metadata)
    assert _snapshot_error(tmp_path).code == "snapshot_unstable"


def test_normalized_backup_publishes_exact_owned_layout_without_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    roots: tuple[Path, Path] | None = None

    def observe_distinct_roots(phase: str, **context: object) -> None:
        nonlocal roots
        if phase == "before_readonly_backup":
            roots = (
                Path(str(context["input_root"])),
                Path(str(context["output_root"])),
            )

    monkeypatch.setattr(snapshot_impl, "_test_seam", observe_distinct_roots)

    with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
        modeling = diagnostic.project_root / ".modeling"
        assert diagnostic.source_state_hint == "INITIALIZED"
        assert {path.name for path in modeling.iterdir()} == EXPECTED_LAYOUT
        assert (modeling / "project.lock").read_bytes() == b"\0"
        with closing(sqlite3.connect(modeling / "state.sqlite3")) as connection:
            assert connection.execute("SELECT COUNT(*) FROM metadata").fetchone() == (
                4,
            )

    assert roots is not None
    assert roots[0] != roots[1]
    assert not roots[0].exists()

    assert not diagnostic.project_root.exists()


def test_read_only_backup_preserves_latest_committed_wal_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    writer = _start_wal_writer(tmp_path, "latest")
    saw_distinct_backup = False

    def observe_backup(phase: str, **context: object) -> None:
        nonlocal saw_distinct_backup
        if phase == "before_readonly_backup":
            input_database = Path(str(context["input_database"]))
            output_database = Path(str(context["output_database"]))
            saw_distinct_backup = input_database != output_database

    monkeypatch.setattr(snapshot_impl, "_test_seam", observe_backup)
    try:
        with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
            with closing(
                sqlite3.connect(diagnostic.project_root / ".modeling" / "state.sqlite3")
            ) as connection:
                assert connection.execute(
                    "SELECT value FROM snapshot_probe"
                ).fetchall() == [("latest",)]
    finally:
        writer.close()

    assert saw_distinct_backup


def test_read_only_backup_leaves_raw_input_database_and_wal_bytes_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    writer = _start_wal_writer(tmp_path, "hash-invariant")
    before: dict[str, tuple[tuple[int, int], int, str]] = {}
    after: dict[str, tuple[tuple[int, int], int, str]] = {}

    def fingerprint(path: Path) -> tuple[tuple[int, int], int, str]:
        return (
            _file_identity(path),
            path.stat().st_size,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def observe_input(phase: str, **context: object) -> None:
        if phase not in {"after_readonly_input_open", "after_readonly_input_close"}:
            return
        input_root = Path(str(context["input_root"]))
        target = before if phase == "after_readonly_input_open" else after
        for name in ("state.sqlite3", "state.sqlite3-wal", "state.sqlite3-shm"):
            target[name] = fingerprint(input_root / name)

    monkeypatch.setattr(snapshot_impl, "_test_seam", observe_input)
    try:
        with materialize_diagnostic_snapshot(tmp_path):
            pass
    finally:
        writer.close()

    assert before
    assert after == before


def test_read_only_backup_preserves_non_default_source_page_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    source_database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(source_database)) as connection:
        assert connection.execute("PRAGMA journal_mode=DELETE").fetchone() == (
            "delete",
        )
        connection.execute("PRAGMA page_size=1024")
        connection.execute("VACUUM")
        assert connection.execute("PRAGMA page_size").fetchone() == (1024,)

    normalized_page_size: int | None = None

    def observe_page_size(phase: str, **context: object) -> None:
        nonlocal normalized_page_size
        if phase == "after_memory_page_validation":
            normalized_page_size = int(context["page_size"])

    monkeypatch.setattr(snapshot_impl, "_test_seam", observe_page_size)

    with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
        with closing(
            sqlite3.connect(diagnostic.project_root / ".modeling" / "state.sqlite3")
        ) as connection:
            assert connection.execute("PRAGMA page_size").fetchone() == (1024,)
            assert connection.execute("SELECT COUNT(*) FROM metadata").fetchone() == (
                4,
            )

    assert normalized_page_size == 1024


def test_owned_peak_limit_is_literal_536936512_bytes() -> None:
    assert snapshot_impl._OWNED_PEAK_LIMIT == 536_936_512
    assert snapshot_impl._OWNED_PEAK_LIMIT == (134_217_728 * 4 + 65_600)


def test_memory_backup_opens_no_output_filesystem_sqlite_or_sidecars(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    opened: list[str] = []
    serialized: list[bytes] = []
    original_connect = snapshot_impl.sqlite3.connect

    class ObservedConnection(sqlite3.Connection):
        def serialize(self, *args: object, **kwargs: object) -> bytes:
            value = super().serialize(*args, **kwargs)
            serialized.append(value)
            return value

    def observed_connect(
        database: object, *args: object, **kwargs: object
    ) -> sqlite3.Connection:
        opened.append(os.fspath(database))
        kwargs["factory"] = ObservedConnection
        return original_connect(database, *args, **kwargs)

    phases: list[str] = []

    def observe(phase: str, **context: object) -> None:
        if phase not in {"before_readonly_backup", "after_fsync"}:
            return
        phases.append(phase)
        output = Path(str(context["output_database"]))
        assert not output.with_name("state.sqlite3-wal").exists()
        assert not output.with_name("state.sqlite3-shm").exists()
        if phase == "before_readonly_backup":
            assert not output.exists()

    monkeypatch.setattr(snapshot_impl.sqlite3, "connect", observed_connect)
    monkeypatch.setattr(snapshot_impl, "_test_seam", observe)

    with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
        output = diagnostic.project_root / ".modeling" / "state.sqlite3"
        output_bytes = output.read_bytes()

    assert len(opened) == 2
    assert opened[0].startswith("file:")
    assert opened[1] == ":memory:"
    assert phases == ["before_readonly_backup", "after_fsync"]
    assert len(serialized) == 1
    assert output_bytes == serialized[0]


def test_serialized_database_length_hash_and_limits_are_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    observed: dict[str, object] = {}

    def observe(phase: str, **context: object) -> None:
        if phase == "after_serialize":
            observed.update(context)

    monkeypatch.setattr(snapshot_impl, "_test_seam", observe)
    with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
        output = diagnostic.project_root / ".modeling" / "state.sqlite3"
        output_bytes = output.read_bytes()

    page_size = int(observed["page_size"])
    page_count = int(observed["page_count"])
    assert len(output_bytes) == page_size * page_count
    assert len(output_bytes) <= 134_217_728
    assert observed["serialized_size"] == len(output_bytes)
    assert observed["serialized_sha256"] == hashlib.sha256(output_bytes).hexdigest()


@pytest.mark.parametrize("attack", ["precreate", "late-drift"])
def test_normalized_output_is_exclusively_created_and_rejects_late_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    attack: str,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())

    def mutate(phase: str, **context: object) -> None:
        if attack == "precreate" and phase == "before_output_create":
            Path(str(context["output_database"])).write_bytes(b"occupied")
        elif attack == "late-drift" and phase == "after_fsync":
            output = Path(str(context["output_database"]))
            data = output.read_bytes()
            output.write_bytes(bytes([data[0] ^ 1]) + data[1:])

    monkeypatch.setattr(snapshot_impl, "_test_seam", mutate)
    assert _snapshot_error(tmp_path).code in {
        "snapshot_invalid" if attack == "precreate" else "snapshot_unstable"
    }


def test_backup_progress_accepts_done_only_and_ok_star_done() -> None:
    for events in (
        [(sqlite3.SQLITE_DONE, 0, 2)],
        [
            (sqlite3.SQLITE_OK, 2, 4),
            (sqlite3.SQLITE_OK, 1, 4),
            (sqlite3.SQLITE_DONE, 0, 4),
        ],
    ):
        progress = snapshot_impl._BackupProgress(
            started_at=snapshot_impl.time.monotonic(),
            check_bounds=lambda: None,
        )
        for event in events:
            progress(*event)
        progress.require_complete()


def test_backup_progress_rejects_duplicate_post_done_and_unknown_status_with_finite_codes() -> (
    None
):
    invalid_sequences = [
        [(sqlite3.SQLITE_DONE, 0, 1), (sqlite3.SQLITE_DONE, 0, 1)],
        [(sqlite3.SQLITE_DONE, 0, 1), (sqlite3.SQLITE_OK, 0, 1)],
        [(0x7FFFFFFF, 1, 1)],
    ]
    for events in invalid_sequences:
        progress = snapshot_impl._BackupProgress(
            started_at=snapshot_impl.time.monotonic(),
            check_bounds=lambda: None,
        )
        with pytest.raises(DiagnosticSnapshotError) as captured:
            for event in events:
                progress(*event)
            progress.require_complete()
        assert captured.value.code == "snapshot_invalid"

    mappings = {
        sqlite3.SQLITE_BUSY: "snapshot_unavailable",
        sqlite3.SQLITE_LOCKED: "snapshot_unavailable",
        sqlite3.SQLITE_CANTOPEN: "snapshot_unavailable",
        sqlite3.SQLITE_IOERR: "snapshot_unavailable",
        sqlite3.SQLITE_PERM: "snapshot_unavailable",
        sqlite3.SQLITE_FULL: "snapshot_resource_limit",
        sqlite3.SQLITE_NOMEM: "snapshot_resource_limit",
        sqlite3.SQLITE_READONLY: "snapshot_invalid",
        sqlite3.SQLITE_NOTADB: "snapshot_invalid",
        sqlite3.SQLITE_CORRUPT: "snapshot_invalid",
        sqlite3.SQLITE_FORMAT: "snapshot_invalid",
    }
    for status, expected in mappings.items():
        progress = snapshot_impl._BackupProgress(
            started_at=snapshot_impl.time.monotonic(),
            check_bounds=lambda: None,
        )
        with pytest.raises(DiagnosticSnapshotError) as captured:
            progress(status, 1, 1)
        assert captured.value.code == expected


def test_uncommitted_wal_tail_is_not_reported_as_committed_state(
    tmp_path: Path,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    writer = _start_wal_writer(tmp_path, "committed")
    wal = tmp_path / ".modeling" / "state.sqlite3-wal"
    try:
        with wal.open("ab") as stream:
            stream.write(b"incomplete-uncommitted-tail")
        with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
            with closing(
                sqlite3.connect(diagnostic.project_root / ".modeling" / "state.sqlite3")
            ) as connection:
                assert connection.execute(
                    "SELECT value FROM snapshot_probe"
                ).fetchall() == [("committed",)]
    finally:
        writer.close()


@pytest.mark.parametrize(
    "member", ["state.sqlite3", "state.sqlite3-wal", "owned:state.sqlite3"]
)
def test_db_or_wal_change_between_manifests_fails_snapshot_unstable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member: str,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    writer = _start_wal_writer(tmp_path) if member.endswith("-wal") else None

    def mutate(phase: str, **context: object) -> None:
        if member.startswith("owned:") and phase == "after_raw_copy":
            target = Path(str(context["staging"])) / member.removeprefix("owned:")
            with target.open("ab") as stream:
                stream.write(b"changed")
        elif not member.startswith("owned:") and phase == "before_manifest_b":
            with (tmp_path / ".modeling" / member).open("ab") as stream:
                stream.write(b"changed")

    monkeypatch.setattr(snapshot_impl, "_test_seam", mutate)
    try:
        assert _snapshot_error(tmp_path).code == "snapshot_unstable"
    finally:
        if writer is not None:
            writer.close()


@pytest.mark.parametrize(
    "member", ["project.json", "state.sqlite3", "state.sqlite3-wal"]
)
def test_same_size_owned_copy_corruption_fails_snapshot_unstable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member: str,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    writer = _start_wal_writer(tmp_path) if member.endswith("-wal") else None

    def corrupt(phase: str, **context: object) -> None:
        if phase != "after_raw_copy":
            return
        target = Path(str(context["staging"])) / member
        data = target.read_bytes()
        target.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))

    monkeypatch.setattr(snapshot_impl, "_test_seam", corrupt)
    try:
        assert _snapshot_error(tmp_path).code == "snapshot_unstable"
    finally:
        if writer is not None:
            writer.close()


@pytest.mark.parametrize(
    "action",
    [
        "appear",
        "disappear",
        "identity-swap",
        "shm-appear",
        "shm-disappear",
        "shm-identity-swap",
    ],
)
def test_wal_appearance_disappearance_or_identity_swap_fails_snapshot_unstable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    wal = tmp_path / ".modeling" / "state.sqlite3-wal"
    shm = tmp_path / ".modeling" / "state.sqlite3-shm"
    if action in {"disappear", "identity-swap"}:
        wal.write_bytes(b"stable-test-wal-member")
    if action in {"shm-disappear", "shm-identity-swap"}:
        shm.write_bytes(b"stable-derived-index")

    def mutate(phase: str, **_: object) -> None:
        if phase != "before_manifest_b":
            return
        if action == "appear":
            wal.write_bytes(b"")
        elif action == "disappear":
            wal.unlink()
        elif action == "identity-swap":
            replacement = wal.with_suffix(".replacement")
            replacement.write_bytes(wal.read_bytes())
            os.replace(replacement, wal)
        elif action == "shm-appear":
            shm.write_bytes(b"new-derived-index")
        elif action == "shm-disappear":
            shm.unlink()
        else:
            replacement = shm.with_suffix(".replacement")
            replacement.write_bytes(shm.read_bytes())
            os.replace(replacement, shm)

    monkeypatch.setattr(snapshot_impl, "_test_seam", mutate)
    assert _snapshot_error(tmp_path).code == "snapshot_unstable"


@pytest.mark.parametrize(
    ("phase", "expected"),
    [
        ("input-open", "snapshot_unavailable"),
        ("input-open-semantic", "snapshot_invalid"),
        ("backup", "snapshot_unavailable"),
        ("backup-semantic", "snapshot_invalid"),
        ("serialize", "snapshot_invalid"),
        ("output-write", "snapshot_unavailable"),
    ],
)
def test_backup_serialize_and_output_write_failures_are_finite_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
    expected: str,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    secret = "SECRET readonly backup failure"
    original_connect = snapshot_impl.sqlite3.connect
    if phase in {"input-open", "input-open-semantic"}:

        def fail_input_open(
            database: object, *args: object, **kwargs: object
        ) -> sqlite3.Connection:
            if kwargs.get("uri"):
                if phase == "input-open-semantic":
                    raise ValueError(secret)
                failure = sqlite3.OperationalError(secret)
                failure.sqlite_errorcode = sqlite3.SQLITE_CANTOPEN  # type: ignore[attr-defined]
                raise failure
            return original_connect(database, *args, **kwargs)

        monkeypatch.setattr(snapshot_impl.sqlite3, "connect", fail_input_open)
    elif phase in {"backup", "backup-semantic", "serialize"}:

        class FailingConnection(sqlite3.Connection):
            def backup(self, *args: object, **kwargs: object) -> None:
                if phase == "backup":
                    failure = sqlite3.OperationalError(secret)
                    failure.sqlite_errorcode = sqlite3.SQLITE_BUSY  # type: ignore[attr-defined]
                    raise failure
                if phase == "backup-semantic":
                    raise ValueError(secret)
                super().backup(*args, **kwargs)  # type: ignore[arg-type]

            def serialize(self, *args: object, **kwargs: object) -> bytes:
                if phase == "serialize":
                    raise ValueError(secret)
                return super().serialize(*args, **kwargs)

        def failing_connect(
            database: object, *args: object, **kwargs: object
        ) -> sqlite3.Connection:
            kwargs["factory"] = FailingConnection
            return original_connect(database, *args, **kwargs)

        monkeypatch.setattr(snapshot_impl.sqlite3, "connect", failing_connect)
    else:
        original_open = Path.open

        class FailingWriter:
            def __init__(self, stream: object) -> None:
                self.stream = stream

            def __enter__(self) -> FailingWriter:
                return self

            def __exit__(self, *args: object) -> None:
                self.stream.close()  # type: ignore[attr-defined]

            def fileno(self) -> int:
                return self.stream.fileno()  # type: ignore[attr-defined,no-any-return]

            def write(self, _: object) -> int:
                raise PermissionError(errno.EACCES, secret)

        def failing_open(
            path: Path, mode: str = "r", *args: object, **kwargs: object
        ) -> object:
            stream = original_open(path, mode, *args, **kwargs)
            if path.name == "state.sqlite3" and mode == "xb":
                return FailingWriter(stream)
            return stream

        monkeypatch.setattr(Path, "open", failing_open)

    error = _snapshot_error(tmp_path)
    assert error.code == expected
    assert secret not in str(error)
    assert secret not in repr(error)


@pytest.mark.parametrize("shape", ["unexpected", "nonregular", "oversize", "reparse"])
def test_snapshot_rejects_reparse_nonregular_unexpected_and_oversize_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    modeling = tmp_path / ".modeling"
    if shape == "unexpected":
        (modeling / "unexpected-secret").write_bytes(b"x")
    elif shape == "nonregular":
        database = modeling / "state.sqlite3"
        database.unlink()
        database.mkdir()
    elif shape == "oversize":
        monkeypatch.setattr(snapshot_impl, "_SOURCE_PROJECT_JSON_LIMIT", 8)
    else:
        target = tmp_path / "unsafe-target"
        modeling.rename(target)
        if os.name == "nt":
            import subprocess

            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(modeling), str(target)],
                capture_output=True,
                check=False,
                text=True,
            )
            assert completed.returncode == 0, completed.stderr or completed.stdout
        else:
            modeling.symlink_to(target, target_is_directory=True)

    assert _snapshot_error(tmp_path).code in {
        "snapshot_invalid",
        "snapshot_resource_limit",
    }


def test_snapshot_expected_errors_are_typed_finite_read_only_and_redacted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = {
        "snapshot_unstable": "snapshot changed during capture",
        "snapshot_invalid": "snapshot input is invalid",
        "snapshot_resource_limit": "snapshot resource limit exceeded",
        "snapshot_unavailable": "snapshot is unavailable",
        "snapshot_cleanup_failed": "snapshot cleanup failed",
    }
    for code, message in expected.items():
        error = DiagnosticSnapshotError(code)
        assert error.code == code
        assert str(error) == message
        assert error.args == (message,)
        assert "SECRET" not in repr(error)
        with pytest.raises(AttributeError):
            error.code = "snapshot_invalid"  # type: ignore[misc]
    with pytest.raises(ValueError):
        DiagnosticSnapshotError("unknown")  # type: ignore[arg-type]

    bootstrap_storage(tmp_path, VersionSet.m1a())

    @contextmanager
    def permission_denied(path: Path) -> Iterator[object]:
        del path
        raise PermissionError(errno.EACCES, "SECRET source credential path")
        yield  # pragma: no cover

    monkeypatch.setattr(snapshot_impl, "_open_source_handle", permission_denied)
    unavailable = _snapshot_error(tmp_path)
    assert unavailable.code == "snapshot_unavailable"
    assert str(unavailable) == "snapshot is unavailable"
    assert "SECRET" not in repr(unavailable)
    assert str(tmp_path) not in repr(unavailable)


@pytest.mark.parametrize(
    "failure",
    [
        "input-wal",
        "source-database",
        "total-copy",
        "memory",
        "serialized",
        "final",
    ],
)
def test_input_wal_and_memory_serialized_final_bounds_fail_resource_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    writer = _start_wal_writer(tmp_path) if failure == "input-wal" else None
    limit_names = {
        "input-wal": "_SOURCE_WAL_LIMIT",
        "source-database": "_SOURCE_DATABASE_LIMIT",
        "total-copy": "_TOTAL_COPY_LIMIT",
        "memory": "_OWNED_MAIN_LIMIT",
    }
    if failure in limit_names:
        monkeypatch.setattr(snapshot_impl, limit_names[failure], 1)
    elif failure == "serialized":
        original_connect = snapshot_impl.sqlite3.connect

        class MemoryFailingConnection(sqlite3.Connection):
            def serialize(self, *args: object, **kwargs: object) -> bytes:
                del args, kwargs
                raise MemoryError("SECRET serialized limit")

        def memory_failing_connect(
            database: object, *args: object, **kwargs: object
        ) -> sqlite3.Connection:
            kwargs["factory"] = MemoryFailingConnection
            return original_connect(database, *args, **kwargs)

        monkeypatch.setattr(snapshot_impl.sqlite3, "connect", memory_failing_connect)
    else:
        original_open = Path.open

        class FullWriter:
            def __init__(self, stream: object) -> None:
                self.stream = stream

            def __enter__(self) -> FullWriter:
                return self

            def __exit__(self, *args: object) -> None:
                self.stream.close()  # type: ignore[attr-defined]

            def fileno(self) -> int:
                return self.stream.fileno()  # type: ignore[attr-defined,no-any-return]

            def write(self, _: object) -> int:
                raise OSError(errno.ENOSPC, "SECRET final limit")

        def full_open(
            path: Path, mode: str = "r", *args: object, **kwargs: object
        ) -> object:
            stream = original_open(path, mode, *args, **kwargs)
            if path.name == "state.sqlite3" and mode == "xb":
                return FullWriter(stream)
            return stream

        monkeypatch.setattr(Path, "open", full_open)
    try:
        assert _snapshot_error(tmp_path).code == "snapshot_resource_limit"
    finally:
        if writer is not None:
            writer.close()


@pytest.mark.parametrize("failure", ["peak", "enospc", "sqlite-full"])
def test_owned_peak_tree_and_enospc_fail_resource_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    if failure == "peak":
        monkeypatch.setattr(snapshot_impl, "_OWNED_PEAK_LIMIT", 1)
    elif failure == "enospc":
        original = snapshot_impl._copy_persistent_member

        def no_space(*args: object, **kwargs: object) -> object:
            del args, kwargs
            raise OSError(errno.ENOSPC, "SECRET device is full")

        monkeypatch.setattr(snapshot_impl, "_copy_persistent_member", no_space)
        assert original is not None
    else:
        full = sqlite3.OperationalError("SECRET SQLite full")
        full.sqlite_errorcode = sqlite3.SQLITE_FULL  # type: ignore[attr-defined]

        def sqlite_full(*args: object, **kwargs: object) -> object:
            del args, kwargs
            raise full

        monkeypatch.setattr(snapshot_impl.sqlite3, "connect", sqlite_full)
    error = _snapshot_error(tmp_path)
    assert error.code == "snapshot_resource_limit"
    assert "SECRET" not in str(error)


def test_cooperative_deadline_checks_after_blocking_phases_fail_resource_limit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    clock = [0.0]
    original_connect = snapshot_impl.sqlite3.connect

    def delayed_connect(
        database: object, *args: object, **kwargs: object
    ) -> sqlite3.Connection:
        connection = original_connect(database, *args, **kwargs)
        if os.fspath(database) == ":memory:":
            clock[0] = 11.0
        return connection

    monkeypatch.setattr(snapshot_impl.sqlite3, "connect", delayed_connect)
    monkeypatch.setattr(snapshot_impl.time, "monotonic", lambda: clock[0])

    assert _snapshot_error(tmp_path).code == "snapshot_resource_limit"

    uninitialized = tmp_path / "uninitialized"
    uninitialized.mkdir()
    clock[0] = 0.0
    original_mkdtemp = snapshot_impl.tempfile.mkdtemp

    def slow_mkdtemp(*args: object, **kwargs: object) -> str:
        created = original_mkdtemp(*args, **kwargs)
        clock[0] = 11.0
        return created

    with monkeypatch.context() as isolated:
        isolated.setattr(snapshot_impl.time, "monotonic", lambda: clock[0])
        isolated.setattr(snapshot_impl.tempfile, "mkdtemp", slow_mkdtemp)
        assert _snapshot_error(uninitialized).code == "snapshot_resource_limit"


def test_snapshot_failure_closes_handles_and_cleanup_failure_uses_typed_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    owned: list[Path] = []
    original_cleanup = snapshot_impl._cleanup_owned_root

    def remove_then_fail(
        path: Path,
        expected_identity: tuple[int, int],
        expected_children: dict[str, tuple[int, int]],
    ) -> None:
        owned.append(path)
        original_cleanup(path, expected_identity, expected_children)
        raise OSError("SECRET cleanup path")

    monkeypatch.setattr(snapshot_impl, "_cleanup_owned_root", remove_then_fail)
    error = _snapshot_error(tmp_path)
    assert error.code == "snapshot_cleanup_failed"
    assert "SECRET" not in str(error)
    assert owned and all(not path.exists() for path in owned)

    def primary_failure(phase: str, **_: object) -> None:
        if phase == "before_consolidation":
            raise DiagnosticSnapshotError("snapshot_invalid")

    monkeypatch.setattr(snapshot_impl, "_test_seam", primary_failure)
    assert _snapshot_error(tmp_path).code == "snapshot_cleanup_failed"


def test_cleanup_refuses_same_name_replacement_after_owned_root_is_renamed(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "uninitialized"
    source_root.mkdir()
    owned_root: Path | None = None
    moved_root: Path | None = None
    replacement_marker: Path | None = None

    try:
        with pytest.raises(DiagnosticSnapshotError) as captured:
            with materialize_diagnostic_snapshot(source_root) as diagnostic:
                owned_root = diagnostic.project_root
                moved_root = owned_root.with_name(f"{owned_root.name}-moved")
                owned_root.rename(moved_root)
                owned_root.mkdir()
                replacement_marker = owned_root / "must-survive.txt"
                replacement_marker.write_bytes(b"replacement-not-owned")

        assert captured.value.code == "snapshot_cleanup_failed"
        assert replacement_marker is not None
        assert replacement_marker.read_bytes() == b"replacement-not-owned"
    finally:
        for candidate in (owned_root, moved_root):
            if candidate is not None and candidate.exists():
                shutil.rmtree(candidate)


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-bound cleanup contract")
def test_cleanup_guard_blocks_swap_after_identity_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "uninitialized"
    source_root.mkdir()
    owned_root: Path | None = None
    moved_root: Path | None = None
    attacked = False
    blocked = False

    def attack_after_validation(phase: str, **context: object) -> None:
        nonlocal attacked, blocked, moved_root
        if phase != "after_cleanup_validation":
            return
        attacked = True
        target = Path(str(context["owned_root"]))
        moved_root = target.with_name(f"{target.name}-race")
        try:
            target.rename(moved_root)
        except PermissionError:
            blocked = True

    monkeypatch.setattr(snapshot_impl, "_test_seam", attack_after_validation)
    with materialize_diagnostic_snapshot(source_root) as diagnostic:
        owned_root = diagnostic.project_root

    assert attacked
    assert blocked
    assert owned_root is not None
    assert not owned_root.exists()
    assert moved_root is not None
    assert not moved_root.exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-bound cleanup contract")
def test_cleanup_rejects_child_swap_without_deleting_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    bootstrap_storage(source_root, VersionSet.m1a())
    external = tmp_path / "external"
    external.mkdir()
    marker = external / "must-survive.txt"
    marker.write_bytes(b"not-owned")
    displaced: Path | None = None
    replacement: Path | None = None
    attacked_root: Path | None = None
    blocked = False

    def swap_child(phase: str, **context: object) -> None:
        nonlocal attacked_root, blocked, displaced, replacement
        if phase != "after_cleanup_validation":
            return
        owned_root = Path(str(context["owned_root"]))
        attacked_root = owned_root
        child = owned_root / ".modeling"
        displaced = owned_root.parent / f"{owned_root.name}-owned-child"
        try:
            child.rename(displaced)
        except PermissionError:
            blocked = True
            raise
        external.rename(child)
        replacement = child

    monkeypatch.setattr(snapshot_impl, "_test_seam", swap_child)
    with pytest.raises(DiagnosticSnapshotError) as captured:
        with materialize_diagnostic_snapshot(source_root):
            pass

    assert captured.value.code == "snapshot_cleanup_failed"
    if blocked:
        assert external.joinpath("must-survive.txt").read_bytes() == b"not-owned"
    else:
        assert replacement is not None
        assert (replacement / "must-survive.txt").read_bytes() == b"not-owned"
    for candidate in (attacked_root, displaced):
        if candidate is not None and candidate.exists():
            shutil.rmtree(candidate)


@pytest.mark.skipif(os.name != "nt", reason="Windows handle-bound cleanup contract")
def test_cleanup_blocks_descendant_file_swap_and_preserves_external_sentinel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    bootstrap_storage(source_root, VersionSet.m1a())
    external = tmp_path / "external.json"
    external.write_bytes(b"external-must-survive")
    blocked = False
    attacked_root: Path | None = None
    replacement: Path | None = None

    def swap_file(phase: str, **context: object) -> None:
        nonlocal attacked_root, blocked, replacement
        if phase != "after_cleanup_validation":
            return
        attacked_root = Path(str(context["owned_root"]))
        target = attacked_root / ".modeling" / "project.json"
        try:
            os.replace(external, target)
        except PermissionError:
            blocked = True
            raise
        replacement = target

    monkeypatch.setattr(snapshot_impl, "_test_seam", swap_file)
    with pytest.raises(DiagnosticSnapshotError) as captured:
        with materialize_diagnostic_snapshot(source_root):
            pass

    assert captured.value.code == "snapshot_cleanup_failed"
    if blocked:
        assert external.read_bytes() == b"external-must-survive"
    else:
        assert replacement is not None
        assert replacement.read_bytes() == b"external-must-survive"
    if attacked_root is not None and attacked_root.exists():
        shutil.rmtree(attacked_root)


def test_non_windows_public_snapshot_fails_before_owned_temp_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_root = tmp_path / "uninitialized"
    source_root.mkdir()
    created = 0
    original_mkdtemp = snapshot_impl.tempfile.mkdtemp

    def observed_mkdtemp(*args: object, **kwargs: object) -> str:
        nonlocal created
        created += 1
        return original_mkdtemp(*args, **kwargs)

    monkeypatch.setattr(
        snapshot_impl,
        "_supports_handle_bound_snapshot",
        lambda: False,
    )
    monkeypatch.setattr(snapshot_impl.tempfile, "mkdtemp", observed_mkdtemp)

    error = _snapshot_error(source_root)

    assert error.code == "snapshot_unavailable"
    assert created == 0


def test_idle_source_bytes_and_members_remain_exactly_unchanged(tmp_path: Path) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    before = _file_bytes(tmp_path / ".modeling")

    with materialize_diagnostic_snapshot(tmp_path):
        pass

    assert _file_bytes(tmp_path / ".modeling") == before


def test_active_writer_uses_stable_db_wal_or_finite_failure_without_shm_hash_equality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    writer = _start_wal_writer(tmp_path, "active")
    database = tmp_path / ".modeling" / "state.sqlite3"
    wal = database.with_name("state.sqlite3-wal")
    before = {
        "db": hashlib.sha256(database.read_bytes()).hexdigest(),
        "wal": hashlib.sha256(wal.read_bytes()).hexdigest(),
    }
    opened: list[str] = []
    original_open = snapshot_impl._open_source_handle

    @contextmanager
    def observed_open(path: Path) -> Iterator[object]:
        opened.append(path.name)
        with original_open(path) as stream:
            yield stream

    monkeypatch.setattr(snapshot_impl, "_open_source_handle", observed_open)
    try:
        try:
            with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
                with closing(
                    sqlite3.connect(
                        diagnostic.project_root / ".modeling" / "state.sqlite3"
                    )
                ) as connection:
                    assert connection.execute(
                        "SELECT value FROM snapshot_probe"
                    ).fetchall() == [("active",)]
        except DiagnosticSnapshotError as error:
            assert error.code in {"snapshot_unstable", "snapshot_unavailable"}
        assert hashlib.sha256(database.read_bytes()).hexdigest() == before["db"]
        assert hashlib.sha256(wal.read_bytes()).hexdigest() == before["wal"]
        assert "state.sqlite3-shm" not in opened
        assert "project.lock" not in opened
    finally:
        writer.close()


def test_read_only_backup_sql_is_limited_to_input_and_memory_output_allowlists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    statements: dict[str, list[str]] = {"input": [], "output": []}
    original_connect = snapshot_impl.sqlite3.connect

    def traced_connect(
        database: object, *args: object, **kwargs: object
    ) -> sqlite3.Connection:
        connection = original_connect(database, *args, **kwargs)
        label = "input" if kwargs.get("uri") else "output"
        connection.set_trace_callback(statements[label].append)
        return connection

    monkeypatch.setattr(snapshot_impl.sqlite3, "connect", traced_connect)
    with materialize_diagnostic_snapshot(tmp_path):
        pass

    assert [item.lower() for item in statements["input"]] == [
        "pragma query_only=on",
        "pragma query_only",
    ]
    output = [item.lower().replace('"main".', "") for item in statements["output"]]
    assert output[:2] == [
        "pragma page_size",
        "pragma page_count",
    ]
    assert set(output) == {"pragma page_size", "pragma page_count"}

    normalized = "\n".join(statements["input"] + statements["output"]).lower()
    for forbidden in (
        "quick_check",
        "integrity_check",
        "foreign_key_check",
        "attempts",
        "validations",
        "idempotency_records",
    ):
        assert forbidden not in normalized


def test_preserved_foreign_key_violation_reaches_store_foreign_key_report(
    tmp_path: Path,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    database = tmp_path / ".modeling" / "state.sqlite3"
    writer = sqlite3.connect(database)
    writer.execute("PRAGMA foreign_keys=OFF")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE snapshot_parent(id INTEGER PRIMARY KEY)")
    writer.execute(
        "CREATE TABLE snapshot_child(parent_id INTEGER REFERENCES snapshot_parent(id))"
    )
    writer.execute("INSERT INTO snapshot_child(parent_id) VALUES (99)")
    writer.commit()
    try:
        with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
            report = SQLiteProjectStore(
                diagnostic.project_root, VersionSet.m1a()
            ).inspect_integrity(deep=False)
            assert "foreign_key" in report.issues
    finally:
        writer.close()


def test_preserved_non_ok_integrity_reaches_store_check_failed(
    tmp_path: Path,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    database = tmp_path / ".modeling" / "state.sqlite3"
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE integrity_probe(value TEXT NOT NULL)")
        writer.execute("INSERT INTO integrity_probe(value) VALUES ('probe')")
        writer.commit()
        metadata_root = writer.execute(
            "SELECT rootpage FROM sqlite_schema WHERE type='table' AND name='metadata'"
        ).fetchone()[0]
        probe_root = writer.execute(
            "SELECT rootpage FROM sqlite_schema "
            "WHERE type='table' AND name='integrity_probe'"
        ).fetchone()[0]
        assert metadata_root > 0
        assert probe_root > 0
        assert metadata_root != probe_root
        writer.execute("PRAGMA writable_schema=ON")
        writer.execute(
            "UPDATE sqlite_schema SET rootpage=? "
            "WHERE type='table' AND name='integrity_probe'",
            (metadata_root,),
        )
        writer.commit()
        writer.execute("PRAGMA writable_schema=OFF")
        assert database.with_name("state.sqlite3-wal").stat().st_size > 0

        with materialize_diagnostic_snapshot(tmp_path) as diagnostic:
            store = SQLiteProjectStore(diagnostic.project_root, VersionSet.m1a())
            report = store.inspect_integrity(deep=True)
    finally:
        writer.close()

    assert report.check is not None
    assert report.check.mode == "integrity"
    assert report.check.outcome == "FAIL"
    assert "sqlite_integrity_check" in report.issues


def test_doctor_binds_composition_only_to_owned_snapshot_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modeling_cli import doctor

    bootstrap_storage(tmp_path, VersionSet.m1a())
    source_root = tmp_path.resolve()
    built_roots: list[Path] = []
    original_build = doctor.build_composition

    def observed_build(root: Path) -> object:
        assert root.resolve() != source_root
        built_roots.append(root.resolve())
        return original_build(root)

    monkeypatch.setattr(doctor, "build_composition", observed_build)
    stdout = io.StringIO()

    assert doctor.run_doctor(tmp_path, False, True, stdout=stdout) == 0
    assert json.loads(stdout.getvalue())["status"] == "READY"
    assert len(built_roots) == 1
    assert not built_roots[0].exists()


def test_doctor_cleans_base_snapshot_and_deep_smoke_roots_on_every_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modeling_cli import doctor

    bootstrap_storage(tmp_path, VersionSet.m1a())
    observed: list[Path] = []
    original_snapshot = doctor.materialize_diagnostic_snapshot
    original_deep = doctor._run_deep_smoke

    @contextmanager
    def observed_snapshot(root: Path) -> Iterator[object]:
        with original_snapshot(root) as snapshot:
            observed.append(snapshot.project_root)
            yield snapshot

    def observed_deep() -> object:
        return original_deep(observed_roots=observed)

    monkeypatch.setattr(doctor, "materialize_diagnostic_snapshot", observed_snapshot)
    monkeypatch.setattr(doctor, "_run_deep_smoke", observed_deep)
    stdout = io.StringIO()

    assert doctor.run_doctor(tmp_path, True, True, stdout=stdout) == 0
    assert len(observed) == 2
    assert all(not root.exists() for root in observed)


def test_real_foreign_key_violation_maps_to_doctor_foreign_key_failure(
    tmp_path: Path,
) -> None:
    from modeling_cli.doctor import run_doctor

    bootstrap_storage(tmp_path, VersionSet.m1a())
    database = tmp_path / ".modeling" / "state.sqlite3"
    writer = sqlite3.connect(database)
    writer.execute("PRAGMA foreign_keys=OFF")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE doctor_parent(id INTEGER PRIMARY KEY)")
    writer.execute(
        "CREATE TABLE doctor_child(parent_id INTEGER REFERENCES doctor_parent(id))"
    )
    writer.execute("INSERT INTO doctor_child(parent_id) VALUES (99)")
    writer.commit()
    try:
        stdout = io.StringIO()
        assert run_doctor(tmp_path, False, True, stdout=stdout) == 2
    finally:
        writer.close()

    report = json.loads(stdout.getvalue())
    checks = {item["name"]: item for item in report["checks"]}
    assert checks["foreign-keys"] == {
        "name": "foreign-keys",
        "status": "FAIL",
        "code": "foreign_key_failure",
    }


def test_preserved_non_ok_integrity_maps_to_doctor_check_failed(
    tmp_path: Path,
) -> None:
    from modeling_cli.doctor import run_doctor

    bootstrap_storage(tmp_path, VersionSet.m1a())
    database = tmp_path / ".modeling" / "state.sqlite3"
    writer = sqlite3.connect(database)
    try:
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("CREATE TABLE doctor_integrity_probe(value TEXT NOT NULL)")
        writer.execute("INSERT INTO doctor_integrity_probe(value) VALUES ('probe')")
        writer.commit()
        metadata_root = writer.execute(
            "SELECT rootpage FROM sqlite_schema WHERE type='table' AND name='metadata'"
        ).fetchone()[0]
        writer.execute("PRAGMA writable_schema=ON")
        writer.execute(
            "UPDATE sqlite_schema SET rootpage=? "
            "WHERE type='table' AND name='doctor_integrity_probe'",
            (metadata_root,),
        )
        writer.commit()
        writer.execute("PRAGMA writable_schema=OFF")
        stdout = io.StringIO()
        assert run_doctor(tmp_path, True, True, stdout=stdout) == 2
    finally:
        writer.close()

    checks = {item["name"]: item for item in json.loads(stdout.getvalue())["checks"]}
    assert checks["storage-integrity"] == {
        "name": "storage-integrity",
        "status": "FAIL",
        "code": "check_failed",
    }


def test_full_doctor_idle_source_bytes_and_members_are_unchanged(
    tmp_path: Path,
) -> None:
    from modeling_cli.doctor import run_doctor

    bootstrap_storage(tmp_path, VersionSet.m1a())
    before = _file_bytes(tmp_path)
    members = sorted(
        path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*")
    )
    stdout = io.StringIO()

    assert run_doctor(tmp_path, True, True, stdout=stdout) == 0
    assert json.loads(stdout.getvalue())["status"] == "READY"
    assert _file_bytes(tmp_path) == before
    assert (
        sorted(path.relative_to(tmp_path).as_posix() for path in tmp_path.rglob("*"))
        == members
    )


def test_full_doctor_active_writer_is_verified_or_finite_without_shm_hash_assertion(
    tmp_path: Path,
) -> None:
    from modeling_cli.doctor import run_doctor

    bootstrap_storage(tmp_path, VersionSet.m1a())
    writer = _start_wal_writer(tmp_path, "doctor-active")
    try:
        stdout = io.StringIO()
        exit_code = run_doctor(tmp_path, False, True, stdout=stdout)
    finally:
        writer.close()

    report = json.loads(stdout.getvalue())
    if exit_code == 0:
        assert report["status"] == "READY"
    else:
        assert exit_code == 2
        assert report["status"] == "UNSAFE"
        storage = next(
            item for item in report["checks"] if item["name"] == "storage-integrity"
        )
        assert storage["code"] in {
            "snapshot_unstable",
            "snapshot_unavailable",
        }
