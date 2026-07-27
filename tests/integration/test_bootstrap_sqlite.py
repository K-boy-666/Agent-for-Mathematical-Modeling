from __future__ import annotations

import errno
import json
import os
import shutil
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path
from typing import NoReturn

import pytest

from modeling_core.contracts.versions import VersionSet
from modeling_core.domain.states import ProjectState
from modeling_infrastructure.project_lock import ProjectLock, StorageConflict
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import StorageError, bootstrap_storage


EXPECTED_LAYOUT = {"project.json", "state.sqlite3", "project.lock"}
SESSION_ONE = "00000000-0000-4000-8000-000000000001"
SESSION_TWO = "00000000-0000-4000-8000-000000000002"


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _assert_no_temporary_storage(root: Path) -> None:
    assert list(root.glob(".modeling.tmp.*")) == []


def test_uninitialized_bootstrap_creates_exact_storage_ready_layout(
    tmp_path: Path,
) -> None:
    keep = tmp_path / "notes.txt"
    keep.write_bytes(b"leave me unchanged")

    metadata = bootstrap_storage(tmp_path, VersionSet.m1a())

    modeling = tmp_path / ".modeling"
    assert metadata.project_state is ProjectState.STORAGE_READY
    assert metadata.created is True
    assert {path.name for path in modeling.iterdir()} == EXPECTED_LAYOUT
    assert keep.read_bytes() == b"leave me unchanged"
    _assert_no_temporary_storage(tmp_path)

    project_metadata = json.loads(
        (modeling / "project.json").read_text(encoding="utf-8")
    )
    assert project_metadata == {
        "canonicalization_version": "canonical-json/0.1.0",
        "project_format_version": "modeling-project/0.1.0",
        "storage_instance_id": metadata.storage_instance_id,
    }
    assert str(tmp_path.resolve()) not in (modeling / "project.json").read_text(
        encoding="utf-8"
    )


def test_repeat_bootstrap_returns_same_id_without_changing_any_bytes(
    tmp_path: Path,
) -> None:
    first = bootstrap_storage(tmp_path, VersionSet.m1a())
    before = _snapshot(tmp_path)

    second = bootstrap_storage(tmp_path, VersionSet.m1a())

    assert second.storage_instance_id == first.storage_instance_id
    assert second.created is False
    assert _snapshot(tmp_path) == before
    assert {path.name for path in (tmp_path / ".modeling").iterdir()} == EXPECTED_LAYOUT


def test_sqlite_pragmas_are_verified_and_wal_sidecars_are_closed(
    tmp_path: Path,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    database = tmp_path / ".modeling" / "state.sqlite3"
    store = SQLiteProjectStore(tmp_path, VersionSet.m1a())

    with closing(store._connect()) as connection:
        assert connection.execute("PRAGMA foreign_keys").fetchone() == (1,)
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("PRAGMA synchronous").fetchone() == (2,)
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (250,)
        assert connection.execute("PRAGMA user_version").fetchone() == (1,)

    assert {path.name for path in database.parent.iterdir()} == EXPECTED_LAYOUT


def test_higher_database_version_fails_closed_without_overwrite(tmp_path: Path) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA user_version=2")
        connection.commit()
    before = _snapshot(tmp_path)

    with pytest.raises(StorageError) as captured:
        bootstrap_storage(tmp_path, VersionSet.m1a())

    assert captured.value.code == "UNSUPPORTED_VERSION"
    assert _snapshot(tmp_path) == before


def test_mismatched_project_metadata_fails_closed_without_overwrite(
    tmp_path: Path,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    project_json = tmp_path / ".modeling" / "project.json"
    metadata = json.loads(project_json.read_text(encoding="utf-8"))
    metadata["canonicalization_version"] = "canonical-json/9.9.9"
    project_json.write_text(
        json.dumps(metadata, separators=(",", ":"), sort_keys=True),
        encoding="utf-8",
    )
    before = _snapshot(tmp_path)

    with pytest.raises(StorageError) as captured:
        bootstrap_storage(tmp_path, VersionSet.m1a())

    assert captured.value.code == "INTEGRITY_FAILURE"
    assert _snapshot(tmp_path) == before


def test_modeling_reparse_point_is_rejected_without_touching_its_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    marker = target / "marker.txt"
    marker.write_bytes(b"external")
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
    assert marker.read_bytes() == b"external"


def test_project_root_under_reparse_ancestor_is_rejected_before_target_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "target"
    project = target / "project"
    project.mkdir(parents=True)
    marker = project / "marker.bin"
    marker.write_bytes(b"target-must-remain-untouched")
    ancestor = tmp_path / "ancestor"

    if os.name == "nt":
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(ancestor), str(target)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
    else:
        ancestor.symlink_to(target, target_is_directory=True)

    monkeypatch.chdir(tmp_path)
    with pytest.raises(StorageError) as captured:
        bootstrap_storage(Path("ancestor") / "project", VersionSet.m1a())

    assert captured.value.code == "SECURITY_VIOLATION"
    assert captured.value.details == {"rule": "unsafe_reparse_point"}
    assert marker.read_bytes() == b"target-must-remain-untouched"
    assert not (project / ".modeling").exists()


def test_project_lock_is_nonblocking_and_release_closes_the_handle(
    tmp_path: Path,
) -> None:
    lock_path = tmp_path / "project.lock"
    first = ProjectLock(lock_path, SESSION_ONE)
    second = ProjectLock(lock_path, SESSION_TWO)

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
    lock_path.rename(tmp_path / "released.lock")


@pytest.mark.parametrize(
    "race_error",
    [
        FileExistsError(errno.EEXIST, "destination won"),
        PermissionError(errno.EACCES, "destination won"),
    ],
)
def test_atomic_publish_race_uses_complete_winner_and_removes_loser(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    race_error: OSError,
) -> None:
    from modeling_infrastructure import storage

    original_rename = storage.os.rename

    def publish_winner_then_lose(source: str | bytes, destination: str | bytes) -> NoReturn:
        source_path = Path(source)
        destination_path = Path(destination)
        shutil.copytree(source_path, destination_path)
        raise race_error

    monkeypatch.setattr(storage.os, "rename", publish_winner_then_lose)

    metadata = bootstrap_storage(tmp_path, VersionSet.m1a())

    monkeypatch.setattr(storage.os, "rename", original_rename)
    assert metadata.created is False
    assert {path.name for path in (tmp_path / ".modeling").iterdir()} == EXPECTED_LAYOUT
    _assert_no_temporary_storage(tmp_path)


def test_atomic_publish_failure_without_winner_leaves_no_partial_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modeling_infrastructure import storage

    def deny_publish(source: str | bytes, destination: str | bytes) -> NoReturn:
        raise PermissionError(errno.EACCES, "sharing violation")

    monkeypatch.setattr(storage.os, "rename", deny_publish)

    with pytest.raises(StorageError) as captured:
        bootstrap_storage(tmp_path, VersionSet.m1a())

    assert captured.value.code == "CONFLICT"
    assert not (tmp_path / ".modeling").exists()
    _assert_no_temporary_storage(tmp_path)
