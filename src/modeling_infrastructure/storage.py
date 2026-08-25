"""Atomic project-storage bootstrap for SQLite schema 1 and 2."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from modeling_core.contracts.versions import VersionSet
from modeling_core.domain.states import ProjectState

from modeling_infrastructure.project_paths import ProjectPaths


_LAYOUT_V1 = frozenset({"project.json", "state.sqlite3", "project.lock"})
_LAYOUT_V2 = frozenset(
    {"project.json", "state.sqlite3", "project.lock", "staging", "artifacts"}
)
_PROJECT_KEYS = frozenset(
    {
        "project_format_version",
        "canonicalization_version",
        "storage_instance_id",
    }
)
_MAX_VERSION_COMPONENT_DIGITS = 64


class StorageError(RuntimeError):
    """Stable infrastructure failure information for the application boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.details = details or {}


@dataclass(frozen=True)
class StorageMetadata:
    """Verified metadata returned by storage bootstrap."""

    project_state: ProjectState
    storage_instance_id: str
    project_format_version: str
    canonicalization_version: str
    database_schema_version: int
    created: bool


def _fail_security(message: str) -> NoReturn:
    raise StorageError(
        "SECURITY_VIOLATION",
        message,
        details={"rule": "unsafe_reparse_point"},
    )


def _bind_paths(project_root: Path) -> ProjectPaths:
    try:
        return ProjectPaths.bind(project_root)
    except (FileNotFoundError, NotADirectoryError) as error:
        raise StorageError(
            "SECURITY_VIOLATION",
            "project root cannot be safely bound",
            details={"rule": "path_outside_project"},
        ) from error
    except ValueError as error:
        _fail_security(str(error))


def _is_uuid4(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return False
    return parsed.version == 4 and str(parsed) == value


def _is_higher_project_format_version(requested: str, supported: str) -> bool:
    requested_family, requested_separator, requested_number = requested.partition("/")
    supported_family, supported_separator, supported_number = supported.partition("/")
    if (
        requested_separator != "/"
        or supported_separator != "/"
        or requested_family != supported_family
    ):
        return False
    requested_parts = requested_number.split(".")
    supported_parts = supported_number.split(".")
    if (
        len(requested_parts) != 3
        or len(supported_parts) != 3
        or not all(part.isascii() and part.isdecimal() for part in requested_parts)
        or not all(part.isascii() and part.isdecimal() for part in supported_parts)
        or any(
            len(part) > _MAX_VERSION_COMPONENT_DIGITS
            or (len(part) > 1 and part.startswith("0"))
            for part in requested_parts + supported_parts
        )
    ):
        return False
    requested_key = tuple((len(part), part) for part in requested_parts)
    supported_key = tuple((len(part), part) for part in supported_parts)
    return requested_key > supported_key


def _project_bytes(versions: VersionSet, storage_instance_id: str) -> bytes:
    payload = {
        "canonicalization_version": versions.canonicalization_version,
        "project_format_version": versions.project_format_version,
        "storage_instance_id": storage_instance_id,
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _configure_connection(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("PRAGMA synchronous=FULL")
    connection.execute("PRAGMA busy_timeout=250")


def _create_database(
    database: Path, versions: VersionSet, storage_instance_id: str
) -> None:
    schema_name = (
        "schema_v2.sql" if versions.database_schema_version == 2 else "schema_v1.sql"
    )
    schema_path = Path(__file__).with_name("sqlite") / schema_name
    schema = schema_path.read_text(encoding="utf-8")
    connection = sqlite3.connect(database, timeout=0.25)
    try:
        _configure_connection(connection)
        journal_mode = connection.execute("PRAGMA journal_mode=WAL").fetchone()
        if journal_mode != ("wal",):
            raise StorageError(
                "INTEGRITY_FAILURE",
                "SQLite did not enable WAL",
                details={"subject": "project_metadata"},
            )
        connection.executescript(schema)
        metadata = (
            ("project_format_version", versions.project_format_version),
            ("canonicalization_version", versions.canonicalization_version),
            ("storage_instance_id", storage_instance_id),
            ("database_schema_version", str(versions.database_schema_version)),
        )
        connection.executemany(
            "INSERT INTO metadata(key, value) VALUES (?, ?)",
            metadata,
        )
        connection.execute(f"PRAGMA user_version={versions.database_schema_version}")
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    finally:
        connection.close()


def _fsync_file(path: Path) -> None:
    with path.open("r+b") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _remove_temporary(path: Path, root: Path) -> None:
    if path.parent != root or not path.name.startswith(".modeling.tmp."):
        raise RuntimeError("refusing to remove an unbound temporary path")
    if path.exists():
        shutil.rmtree(path)


def _read_project_json(path: Path) -> dict[str, str]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise StorageError(
            "INTEGRITY_FAILURE",
            "project metadata is unreadable",
            details={"subject": "project_metadata"},
        ) from error
    if not isinstance(value, dict) or frozenset(value) != _PROJECT_KEYS:
        raise StorageError(
            "INTEGRITY_FAILURE",
            "project metadata has an unexpected shape",
            details={"subject": "project_metadata"},
        )
    if not all(isinstance(item, str) for item in value.values()):
        raise StorageError(
            "INTEGRITY_FAILURE",
            "project metadata values must be strings",
            details={"subject": "project_metadata"},
        )
    return value


def _read_database_metadata(
    database: Path, versions: VersionSet
) -> tuple[int, dict[str, str]]:
    try:
        connection = sqlite3.connect(database, timeout=0.25)
        try:
            _configure_connection(connection)
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]
            if user_version > versions.database_schema_version:
                raise StorageError(
                    "UNSUPPORTED_VERSION",
                    "database schema is newer than this application",
                    details={
                        "subject": "database_schema",
                        "requested_version": str(user_version),
                        "supported_versions": [str(versions.database_schema_version)],
                    },
                )
            if user_version < versions.database_schema_version:
                raise StorageError(
                    "UNSUPPORTED_VERSION",
                    "database schema is older than this application",
                    details={
                        "subject": "database_schema",
                        "requested_version": str(user_version),
                        "supported_versions": [str(versions.database_schema_version)],
                    },
                )
            pragmas = {
                "foreign_keys": connection.execute("PRAGMA foreign_keys").fetchone()[0],
                "journal_mode": connection.execute("PRAGMA journal_mode").fetchone()[0],
                "synchronous": connection.execute("PRAGMA synchronous").fetchone()[0],
                "busy_timeout": connection.execute("PRAGMA busy_timeout").fetchone()[0],
            }
            if pragmas != {
                "foreign_keys": 1,
                "journal_mode": "wal",
                "synchronous": 2,
                "busy_timeout": 250,
            }:
                raise StorageError(
                    "INTEGRITY_FAILURE",
                    "SQLite pragmas do not match required values",
                    details={"subject": "project_metadata"},
                )
            rows = connection.execute("SELECT key, value FROM metadata").fetchall()
        finally:
            connection.close()
    except StorageError:
        raise
    except (OSError, sqlite3.DatabaseError) as error:
        raise StorageError(
            "INTEGRITY_FAILURE",
            "SQLite storage is unreadable",
            details={"subject": "project_metadata"},
        ) from error
    metadata = {str(key): str(value) for key, value in rows}
    if len(metadata) != len(rows):
        raise StorageError(
            "INTEGRITY_FAILURE",
            "SQLite metadata contains duplicate keys",
            details={"subject": "project_metadata"},
        )
    return user_version, metadata


def load_storage_metadata(
    project_root: Path, versions: VersionSet, *, created: bool = False
) -> StorageMetadata:
    """Load and cross-check an already published storage directory."""
    paths = _bind_paths(project_root)
    if not paths.modeling.exists():
        raise StorageError(
            "PRECONDITION_FAILED",
            "project storage is not initialized",
            details={
                "condition": "project_not_ready",
                "current_state": ProjectState.UNINITIALIZED.value,
            },
        )
    try:
        entries = {entry.name for entry in paths.modeling.iterdir()}
    except OSError as error:
        raise StorageError(
            "INTEGRITY_FAILURE",
            "project storage cannot be enumerated",
            details={"subject": "project_metadata"},
        ) from error
    project = _read_project_json(paths.project_json)
    storage_instance_id = project["storage_instance_id"]
    if not _is_uuid4(storage_instance_id):
        raise StorageError(
            "INTEGRITY_FAILURE",
            "storage instance ID is invalid",
            details={"subject": "project_metadata"},
        )
    user_version, database_metadata = _read_database_metadata(paths.database, versions)
    expected_layout = _LAYOUT_V2 if user_version == 2 else _LAYOUT_V1
    if entries != expected_layout:
        raise StorageError(
            "INTEGRITY_FAILURE",
            "project storage layout is incomplete or unexpected",
            details={"subject": "project_metadata"},
        )
    project_format_version = project["project_format_version"]
    if project_format_version == database_metadata.get(
        "project_format_version"
    ) and _is_higher_project_format_version(
        project_format_version, versions.project_format_version
    ):
        raise StorageError(
            "UNSUPPORTED_VERSION",
            "project format is newer than this application",
            details={
                "subject": "project_format",
                "requested_version": project_format_version,
                "supported_versions": [versions.project_format_version],
            },
        )
    expected = {
        "project_format_version": versions.project_format_version,
        "canonicalization_version": versions.canonicalization_version,
        "storage_instance_id": storage_instance_id,
        "database_schema_version": str(versions.database_schema_version),
    }
    if (
        project["project_format_version"] != versions.project_format_version
        or project["canonicalization_version"] != versions.canonicalization_version
        or database_metadata != expected
    ):
        raise StorageError(
            "INTEGRITY_FAILURE",
            "project and database metadata do not match",
            details={"subject": "project_metadata"},
        )
    return StorageMetadata(
        project_state=ProjectState.STORAGE_READY,
        storage_instance_id=storage_instance_id,
        project_format_version=versions.project_format_version,
        canonicalization_version=versions.canonicalization_version,
        database_schema_version=user_version,
        created=created,
    )


def bootstrap_storage(project_root: Path, versions: VersionSet) -> StorageMetadata:
    """Atomically establish storage without creating a Project row."""
    paths = _bind_paths(project_root)
    if paths.modeling.exists():
        return load_storage_metadata(paths.root, versions)

    temporary = paths.temporary_modeling(str(uuid.uuid4()))
    storage_instance_id = str(uuid.uuid4())
    try:
        temporary.mkdir(mode=0o700)
        project_json = temporary / "project.json"
        database = temporary / "state.sqlite3"
        lock = temporary / "project.lock"
        project_json.write_bytes(_project_bytes(versions, storage_instance_id))
        lock.write_bytes(b"\0")
        _create_database(database, versions, storage_instance_id)
        if versions.database_schema_version == 2:
            (temporary / "staging").mkdir(mode=0o700)
            (temporary / "artifacts").mkdir(mode=0o700)
        for path in (project_json, database, lock):
            _fsync_file(path)
        _fsync_directory(temporary)
        try:
            os.rename(temporary, paths.modeling)
        except (FileExistsError, PermissionError) as error:
            _remove_temporary(temporary, paths.root)
            if paths.modeling.exists():
                return load_storage_metadata(paths.root, versions)
            raise StorageError(
                "CONFLICT",
                "another initializer prevented atomic publication",
                retryable=True,
                details={"conflict_type": "project_busy", "retry_after_ms": 250},
            ) from error
        _fsync_directory(paths.root)
        return load_storage_metadata(paths.root, versions, created=True)
    except StorageError:
        _remove_temporary(temporary, paths.root)
        raise
    except (OSError, sqlite3.DatabaseError) as error:
        _remove_temporary(temporary, paths.root)
        raise StorageError(
            "INTERNAL_ERROR",
            "storage bootstrap failed before publication",
        ) from error
