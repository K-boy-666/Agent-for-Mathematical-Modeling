"""Schema-1 and schema-2 SQLite implementation of the project-store port."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Iterator, Literal, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from jsonschema.exceptions import ValidationError as SchemaValidationError  # type: ignore[import-untyped]
from pydantic import TypeAdapter

from modeling_core.contracts.canonical_json import (
    canonical_json_bytes,
    sha256_json,
    strict_json_loads,
)
from modeling_core.contracts.common import JsonObject, Warning
from modeling_core.contracts.errors import ErrorResponse
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.tools import (
    AttemptStatusCounts,
    CanonicalRootFindingInput,
    DataSnapshotReference,
    EnvironmentSummary,
    ExecutionOptions,
    ExperimentSummary,
    NumericalFailureData,
    ResultPayload,
    ValidationMetrics,
    ValidationReportPayload,
    ValidationStatusCounts,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.domain.models import (
    Artifact,
    Attempt,
    EnvironmentSnapshot,
    Experiment,
    InputSnapshot,
    Project,
    ResultSnapshot,
    Validation,
)
from modeling_core.domain.states import (
    AttemptStatus,
    ProjectState,
    ResultKind,
    TerminalReason,
    ValidationOutcome,
    ValidationStatus,
)
from modeling_core.ports.artifact_store import ArtifactStore, ArtifactStoreError
from modeling_core.ports.clock import Clock
from modeling_core.ports.ids import IdGenerator
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
    LegacyAttempt,
    LegacyIdempotencyRecord,
    LegacyValidation,
    ProjectStatusSnapshot,
    ProjectStateInspection,
    ProjectStoreError,
    ProjectWriteResult,
    RecoveryReport,
    StoreIntegrityCheck,
    StoreIntegrityIssue,
    StoreIntegrityReport,
    StoredRunResult,
    StoredValidationResult,
    ValidationSource,
    VerifiedResult,
    WriteOperation,
)
from modeling_infrastructure.project_lock import ProjectLock, StorageConflict
from modeling_infrastructure.project_paths import ProjectPaths
from modeling_infrastructure.storage import (
    StorageError,
    bootstrap_storage,
    load_storage_metadata,
)

if TYPE_CHECKING:
    from modeling_core.ports.project_store import ProjectStore


_RESULT_PAYLOAD: TypeAdapter[ResultPayload] = TypeAdapter(ResultPayload)
_DATA_REFS = TypeAdapter(tuple[DataSnapshotReference, ...])
_WARNINGS = TypeAdapter(tuple[Warning, ...])
_RESULT_SCHEMA_BASE = "https://schemas.math-modeling-mcp.local/common/"


def _timestamp(value: datetime) -> str:
    utc = value.astimezone(UTC)
    return utc.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _json(value: object) -> str:
    return canonical_json_bytes(value).decode("utf-8")  # type: ignore[arg-type]


def _document(value: str) -> JsonObject:
    decoded = strict_json_loads(value.encode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("stored JSON value must be an object")
    return cast(JsonObject, decoded)


def _array(value: str) -> list[object]:
    decoded = strict_json_loads(value.encode("utf-8"))
    if not isinstance(decoded, list):
        raise ValueError("stored JSON value must be an array")
    return cast(list[object], decoded)


def _validation_metrics(value: str) -> ValidationMetrics:
    return ValidationMetrics.model_validate_json(value, strict=True)


def _validation_report(value: str) -> ValidationReportPayload:
    return ValidationReportPayload.model_validate_json(value, strict=True)


class SQLiteProjectStore:
    """One-project store with short explicit write transactions."""

    def __init__(
        self,
        project_root: Path,
        versions: VersionSet,
        clock: Clock | None = None,
        id_generator: IdGenerator | None = None,
        session_id: str | None = None,
        artifact_store: ArtifactStore | None = None,
    ) -> None:
        self._paths = ProjectPaths.bind(project_root)
        self._versions = versions
        self._schema_version = versions.database_schema_version
        self._clock = clock
        self._id_generator = id_generator
        self._degraded = False
        self._artifact_store = artifact_store
        self._catalogs: dict[str, SchemaCatalog] = {}
        self._project_lock = ProjectLock(
            self._paths.lock,
            session_id if session_id is not None else str(uuid.uuid4()),
        )

    @property
    def _schema_two(self) -> bool:
        return self._schema_version == 2

    def _result_schema_validator(
        self, result_schema_version: str
    ) -> Draft202012Validator:
        schema_axis = result_schema_version.split("/", 1)[-1]
        if schema_axis not in {"0.1.0", "1.0.0"}:
            raise ProjectStoreError(
                "UNSUPPORTED_VERSION",
                "stored result schema version is not supported",
                False,
                {"subject": "result_artifact"},
            )
        catalog = self._catalogs.get(schema_axis)
        if catalog is None:
            catalog = SchemaCatalog.load_packaged(schema_axis)
            self._catalogs[schema_axis] = catalog
        schema_id = f"{_RESULT_SCHEMA_BASE}{schema_axis}/modeling-result.schema.json"
        try:
            schema = catalog.common_schemas[schema_id]
        except KeyError as error:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "result schema asset is missing",
                False,
                {"subject": "result_artifact"},
            ) from error
        return Draft202012Validator(schema)

    def _read_result_bytes(self, row: sqlite3.Row) -> bytes:
        artifact_id = row["result_artifact_id"]
        byte_size = row["artifact_byte_size"]
        sha256 = row["artifact_sha256"]
        if artifact_id is None or byte_size is None or sha256 is None:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "committed result is missing its artifact reference",
                False,
                {"subject": "result_artifact"},
            )
        if artifact_id != sha256 or artifact_id != row["result_hash"]:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "committed result artifact identity disagrees with its hash",
                False,
                {"subject": "result_artifact"},
            )
        if self._artifact_store is None:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "artifact store is unavailable for verified reads",
                False,
                {"subject": "result_artifact"},
            )
        try:
            return self._artifact_store.read_verified(artifact_id, byte_size, sha256)
        except ArtifactStoreError as error:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "committed result artifact failed verification",
                False,
                {"subject": "result_artifact"},
            ) from error

    def _result_payload_from_artifact(self, row: sqlite3.Row) -> ResultPayload:
        raw = self._read_result_bytes(row)
        validator = self._result_schema_validator(row["result_schema_version"])
        try:
            decoded = strict_json_loads(raw)
        except ValueError as error:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "committed result payload failed strict reconstruction",
                False,
                {"subject": "result_artifact"},
            ) from error
        try:
            validator.validate(decoded)
        except SchemaValidationError as error:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "committed result payload failed schema validation",
                False,
                {"subject": "result_artifact"},
            ) from error
        try:
            return _RESULT_PAYLOAD.validate_python(decoded, strict=True)
        except (ValueError, TypeError) as error:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "committed result payload failed strict reconstruction",
                False,
                {"subject": "result_artifact"},
            ) from error

    def _report_payload_from_artifact(
        self, row: sqlite3.Row
    ) -> ValidationReportPayload:
        artifact_id = row["report_artifact_id"]
        byte_size = row["artifact_byte_size"]
        sha256 = row["artifact_sha256"]
        report_hash = row["validation_report_hash"]
        if artifact_id is None or byte_size is None or sha256 is None:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "committed validation is missing its report artifact reference",
                False,
                {"subject": "report_artifact"},
            )
        if artifact_id != sha256 or artifact_id != report_hash:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "committed report artifact identity disagrees with its hash",
                False,
                {"subject": "report_artifact"},
            )
        if self._artifact_store is None:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "artifact store is unavailable for verified reads",
                False,
                {"subject": "report_artifact"},
            )
        try:
            raw = self._artifact_store.read_verified(artifact_id, byte_size, sha256)
        except ArtifactStoreError as error:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "committed report artifact failed verification",
                False,
                {"subject": "report_artifact"},
            ) from error
        try:
            return ValidationReportPayload.model_validate_json(raw, strict=True)
        except ValueError as error:
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "committed report payload failed strict reconstruction",
                False,
                {"subject": "report_artifact"},
            ) from error

    def _result_artifact_from_row(self, row: sqlite3.Row) -> Artifact | None:
        artifact_id = row["result_artifact_id"]
        if artifact_id is None:
            return None
        return Artifact(
            artifact_id=artifact_id,
            role="result",
            media_type=row["artifact_media_type"],
            byte_size=row["artifact_byte_size"],
            sha256=row["artifact_sha256"],
            schema_id=row["artifact_schema_id"],
            created_at=_datetime(row["artifact_created_at"]),
        )

    def _report_artifact_from_row(self, row: sqlite3.Row) -> Artifact | None:
        artifact_id = row["report_artifact_id"]
        if artifact_id is None:
            return None
        return Artifact(
            artifact_id=artifact_id,
            role="validation_report",
            media_type=row["artifact_media_type"],
            byte_size=row["artifact_byte_size"],
            sha256=row["artifact_sha256"],
            schema_id=row["artifact_schema_id"],
            created_at=_datetime(row["artifact_created_at"]),
        )

    @property
    def project_root(self) -> Path:
        return self._paths.root

    def _transient_sqlite_layout(self, error: StorageError) -> bool:
        if (
            error.code != "INTEGRITY_FAILURE"
            or str(error) != "project storage layout is incomplete or unexpected"
        ):
            return False
        try:
            entries = {entry.name for entry in self._paths.modeling.iterdir()}
        except OSError:
            return False
        stable = {"project.json", "project.lock", "state.sqlite3"}
        if self._versions.database_schema_version == 2:
            stable.update({"artifacts", "staging"})
        runtime = stable | {"state.sqlite3-shm", "state.sqlite3-wal"}
        return stable <= entries <= runtime

    def start_writer_session(self) -> None:
        """Acquire and verify existing storage without bootstrapping a new root."""
        if self._project_lock.held:
            return
        if not self._paths.modeling.exists():
            return
        if not self._paths.lock.is_file():
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "project storage is unavailable",
                False,
                {"subject": "project_metadata"},
            )
        try:
            self._project_lock.acquire()
        except StorageConflict as error:
            raise ProjectStoreError(
                "CONFLICT",
                "project is busy",
                True,
                {"conflict_type": "project_busy", "retry_after_ms": 250},
            ) from error
        try:
            load_storage_metadata(self._paths.root, self._versions)
            inspection = self.inspect_project_state()
            integrity = self.inspect_integrity(deep=False)
            if (
                inspection.state is ProjectState.DEGRADED
                or integrity.state is ProjectState.DEGRADED
                or integrity.issues
            ):
                self._degraded = True
                return
        except StorageError as error:
            transient_layout = self._transient_sqlite_layout(error)
            if transient_layout:
                self._project_lock.release()
                raise ProjectStoreError(
                    "CONFLICT",
                    "project is busy",
                    True,
                    {"conflict_type": "project_busy", "retry_after_ms": 250},
                ) from error
            if error.code == "INTEGRITY_FAILURE":
                self._degraded = True
                return
            self._project_lock.release()
            raise ProjectStoreError(
                cast(object, error.code),  # type: ignore[arg-type]
                str(error),
                error.retryable,
                cast(JsonObject, error.details),
            ) from error
        except BaseException:
            self._project_lock.release()
            raise

    def close(self) -> None:
        """Release only this store's held writer lease; retain its lock file."""
        self._project_lock.release()

    def _connect(self, *, named_rows: bool = False) -> sqlite3.Connection:
        connection = sqlite3.connect(self._paths.database, timeout=0.25)
        if named_rows:
            connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=250")
        return connection

    @contextmanager
    def _read(self) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            connection = self._connect(named_rows=True)
            yield connection
        except ProjectStoreError:
            raise
        except sqlite3.OperationalError as error:
            error_code = getattr(error, "sqlite_errorcode", 0) or 0
            if error_code & 0xFF in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
                raise ProjectStoreError(
                    "CONFLICT",
                    "project storage is busy",
                    True,
                    {"conflict_type": "project_busy", "retry_after_ms": 250},
                ) from error
            self._degraded = True
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "project persistence failed closed",
                False,
                {"subject": "database_relation"},
            ) from error
        except (OSError, sqlite3.DatabaseError, ValueError) as error:
            self._degraded = True
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "project persistence failed closed",
                False,
                {"subject": "database_relation"},
            ) from error
        finally:
            if connection is not None:
                connection.close()

    @contextmanager
    def _write(
        self, *, degrade_on_failure: bool = False
    ) -> Iterator[sqlite3.Connection]:
        connection: sqlite3.Connection | None = None
        try:
            self.start_writer_session()
            connection = self._connect(named_rows=True)
            connection.isolation_level = None
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except ProjectStoreError:
            if connection is not None and connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        except sqlite3.OperationalError as error:
            if connection is not None and connection.in_transaction:
                connection.execute("ROLLBACK")
            error_code = getattr(error, "sqlite_errorcode", 0) or 0
            if not degrade_on_failure and error_code & 0xFF in {
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
            }:
                raise ProjectStoreError(
                    "CONFLICT",
                    "project storage is busy",
                    True,
                    {"conflict_type": "project_busy", "retry_after_ms": 250},
                ) from error
            if degrade_on_failure:
                self._degraded = True
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "project persistence failed closed",
                False,
                {"subject": "database_relation"},
            ) from error
        except (OSError, sqlite3.DatabaseError, ValueError) as error:
            if connection is not None and connection.in_transaction:
                connection.execute("ROLLBACK")
            if degrade_on_failure:
                self._degraded = True
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "project persistence failed closed",
                False,
                {"subject": "database_relation"},
            ) from error
        finally:
            if connection is not None:
                connection.close()

    def _now(self) -> datetime:
        value = self._clock.utc_now() if self._clock is not None else datetime.now(UTC)
        return value.astimezone(UTC).replace(
            microsecond=(value.microsecond // 1000) * 1000
        )

    def _new_id(self) -> str:
        return (
            self._id_generator.new_uuid4()
            if self._id_generator is not None
            else str(uuid.uuid4())
        )

    @staticmethod
    def _project_from_row(row: sqlite3.Row) -> Project:
        return Project(
            project_id=row["project_id"],
            storage_instance_id=row["storage_instance_id"],
            project_format_version=row["project_format_version"],
            display_name=row["display_name"],
            created_at=_datetime(row["created_at"]),
        )

    @staticmethod
    def _experiment_from_row(row: sqlite3.Row) -> Experiment:
        return Experiment(
            experiment_id=row["experiment_id"],
            project_id=row["project_id"],
            capability_id=row["capability_id"],
            contract_version=row["contract_version"],
            canonical_input_schema_version=row["canonical_input_schema_version"],
            canonical_payload=CanonicalRootFindingInput.model_validate(
                _document(row["canonical_payload"]), strict=True
            ),
            canonical_payload_hash=row["canonical_payload_hash"],
            model_snapshot_hash=row["model_snapshot_hash"],
            data_snapshot_references=_DATA_REFS.validate_python(
                tuple(_array(row["data_snapshot_references"])), strict=True
            ),
            data_snapshot_set_hash=row["data_snapshot_set_hash"],
            execution_policy=ExecutionOptions.model_validate(
                _document(row["execution_policy"]), strict=True
            ),
            created_at=_datetime(row["created_at"]),
        )

    @staticmethod
    def _result_from_row(row: sqlite3.Row | None) -> ResultSnapshot | None:
        if row is None or row["result_snapshot_id"] is None:
            return None
        payload = _RESULT_PAYLOAD.validate_python(
            _document(row["result_payload_json"]), strict=True
        )
        return ResultSnapshot(
            result_snapshot_id=row["result_snapshot_id"],
            attempt_id=row["attempt_id"],
            result_kind=ResultKind(row["result_kind"]),
            result_schema_version=row["result_schema_version"],
            result_hash=row["result_hash"],
            result_payload=payload,
        )

    @classmethod
    def _attempt_from_row(cls, row: sqlite3.Row) -> Attempt:
        result = cls._result_from_row(row)
        system_error = (
            ErrorResponse.model_validate(_document(row["system_error"]), strict=True)
            if row["system_error"] is not None
            else None
        )
        failure = (
            NumericalFailureData.model_validate(
                _document(row["numerical_failure"]), strict=True
            )
            if row["numerical_failure"] is not None
            else None
        )
        return Attempt(
            attempt_id=row["attempt_id"],
            experiment_id=row["experiment_id"],
            implementation_id=row["implementation_id"],
            implementation_version=row["implementation_version"],
            environment_summary=EnvironmentSummary.model_validate(
                _document(row["environment_summary"]), strict=True
            ),
            randomness=row["randomness"],
            seed=row["seed"],
            session_id=row["session_id"],
            status=AttemptStatus(row["status"]),
            created_at=_datetime(row["created_at"]),
            started_at=_datetime(row["started_at"]) if row["started_at"] else None,
            finished_at=_datetime(row["finished_at"]) if row["finished_at"] else None,
            warnings=_WARNINGS.validate_python(
                tuple(_array(row["warnings"])), strict=True
            ),
            result=result,
            system_error=system_error,
            numerical_failure=failure,
            terminal_reason=(
                TerminalReason(row["terminal_reason"])
                if row["terminal_reason"] is not None
                else None
            ),
        )

    @staticmethod
    def _validation_from_row(row: sqlite3.Row) -> Validation:
        return Validation(
            validation_id=row["validation_id"],
            attempt_id=row["attempt_id"],
            expected_result_hash=row["expected_result_hash"],
            result_hash=row["result_hash"],
            validator_id=row["validator_id"],
            validator_implementation_id=row["validator_implementation_id"],
            validator_implementation_version=row["validator_implementation_version"],
            policy_version=row["policy_version"],
            policy=_document(row["policy"]),
            policy_hash=row["policy_hash"],
            status=ValidationStatus(row["status"]),
            created_at=_datetime(row["created_at"]),
            started_at=_datetime(row["started_at"]) if row["started_at"] else None,
            finished_at=_datetime(row["finished_at"]) if row["finished_at"] else None,
            outcome=(ValidationOutcome(row["outcome"]) if row["outcome"] else None),
            metrics=(
                _validation_metrics(row["metrics"])
                if row["metrics"] is not None
                else None
            ),
            validation_report_hash=row["validation_report_hash"],
            report_payload=(
                _validation_report(row["report_payload_json"])
                if row["report_payload_json"] is not None
                else None
            ),
            operational_error=(
                ErrorResponse.model_validate(
                    _document(row["operational_error"]), strict=True
                )
                if row["operational_error"] is not None
                else None
            ),
            terminal_reason=(
                TerminalReason(row["terminal_reason"])
                if row["terminal_reason"] is not None
                else None
            ),
        )

    def _attempt_from_row_v2(self, row: sqlite3.Row) -> Attempt:
        result: ResultSnapshot | None = None
        if row["result_snapshot_id"] is not None:
            result = ResultSnapshot(
                result_snapshot_id=row["result_snapshot_id"],
                attempt_id=row["attempt_id"],
                result_kind=ResultKind(row["result_kind"]),
                result_schema_version=row["result_schema_version"],
                result_hash=row["result_hash"],
                result_payload=self._result_payload_from_artifact(row),
            )
        system_error = (
            ErrorResponse.model_validate(_document(row["system_error"]), strict=True)
            if row["system_error"] is not None
            else None
        )
        failure = (
            NumericalFailureData.model_validate(
                _document(row["numerical_failure"]), strict=True
            )
            if row["numerical_failure"] is not None
            else None
        )
        return Attempt(
            attempt_id=row["attempt_id"],
            experiment_id=row["experiment_id"],
            implementation_id=row["implementation_id"],
            implementation_version=row["implementation_version"],
            environment_summary=EnvironmentSummary.model_validate(
                _document(row["environment_summary"]), strict=True
            ),
            randomness=row["randomness"],
            seed=row["seed"],
            session_id=row["session_id"],
            status=AttemptStatus(row["status"]),
            created_at=_datetime(row["created_at"]),
            started_at=_datetime(row["started_at"]) if row["started_at"] else None,
            finished_at=_datetime(row["finished_at"]) if row["finished_at"] else None,
            warnings=_WARNINGS.validate_python(
                tuple(_array(row["warnings"])), strict=True
            ),
            result=result,
            system_error=system_error,
            numerical_failure=failure,
            terminal_reason=(
                TerminalReason(row["terminal_reason"])
                if row["terminal_reason"] is not None
                else None
            ),
        )

    def _validation_from_row_v2(self, row: sqlite3.Row) -> Validation:
        return Validation(
            validation_id=row["validation_id"],
            attempt_id=row["attempt_id"],
            expected_result_hash=row["expected_result_hash"],
            result_hash=row["result_hash"],
            validator_id=row["validator_id"],
            validator_implementation_id=row["validator_implementation_id"],
            validator_implementation_version=row["validator_implementation_version"],
            policy_version=row["policy_version"],
            policy=_document(row["policy"]),
            policy_hash=row["policy_hash"],
            status=ValidationStatus(row["status"]),
            created_at=_datetime(row["created_at"]),
            started_at=_datetime(row["started_at"]) if row["started_at"] else None,
            finished_at=_datetime(row["finished_at"]) if row["finished_at"] else None,
            outcome=(ValidationOutcome(row["outcome"]) if row["outcome"] else None),
            metrics=(
                _validation_metrics(row["metrics"])
                if row["metrics"] is not None
                else None
            ),
            validation_report_hash=row["validation_report_hash"],
            report_payload=(
                self._report_payload_from_artifact(row)
                if row["report_artifact_id"] is not None
                else None
            ),
            operational_error=(
                ErrorResponse.model_validate(
                    _document(row["operational_error"]), strict=True
                )
                if row["operational_error"] is not None
                else None
            ),
            terminal_reason=(
                TerminalReason(row["terminal_reason"])
                if row["terminal_reason"] is not None
                else None
            ),
        )

    def _map_attempt(self, row: sqlite3.Row) -> Attempt:
        if self._schema_two:
            return self._attempt_from_row_v2(row)
        return self._attempt_from_row(row)

    def _map_validation(self, row: sqlite3.Row) -> Validation:
        if self._schema_two:
            return self._validation_from_row_v2(row)
        return self._validation_from_row(row)

    def _attempt_row(
        self, connection: sqlite3.Connection, attempt_id: str
    ) -> sqlite3.Row:
        if self._schema_two:
            row = connection.execute(
                """
                SELECT a.*, r.result_snapshot_id, r.result_kind,
                       r.result_schema_version, r.result_hash,
                       r.result_artifact_id,
                       art.media_type AS artifact_media_type,
                       art.byte_size AS artifact_byte_size,
                       art.sha256 AS artifact_sha256,
                       art.schema_id AS artifact_schema_id,
                       art.created_at AS artifact_created_at
                  FROM attempts a
                  LEFT JOIN result_snapshots r ON r.attempt_id = a.attempt_id
                  LEFT JOIN artifacts art ON art.artifact_id = r.result_artifact_id
                 WHERE a.attempt_id = ?
                """,
                (attempt_id,),
            ).fetchone()
        else:
            row = connection.execute(
                """
                SELECT a.*, r.result_snapshot_id, r.result_kind,
                       r.result_schema_version, r.result_hash, r.result_payload_json
                  FROM attempts a
                  LEFT JOIN result_snapshots r ON r.attempt_id = a.attempt_id
                 WHERE a.attempt_id = ?
                """,
                (attempt_id,),
            ).fetchone()
        if row is None:
            raise ProjectStoreError(
                "NOT_FOUND",
                "attempt was not found",
                False,
                {"resource_type": "attempt", "resource_id": attempt_id},
            )
        return cast(sqlite3.Row, row)

    @staticmethod
    def _idempotency_replay(
        connection: sqlite3.Connection,
        *,
        scope_id: str,
        tool_name: str,
        operation: WriteOperation,
    ) -> JsonObject | None:
        row = connection.execute(
            """
            SELECT canonical_request_hash, status, result_entity_references
              FROM idempotency_records
             WHERE scope_id = ? AND tool_name = ? AND operation_id = ?
            """,
            (scope_id, tool_name, operation.operation_id),
        ).fetchone()
        if row is None:
            return None
        if row["canonical_request_hash"] != operation.canonical_request_hash:
            raise ProjectStoreError(
                "CONFLICT",
                "operation ID was reused with a different request",
                False,
                {"conflict_type": "idempotency_mismatch"},
            )
        if row["status"] == "IN_PROGRESS":
            raise ProjectStoreError(
                "CONFLICT",
                "operation is already in progress",
                True,
                {"conflict_type": "operation_in_progress", "retry_after_ms": 250},
            )
        return _document(row["result_entity_references"])

    def inspect_project_state(self) -> ProjectStateInspection:
        if self._degraded:
            return ProjectStateInspection(state=ProjectState.DEGRADED)
        if not self._paths.modeling.exists():
            return ProjectStateInspection(state=ProjectState.UNINITIALIZED)
        try:
            metadata = load_storage_metadata(self._paths.root, self._versions)
            with self._read() as connection:
                rows = connection.execute("SELECT * FROM projects").fetchall()
            if not rows:
                return ProjectStateInspection(state=metadata.project_state)
            if len(rows) != 1:
                return ProjectStateInspection(state=ProjectState.DEGRADED)
            return ProjectStateInspection(
                state=ProjectState.READY,
                project=self._project_from_row(rows[0]),
            )
        except (
            ProjectStoreError,
            StorageError,
            OSError,
            sqlite3.DatabaseError,
            ValueError,
        ):
            return ProjectStateInspection(state=ProjectState.DEGRADED)

    def create_or_replay_project(
        self, command: CreateProjectCommand
    ) -> ProjectWriteResult:
        if self._degraded:
            raise ProjectStoreError(
                "PRECONDITION_FAILED",
                "project is degraded",
                False,
                {"condition": "project_degraded", "current_state": "DEGRADED"},
            )
        first_bootstrap = not self._paths.modeling.exists()
        if first_bootstrap:
            try:
                bootstrap_storage(self._paths.root, self._versions)
            except StorageError as error:
                if not self._paths.modeling.exists():
                    raise ProjectStoreError(
                        cast(object, error.code),  # type: ignore[arg-type]
                        "project storage is unavailable",
                        error.retryable,
                        cast(JsonObject, error.details),
                    ) from error
        try:
            self.start_writer_session()
        except ProjectStoreError as error:
            cause = error.__cause__
            if not (
                first_bootstrap
                and isinstance(cause, StorageError)
                and cause.code == "INTEGRITY_FAILURE"
                and str(cause) == "project storage layout is incomplete or unexpected"
            ):
                raise
            # The first validation closes sidecars left by a competing bootstrap reader.
            self.start_writer_session()
        try:
            metadata = load_storage_metadata(self._paths.root, self._versions)
        except StorageError as error:
            raise ProjectStoreError(
                cast(object, error.code),  # type: ignore[arg-type]
                "project storage is unavailable",
                error.retryable,
                cast(JsonObject, error.details),
            ) from error
        with self._write(degrade_on_failure=True) as connection:
            replay = self._idempotency_replay(
                connection,
                scope_id=metadata.storage_instance_id,
                tool_name="create_project",
                operation=command.operation,
            )
            if replay is not None:
                row = connection.execute("SELECT * FROM projects").fetchone()
                created = replay.get("created")
                if (
                    row is None
                    or set(replay) != {"project_id", "created"}
                    or replay.get("project_id") != row["project_id"]
                    or type(created) is not bool
                ):
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "completed project operation references missing state",
                        False,
                        {"subject": "database_relation"},
                    )
                return ProjectWriteResult(
                    project=self._project_from_row(row),
                    created=created,
                    replayed=True,
                )

            row = connection.execute("SELECT * FROM projects").fetchone()
            created = row is None
            if row is None:
                project = Project(
                    project_id=self._new_id(),
                    storage_instance_id=metadata.storage_instance_id,
                    project_format_version=cast(
                        Literal["modeling-project/0.1.0"],
                        self._versions.project_format_version,
                    ),
                    display_name=command.display_name,
                    created_at=self._now(),
                )
                connection.execute(
                    """
                    INSERT INTO projects(
                        project_id, storage_instance_id, project_format_version,
                        display_name, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        project.project_id,
                        project.storage_instance_id,
                        project.project_format_version,
                        project.display_name,
                        _timestamp(project.created_at),
                    ),
                )
            else:
                project = self._project_from_row(row)
                if project.display_name != command.display_name:
                    raise ProjectStoreError(
                        "CONFLICT",
                        "project metadata does not match the existing project",
                        False,
                        {
                            "conflict_type": "project_metadata_mismatch",
                            "existing_resource_id": project.project_id,
                        },
                    )
            refs: JsonObject = {"project_id": project.project_id, "created": created}
            connection.execute(
                """
                INSERT INTO idempotency_records(
                    scope_id, tool_name, operation_id, canonical_request_hash,
                    status, result_entity_references
                ) VALUES (?, 'create_project', ?, ?, 'COMPLETED', ?)
                """,
                (
                    metadata.storage_instance_id,
                    command.operation.operation_id,
                    command.operation.canonical_request_hash,
                    _json(refs),
                ),
            )
            return ProjectWriteResult(project=project, created=created, replayed=False)

    def get_project_status(self, project_id: str) -> ProjectStatusSnapshot:
        with self._read() as connection:
            project_row = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            if project_row is None:
                raise ProjectStoreError(
                    "NOT_FOUND",
                    "project was not found",
                    False,
                    {"resource_type": "project", "resource_id": project_id},
                )
            attempt_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM attempts GROUP BY status"
            ).fetchall()
            validation_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM validations GROUP BY status"
            ).fetchall()
            experiment_rows = connection.execute(
                """
                SELECT e.experiment_id, e.capability_id, e.contract_version,
                       e.created_at, a.attempt_id, a.status, a.created_at AS attempt_at,
                       (SELECT COUNT(*) FROM attempts ax
                         WHERE ax.experiment_id=e.experiment_id) AS attempt_count,
                       (SELECT COUNT(*) FROM validations v
                         JOIN attempts av ON av.attempt_id=v.attempt_id
                         WHERE av.experiment_id=e.experiment_id) AS validation_count
                  FROM experiments e
                  JOIN attempts a ON a.attempt_id = (
                       SELECT a2.attempt_id FROM attempts a2
                        WHERE a2.experiment_id=e.experiment_id
                        ORDER BY a2.created_at DESC, a2.attempt_id DESC LIMIT 1
                  )
                 ORDER BY e.created_at DESC, e.experiment_id DESC
                 LIMIT 21
                """
            ).fetchall()
            activity_values = [project_row["created_at"]]
            for table, columns in (
                ("experiments", ("created_at",)),
                ("attempts", ("created_at", "started_at", "finished_at")),
                ("validations", ("created_at", "started_at", "finished_at")),
            ):
                select = ", ".join(f"MAX({column})" for column in columns)
                row = connection.execute(f"SELECT {select} FROM {table}").fetchone()
                activity_values.extend(item for item in row if item is not None)

        try:
            attempts = {row["status"]: row["count"] for row in attempt_rows}
            validations = {row["status"]: row["count"] for row in validation_rows}
            summaries = tuple(
                ExperimentSummary(
                    experiment_id=row["experiment_id"],
                    capability_id=row["capability_id"],
                    contract_version=row["contract_version"],
                    created_at=row["created_at"],
                    attempt_count=row["attempt_count"],
                    latest_attempt_id=row["attempt_id"],
                    latest_attempt_status=row["status"],
                    latest_attempt_at=row["attempt_at"],
                    validation_count=row["validation_count"],
                )
                for row in experiment_rows[:20]
            )
            return ProjectStatusSnapshot(
                project=self._project_from_row(project_row),
                attempt_status_counts=AttemptStatusCounts(
                    pending=attempts.get("PENDING", 0),
                    running=attempts.get("RUNNING", 0),
                    succeeded=attempts.get("SUCCEEDED", 0),
                    numerical_failure=attempts.get("NUMERICAL_FAILURE", 0),
                    errored=attempts.get("ERRORED", 0),
                    timed_out=attempts.get("TIMED_OUT", 0),
                    abandoned=attempts.get("ABANDONED", 0),
                ),
                validation_status_counts=ValidationStatusCounts(
                    pending=validations.get("PENDING", 0),
                    running=validations.get("RUNNING", 0),
                    succeeded=validations.get("SUCCEEDED", 0),
                    errored=validations.get("ERRORED", 0),
                    timed_out=validations.get("TIMED_OUT", 0),
                    abandoned=validations.get("ABANDONED", 0),
                ),
                last_activity_at=_datetime(max(activity_values)),
                experiments=summaries,
                truncated=len(experiment_rows) > 20,
            )
        except (AttributeError, TypeError, ValueError) as error:
            self._degraded = True
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "stored project status failed reconstruction",
                False,
                {"subject": "database_relation"},
            ) from error

    def get_experiment_trace(self, query: ExperimentTraceQuery) -> ExperimentTrace:
        with self._read() as connection:
            project_row = connection.execute(
                "SELECT * FROM projects WHERE project_id=?", (query.project_id,)
            ).fetchone()
            experiment_row = connection.execute(
                "SELECT * FROM experiments WHERE project_id=? AND experiment_id=?",
                (query.project_id, query.experiment_id),
            ).fetchone()
            if project_row is None or experiment_row is None:
                raise ProjectStoreError(
                    "NOT_FOUND",
                    "experiment was not found",
                    False,
                    {"resource_type": "experiment", "resource_id": query.experiment_id},
                )
            if self._schema_two:
                attempt_rows = connection.execute(
                    """
                    SELECT a.*, r.result_snapshot_id, r.result_kind,
                           r.result_schema_version, r.result_hash,
                           r.result_artifact_id,
                           art.media_type AS artifact_media_type,
                           art.byte_size AS artifact_byte_size,
                           art.sha256 AS artifact_sha256,
                           art.schema_id AS artifact_schema_id,
                           art.created_at AS artifact_created_at
                      FROM attempts a LEFT JOIN result_snapshots r
                        ON r.attempt_id=a.attempt_id
                      LEFT JOIN artifacts art
                        ON art.artifact_id=r.result_artifact_id
                     WHERE a.experiment_id=? ORDER BY a.created_at, a.attempt_id
                    """,
                    (query.experiment_id,),
                ).fetchall()
            else:
                attempt_rows = connection.execute(
                    """
                    SELECT a.*, r.result_snapshot_id, r.result_kind,
                           r.result_schema_version, r.result_hash, r.result_payload_json
                      FROM attempts a LEFT JOIN result_snapshots r
                        ON r.attempt_id=a.attempt_id
                     WHERE a.experiment_id=? ORDER BY a.created_at, a.attempt_id
                    """,
                    (query.experiment_id,),
                ).fetchall()
            attempt_ids = [row["attempt_id"] for row in attempt_rows]
            validation_rows: list[sqlite3.Row] = []
            if attempt_ids:
                placeholders = ",".join("?" for _ in attempt_ids)
                if self._schema_two:
                    validation_rows = connection.execute(
                        f"""
                        SELECT v.*, art.media_type AS artifact_media_type,
                               art.byte_size AS artifact_byte_size,
                               art.sha256 AS artifact_sha256,
                               art.schema_id AS artifact_schema_id,
                               art.created_at AS artifact_created_at
                          FROM validations v LEFT JOIN artifacts art
                            ON art.artifact_id=v.report_artifact_id
                         WHERE v.attempt_id IN ({placeholders})
                         ORDER BY v.created_at, v.validation_id
                        """,
                        attempt_ids,
                    ).fetchall()
                else:
                    validation_rows = connection.execute(
                        f"SELECT * FROM validations WHERE attempt_id IN ({placeholders}) "
                        "ORDER BY created_at, validation_id",
                        attempt_ids,
                    ).fetchall()
        try:
            return ExperimentTrace(
                project=self._project_from_row(project_row),
                experiment=self._experiment_from_row(experiment_row),
                attempts=tuple(self._map_attempt(row) for row in attempt_rows),
                validations=tuple(self._map_validation(row) for row in validation_rows),
            )
        except ValueError as error:
            self._degraded = True
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "stored experiment trace failed reconstruction",
                False,
                {"subject": "database_relation"},
            ) from error

    def get_validation_source(
        self, project_id: str, attempt_id: str
    ) -> ValidationSource:
        with self._read() as connection:
            attempt_row = self._attempt_row(connection, attempt_id)
            experiment_row = connection.execute(
                "SELECT * FROM experiments WHERE experiment_id=? AND project_id=?",
                (attempt_row["experiment_id"], project_id),
            ).fetchone()
            if experiment_row is None:
                raise ProjectStoreError(
                    "NOT_FOUND",
                    "attempt was not found in project",
                    False,
                    {"resource_type": "attempt", "resource_id": attempt_id},
                )
        try:
            experiment = self._experiment_from_row(experiment_row)
            attempt = self._map_attempt(attempt_row)
        except (AttributeError, TypeError, ValueError) as error:
            self._degraded = True
            raise ProjectStoreError(
                "INTEGRITY_FAILURE",
                "stored validation source failed reconstruction",
                False,
                {"subject": "database_relation"},
            ) from error
        try:
            return ValidationSource(experiment=experiment, attempt=attempt)
        except ValueError as error:
            raise ProjectStoreError(
                "PRECONDITION_FAILED",
                "attempt is not eligible for validation",
                False,
                {
                    "condition": "attempt_not_succeeded",
                    "current_state": attempt_row["status"],
                },
            ) from error

    def load_verified_result(self, attempt_id: str) -> VerifiedResult:
        """Reread the committed result after artifact identity and hash checks."""
        with self._read() as connection:
            attempt_exists = connection.execute(
                "SELECT 1 FROM attempts WHERE attempt_id=?", (attempt_id,)
            ).fetchone()
            if attempt_exists is None:
                raise ProjectStoreError(
                    "NOT_FOUND",
                    "attempt was not found",
                    False,
                    {"resource_type": "attempt", "resource_id": attempt_id},
                )
            if self._schema_two:
                row = connection.execute(
                    """
                    SELECT r.result_snapshot_id, r.attempt_id, r.result_kind,
                           r.result_schema_version, r.result_hash,
                           r.result_artifact_id,
                           art.role AS artifact_role,
                           art.media_type AS artifact_media_type,
                           art.byte_size AS artifact_byte_size,
                           art.sha256 AS artifact_sha256,
                           art.schema_id AS artifact_schema_id,
                           art.created_at AS artifact_created_at
                      FROM result_snapshots r
                      LEFT JOIN artifacts art
                        ON art.artifact_id = r.result_artifact_id
                     WHERE r.attempt_id = ?
                    """,
                    (attempt_id,),
                ).fetchone()
                if row is None or row["result_artifact_id"] is None:
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "committed result is missing its artifact reference",
                        False,
                        {"subject": "result_artifact"},
                    )
                if row["artifact_role"] != "result":
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "committed result artifact has the wrong role",
                        False,
                        {"subject": "result_artifact"},
                    )
                payload = self._result_payload_from_artifact(row)
                artifact = self._result_artifact_from_row(row)
                result_snapshot = ResultSnapshot(
                    result_snapshot_id=row["result_snapshot_id"],
                    attempt_id=row["attempt_id"],
                    result_kind=ResultKind(row["result_kind"]),
                    result_schema_version=row["result_schema_version"],
                    result_hash=row["result_hash"],
                    result_payload=payload,
                )
                return VerifiedResult(
                    result_snapshot=result_snapshot,
                    artifact=artifact,
                    payload_bytes=self._read_result_bytes(row),
                )
            row = connection.execute(
                """
                SELECT r.result_snapshot_id, r.attempt_id, r.result_kind,
                       r.result_schema_version, r.result_hash, r.result_payload_json
                  FROM result_snapshots r
                 WHERE r.attempt_id = ?
                """,
                (attempt_id,),
            ).fetchone()
            if row is None:
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "committed result is missing",
                    False,
                    {"subject": "result_artifact"},
                )
            try:
                result_snapshot = ResultSnapshot(
                    result_snapshot_id=row["result_snapshot_id"],
                    attempt_id=row["attempt_id"],
                    result_kind=ResultKind(row["result_kind"]),
                    result_schema_version=row["result_schema_version"],
                    result_hash=row["result_hash"],
                    result_payload=_RESULT_PAYLOAD.validate_python(
                        _document(row["result_payload_json"]), strict=True
                    ),
                )
            except (AttributeError, TypeError, ValueError) as error:
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "committed result failed strict reconstruction",
                    False,
                    {"subject": "result_artifact"},
                ) from error
            raw = canonical_json_bytes(
                cast(
                    JsonObject,
                    result_snapshot.result_payload.model_dump(mode="json"),
                )
            )
            if (
                sha256_json(
                    cast(
                        JsonObject,
                        result_snapshot.result_payload.model_dump(mode="json"),
                    )
                )
                != result_snapshot.result_hash
            ):
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "committed result hash does not match its payload",
                    False,
                    {"subject": "result_artifact"},
                )
            return VerifiedResult(
                result_snapshot=result_snapshot,
                artifact=None,
                payload_bytes=raw,
            )

    def _insert_experiment(
        self, connection: sqlite3.Connection, item: Experiment, input_snapshot_id: str
    ) -> None:
        if self._schema_two:
            connection.execute(
                """
                INSERT INTO experiments(
                    experiment_id, project_id, capability_id, contract_version,
                    canonical_input_schema_version, canonical_payload,
                    canonical_payload_hash, canonicalization_version,
                    model_snapshot_hash, data_snapshot_references,
                    data_snapshot_set_hash, execution_policy, input_snapshot_id,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.experiment_id,
                    item.project_id,
                    item.capability_id,
                    item.contract_version,
                    item.canonical_input_schema_version,
                    _json(item.canonical_payload.model_dump(mode="json")),
                    item.canonical_payload_hash,
                    self._versions.canonicalization_version,
                    item.model_snapshot_hash,
                    _json(
                        [
                            ref.model_dump(mode="json")
                            for ref in item.data_snapshot_references
                        ]
                    ),
                    item.data_snapshot_set_hash,
                    _json(item.execution_policy.model_dump(mode="json")),
                    input_snapshot_id,
                    _timestamp(item.created_at),
                ),
            )
            return
        connection.execute(
            """
            INSERT INTO experiments(
                experiment_id, project_id, capability_id, contract_version,
                canonical_input_schema_version, canonical_payload,
                canonical_payload_hash, canonicalization_version,
                model_snapshot_hash, data_snapshot_references,
                data_snapshot_set_hash, execution_policy, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.experiment_id,
                item.project_id,
                item.capability_id,
                item.contract_version,
                item.canonical_input_schema_version,
                _json(item.canonical_payload.model_dump(mode="json")),
                item.canonical_payload_hash,
                self._versions.canonicalization_version,
                item.model_snapshot_hash,
                _json(
                    [
                        ref.model_dump(mode="json")
                        for ref in item.data_snapshot_references
                    ]
                ),
                item.data_snapshot_set_hash,
                _json(item.execution_policy.model_dump(mode="json")),
                _timestamp(item.created_at),
            ),
        )

    @staticmethod
    def _insert_input_snapshot(
        connection: sqlite3.Connection, item: InputSnapshot
    ) -> None:
        connection.execute(
            """
            INSERT INTO input_snapshots(
                input_snapshot_id, canonical_input_schema_version,
                canonical_payload_hash, model_snapshot_hash,
                data_snapshot_references, data_snapshot_set_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.input_snapshot_id,
                item.canonical_input_schema_version,
                item.canonical_payload_hash,
                item.model_snapshot_hash,
                _json(
                    [
                        ref.model_dump(mode="json")
                        for ref in item.data_snapshot_references
                    ]
                ),
                item.data_snapshot_set_hash,
                _timestamp(item.created_at),
            ),
        )

    @staticmethod
    def _insert_environment_snapshot(
        connection: sqlite3.Connection, item: EnvironmentSnapshot
    ) -> None:
        connection.execute(
            """
            INSERT INTO environment_snapshots(
                environment_snapshot_id, environment_json, environment_hash,
                created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (
                item.environment_snapshot_id,
                _json(item.environment_document),
                item.environment_hash,
                _timestamp(item.created_at),
            ),
        )

    def _insert_attempt(
        self,
        connection: sqlite3.Connection,
        item: Attempt,
        input_snapshot_id: str,
        environment_snapshot_id: str | None,
    ) -> None:
        if self._schema_two:
            connection.execute(
                """
                INSERT INTO attempts(
                    attempt_id, experiment_id, implementation_id,
                    implementation_version, environment_summary, randomness, seed,
                    session_id, input_snapshot_id, environment_snapshot_id,
                    status, created_at, started_at, finished_at, warnings,
                    system_error, numerical_failure, terminal_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.attempt_id,
                    item.experiment_id,
                    item.implementation_id,
                    item.implementation_version,
                    _json(item.environment_summary.model_dump(mode="json")),
                    item.randomness,
                    item.seed,
                    item.session_id,
                    input_snapshot_id,
                    environment_snapshot_id,
                    item.status.value,
                    _timestamp(item.created_at),
                    None,
                    None,
                    _json(
                        [warning.model_dump(mode="json") for warning in item.warnings]
                    ),
                    None,
                    None,
                    None,
                ),
            )
            return
        connection.execute(
            """
            INSERT INTO attempts(
                attempt_id, experiment_id, implementation_id,
                implementation_version, environment_summary, randomness, seed,
                session_id, status, created_at, started_at, finished_at, warnings,
                system_error, numerical_failure, terminal_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.attempt_id,
                item.experiment_id,
                item.implementation_id,
                item.implementation_version,
                _json(item.environment_summary.model_dump(mode="json")),
                item.randomness,
                item.seed,
                item.session_id,
                item.status.value,
                _timestamp(item.created_at),
                None,
                None,
                _json([warning.model_dump(mode="json") for warning in item.warnings]),
                None,
                None,
                None,
            ),
        )

    @staticmethod
    def _insert_artifact_row(connection: sqlite3.Connection, item: Artifact) -> None:
        existing = connection.execute(
            "SELECT role, media_type, byte_size, sha256, schema_id "
            "FROM artifacts WHERE artifact_id=?",
            (item.artifact_id,),
        ).fetchone()
        if existing is not None:
            if tuple(existing) != (
                item.role,
                item.media_type,
                item.byte_size,
                item.sha256,
                item.schema_id,
            ):
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "content-addressed artifact metadata is inconsistent",
                    False,
                    {"subject": "result_artifact"},
                )
            return
        connection.execute(
            """
            INSERT INTO artifacts(
                artifact_id, role, media_type, byte_size, sha256, schema_id,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.artifact_id,
                item.role,
                item.media_type,
                item.byte_size,
                item.sha256,
                item.schema_id,
                _timestamp(item.created_at),
            ),
        )

    def begin_run(self, command: BeginRunCommand) -> BeginRunResult:
        with self._write() as connection:
            replay = self._idempotency_replay(
                connection,
                scope_id=command.experiment.project_id,
                tool_name="run_experiment",
                operation=command.operation,
            )
            if replay is not None:
                experiment_id = replay.get("experiment_id")
                attempt_id = replay.get("attempt_id")
                if (
                    set(replay) != {"experiment_id", "attempt_id"}
                    or not isinstance(experiment_id, str)
                    or not isinstance(attempt_id, str)
                ):
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "completed run references invalid state",
                        False,
                        {"subject": "database_relation"},
                    )
                experiment_row = connection.execute(
                    "SELECT * FROM experiments WHERE experiment_id=? AND project_id=?",
                    (experiment_id, command.experiment.project_id),
                ).fetchone()
                try:
                    attempt_row = self._attempt_row(connection, attempt_id)
                except ProjectStoreError as error:
                    if error.code != "NOT_FOUND":
                        raise
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "completed run references missing state",
                        False,
                        {"subject": "database_relation"},
                    ) from error
                if (
                    experiment_row is None
                    or (
                        command.mode == "rerun"
                        and experiment_id != command.experiment.experiment_id
                    )
                    or attempt_row["experiment_id"] != experiment_id
                    or attempt_row["status"]
                    not in {
                        "SUCCEEDED",
                        "NUMERICAL_FAILURE",
                        "ERRORED",
                        "TIMED_OUT",
                        "ABANDONED",
                    }
                ):
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "completed run references missing state",
                        False,
                        {"subject": "database_relation"},
                    )
                attempt = self._map_attempt(attempt_row)
                return BeginRunResult(
                    experiment=self._experiment_from_row(experiment_row),
                    attempt=attempt,
                    replayed=True,
                    artifact=(
                        self._result_artifact_from_row(attempt_row)
                        if self._schema_two
                        else None
                    ),
                )
            if (
                connection.execute(
                    "SELECT 1 FROM projects WHERE project_id=?",
                    (command.experiment.project_id,),
                ).fetchone()
                is None
            ):
                raise ProjectStoreError(
                    "NOT_FOUND",
                    "project was not found",
                    False,
                    {
                        "resource_type": "project",
                        "resource_id": command.experiment.project_id,
                    },
                )
            connection.execute(
                """
                INSERT INTO idempotency_records VALUES (
                    ?, 'run_experiment', ?, ?, 'IN_PROGRESS', '{}'
                )
                """,
                (
                    command.experiment.project_id,
                    command.operation.operation_id,
                    command.operation.canonical_request_hash,
                ),
            )
            if self._schema_two:
                if command.environment_snapshot is None:
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "schema 2 begin-run requires an environment snapshot",
                        False,
                        {"subject": "database_relation"},
                    )
                self._insert_environment_snapshot(
                    connection, command.environment_snapshot
                )
                if command.mode == "new":
                    if command.input_snapshot is None:
                        raise ProjectStoreError(
                            "INTEGRITY_FAILURE",
                            "new run requires an input snapshot",
                            False,
                            {"subject": "database_relation"},
                        )
                    self._insert_input_snapshot(connection, command.input_snapshot)
                    self._insert_experiment(
                        connection,
                        command.experiment,
                        command.input_snapshot.input_snapshot_id,
                    )
                    input_snapshot_id = command.input_snapshot.input_snapshot_id
                else:
                    stored_experiment = connection.execute(
                        "SELECT * FROM experiments WHERE experiment_id=? AND project_id=?",
                        (
                            command.experiment.experiment_id,
                            command.experiment.project_id,
                        ),
                    ).fetchone()
                    if (
                        stored_experiment is None
                        or self._experiment_from_row(stored_experiment)
                        != command.experiment
                    ):
                        raise ProjectStoreError(
                            "INTEGRITY_FAILURE",
                            "rerun intent does not match the stored experiment",
                            False,
                            {"subject": "database_relation"},
                        )
                    input_snapshot_id = stored_experiment["input_snapshot_id"]
                self._insert_attempt(
                    connection,
                    command.attempt,
                    input_snapshot_id,
                    command.environment_snapshot.environment_snapshot_id,
                )
            else:
                if command.mode == "rerun":
                    raise ProjectStoreError(
                        "UNSUPPORTED_VERSION",
                        "rerun requires database schema 2",
                        False,
                        {"subject": "database_schema"},
                    )
                if (
                    command.input_snapshot is not None
                    or command.environment_snapshot is not None
                ):
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "schema 1 begin-run does not accept snapshots",
                        False,
                        {"subject": "database_relation"},
                    )
                self._insert_experiment(connection, command.experiment, "")
                self._insert_attempt(connection, command.attempt, "", None)
            return BeginRunResult(
                experiment=command.experiment, attempt=command.attempt, replayed=False
            )

    def mark_attempt_running(
        self, attempt_id: str, started_at: datetime, session_id: str
    ) -> None:
        with self._write() as connection:
            cursor = connection.execute(
                """
                UPDATE attempts SET status='RUNNING', started_at=?
                 WHERE attempt_id=? AND status='PENDING' AND session_id=?
                """,
                (_timestamp(started_at), attempt_id, session_id),
            )
            if cursor.rowcount != 1:
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "attempt transition was rejected",
                    False,
                    {"subject": "database_relation"},
                )

    def complete_attempt(self, command: CompleteAttemptCommand) -> StoredRunResult:
        with self._write(degrade_on_failure=True) as connection:
            row = connection.execute(
                """
                SELECT e.project_id, a.status, a.experiment_id,
                       a.implementation_id, a.implementation_version,
                       a.environment_summary, a.randomness, a.seed,
                       a.session_id, a.created_at, a.started_at
                  FROM attempts a
                JOIN experiments e ON e.experiment_id=a.experiment_id
                WHERE a.attempt_id=?
                """,
                (command.attempt.attempt_id,),
            ).fetchone()
            item = command.attempt
            if row is None or row["status"] != "RUNNING":
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "attempt completion state is invalid",
                    False,
                    {"subject": "database_relation"},
                )
            if (
                row["experiment_id"] != item.experiment_id
                or row["implementation_id"] != item.implementation_id
                or row["implementation_version"] != item.implementation_version
                or row["environment_summary"]
                != _json(item.environment_summary.model_dump(mode="json"))
                or row["randomness"] != item.randomness
                or row["seed"] != item.seed
                or row["session_id"] != item.session_id
                or row["created_at"] != _timestamp(item.created_at)
                or row["started_at"] != _timestamp(cast(datetime, item.started_at))
            ):
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "attempt provenance is invalid",
                    False,
                    {"subject": "database_relation"},
                )
            idem = connection.execute(
                """
                SELECT status, canonical_request_hash FROM idempotency_records
                 WHERE scope_id=? AND tool_name='run_experiment' AND operation_id=?
                """,
                (row["project_id"], command.operation.operation_id),
            ).fetchone()
            if (
                idem is None
                or idem["status"] != "IN_PROGRESS"
                or (
                    idem["canonical_request_hash"]
                    != command.operation.canonical_request_hash
                )
            ):
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "run idempotency state is invalid",
                    False,
                    {"subject": "database_relation"},
                )
            if item.result is not None:
                if self._schema_two:
                    if command.result_artifact is None:
                        raise ProjectStoreError(
                            "INTEGRITY_FAILURE",
                            "schema 2 result completion requires its artifact",
                            False,
                            {"subject": "result_artifact"},
                        )
                    self._insert_artifact_row(connection, command.result_artifact)
                    result_cursor = connection.execute(
                        """
                        INSERT INTO result_snapshots(
                            result_snapshot_id, attempt_id, result_kind,
                            result_schema_version, result_hash, result_artifact_id
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.result.result_snapshot_id,
                            item.attempt_id,
                            item.result.result_kind.value,
                            item.result.result_schema_version,
                            item.result.result_hash,
                            command.result_artifact.artifact_id,
                        ),
                    )
                else:
                    if command.result_artifact is not None:
                        raise ProjectStoreError(
                            "INTEGRITY_FAILURE",
                            "schema 1 result completion does not accept artifacts",
                            False,
                            {"subject": "database_relation"},
                        )
                    result_cursor = connection.execute(
                        """
                        INSERT INTO result_snapshots VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item.result.result_snapshot_id,
                            item.attempt_id,
                            item.result.result_kind.value,
                            item.result.result_schema_version,
                            item.result.result_hash,
                            _json(item.result.result_payload.model_dump(mode="json")),
                        ),
                    )
                if result_cursor.rowcount != 1:
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "result completion was rejected",
                        False,
                        {"subject": "database_relation"},
                    )
            attempt_cursor = connection.execute(
                """
                UPDATE attempts SET status=?, finished_at=?, warnings=?, system_error=?,
                       numerical_failure=?, terminal_reason=?
                 WHERE attempt_id=? AND status='RUNNING'
                """,
                (
                    item.status.value,
                    _timestamp(cast(datetime, item.finished_at)),
                    _json(
                        [warning.model_dump(mode="json") for warning in item.warnings]
                    ),
                    _json(item.system_error.model_dump(mode="json"))
                    if item.system_error
                    else None,
                    _json(item.numerical_failure.model_dump(mode="json"))
                    if item.numerical_failure
                    else None,
                    item.terminal_reason.value if item.terminal_reason else None,
                    item.attempt_id,
                ),
            )
            if attempt_cursor.rowcount != 1:
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "attempt completion was rejected",
                    False,
                    {"subject": "database_relation"},
                )
            refs: JsonObject = {
                "experiment_id": item.experiment_id,
                "attempt_id": item.attempt_id,
            }
            idempotency_cursor = connection.execute(
                """
                UPDATE idempotency_records SET status='COMPLETED',
                       result_entity_references=?
                 WHERE scope_id=? AND tool_name='run_experiment' AND operation_id=?
                   AND status='IN_PROGRESS' AND canonical_request_hash=?
                """,
                (
                    _json(refs),
                    row["project_id"],
                    command.operation.operation_id,
                    command.operation.canonical_request_hash,
                ),
            )
            if idempotency_cursor.rowcount != 1:
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "run idempotency completion was rejected",
                    False,
                    {"subject": "database_relation"},
                )
            return StoredRunResult(
                attempt=item,
                artifact=command.result_artifact,
            )

    def begin_validation(
        self, command: BeginValidationCommand
    ) -> BeginValidationResult:
        with self._write() as connection:
            row = connection.execute(
                """
                SELECT e.project_id FROM attempts a JOIN experiments e
                  ON e.experiment_id=a.experiment_id WHERE a.attempt_id=?
                """,
                (command.validation.attempt_id,),
            ).fetchone()
            if row is None:
                raise ProjectStoreError(
                    "NOT_FOUND",
                    "attempt was not found",
                    False,
                    {
                        "resource_type": "attempt",
                        "resource_id": command.validation.attempt_id,
                    },
                )
            project_id = row["project_id"]
            replay = self._idempotency_replay(
                connection,
                scope_id=project_id,
                tool_name="validate_experiment",
                operation=command.operation,
            )
            if replay is not None:
                validation_id = replay.get("validation_id")
                if self._schema_two:
                    stored = connection.execute(
                        """
                        SELECT v.*, art.media_type AS artifact_media_type,
                               art.byte_size AS artifact_byte_size,
                               art.sha256 AS artifact_sha256,
                               art.schema_id AS artifact_schema_id,
                               art.created_at AS artifact_created_at
                          FROM validations v LEFT JOIN artifacts art
                            ON art.artifact_id=v.report_artifact_id
                         WHERE v.validation_id=?
                        """,
                        (validation_id,),
                    ).fetchone()
                else:
                    stored = connection.execute(
                        "SELECT * FROM validations WHERE validation_id=?",
                        (validation_id,),
                    ).fetchone()
                if (
                    stored is None
                    or set(replay) != {"validation_id"}
                    or not isinstance(validation_id, str)
                    or stored["status"]
                    not in {"SUCCEEDED", "ERRORED", "TIMED_OUT", "ABANDONED"}
                ):
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "completed validation references missing state",
                        False,
                        {"subject": "database_relation"},
                    )
                replayed_validation = self._map_validation(stored)
                expected = command.validation
                if (
                    replayed_validation.attempt_id != expected.attempt_id
                    or replayed_validation.expected_result_hash
                    != expected.expected_result_hash
                    or replayed_validation.result_hash != expected.result_hash
                    or replayed_validation.validator_id != expected.validator_id
                    or replayed_validation.validator_implementation_id
                    != expected.validator_implementation_id
                    or replayed_validation.validator_implementation_version
                    != expected.validator_implementation_version
                    or replayed_validation.policy_version != expected.policy_version
                    or replayed_validation.policy != expected.policy
                    or replayed_validation.policy_hash != expected.policy_hash
                ):
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "completed validation references inconsistent state",
                        False,
                        {"subject": "database_relation"},
                    )
                return BeginValidationResult(
                    validation=replayed_validation,
                    replayed=True,
                    report_artifact=(
                        self._report_artifact_from_row(stored)
                        if self._schema_two
                        else None
                    ),
                )
            connection.execute(
                """
                INSERT INTO idempotency_records VALUES (
                    ?, 'validate_experiment', ?, ?, 'IN_PROGRESS', '{}'
                )
                """,
                (
                    project_id,
                    command.operation.operation_id,
                    command.operation.canonical_request_hash,
                ),
            )
            item = command.validation
            connection.execute(
                """
                INSERT INTO validations(
                    validation_id, attempt_id, expected_result_hash, result_hash,
                    validator_id, validator_implementation_id,
                    validator_implementation_version, policy_version, policy,
                    policy_hash, status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
                """,
                (
                    item.validation_id,
                    item.attempt_id,
                    item.expected_result_hash,
                    item.result_hash,
                    item.validator_id,
                    item.validator_implementation_id,
                    item.validator_implementation_version,
                    item.policy_version,
                    _json(item.policy),
                    item.policy_hash,
                    _timestamp(item.created_at),
                ),
            )
            return BeginValidationResult(validation=item, replayed=False)

    def mark_validation_running(self, validation_id: str, started_at: datetime) -> None:
        with self._write() as connection:
            cursor = connection.execute(
                "UPDATE validations SET status='RUNNING', started_at=? "
                "WHERE validation_id=? AND status='PENDING'",
                (_timestamp(started_at), validation_id),
            )
            if cursor.rowcount != 1:
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "validation transition was rejected",
                    False,
                    {"subject": "database_relation"},
                )

    def complete_validation(
        self, command: CompleteValidationCommand
    ) -> StoredValidationResult:
        with self._write(degrade_on_failure=True) as connection:
            row = connection.execute(
                """
                SELECT e.project_id, v.status, v.attempt_id,
                       v.expected_result_hash, v.result_hash, v.validator_id,
                       v.validator_implementation_id,
                       v.validator_implementation_version, v.policy_version,
                       v.policy, v.policy_hash, v.created_at, v.started_at
                  FROM validations v
                JOIN attempts a ON a.attempt_id=v.attempt_id
                JOIN experiments e ON e.experiment_id=a.experiment_id
                WHERE v.validation_id=?
                """,
                (command.validation.validation_id,),
            ).fetchone()
            item = command.validation
            if row is None or row["status"] != "RUNNING":
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "validation completion state is invalid",
                    False,
                    {"subject": "database_relation"},
                )
            if (
                row["attempt_id"] != item.attempt_id
                or row["expected_result_hash"] != item.expected_result_hash
                or row["result_hash"] != item.result_hash
                or row["validator_id"] != item.validator_id
                or row["validator_implementation_id"]
                != item.validator_implementation_id
                or row["validator_implementation_version"]
                != item.validator_implementation_version
                or row["policy_version"] != item.policy_version
                or row["policy"] != _json(item.policy)
                or row["policy_hash"] != item.policy_hash
                or row["created_at"] != _timestamp(item.created_at)
                or row["started_at"] != _timestamp(cast(datetime, item.started_at))
            ):
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "validation provenance is invalid",
                    False,
                    {"subject": "database_relation"},
                )
            idem = connection.execute(
                """
                SELECT status, canonical_request_hash FROM idempotency_records
                 WHERE scope_id=? AND tool_name='validate_experiment' AND operation_id=?
                """,
                (row["project_id"], command.operation.operation_id),
            ).fetchone()
            if (
                idem is None
                or idem["status"] != "IN_PROGRESS"
                or (
                    idem["canonical_request_hash"]
                    != command.operation.canonical_request_hash
                )
            ):
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "validation idempotency state is invalid",
                    False,
                    {"subject": "database_relation"},
                )
            if self._schema_two:
                if command.report_artifact is not None:
                    if (
                        item.report_payload is None
                        or item.validation_report_hash is None
                    ):
                        raise ProjectStoreError(
                            "INTEGRITY_FAILURE",
                            "schema 2 report artifact requires its payload and hash",
                            False,
                            {"subject": "report_artifact"},
                        )
                    self._insert_artifact_row(connection, command.report_artifact)
                validation_cursor = connection.execute(
                    """
                    UPDATE validations SET status=?, finished_at=?, outcome=?, metrics=?,
                           validation_report_hash=?, report_artifact_id=?,
                           operational_error=?, terminal_reason=?
                     WHERE validation_id=? AND status='RUNNING'
                    """,
                    (
                        item.status.value,
                        _timestamp(cast(datetime, item.finished_at)),
                        item.outcome.value if item.outcome else None,
                        _json(item.metrics.model_dump(mode="json"))
                        if item.metrics
                        else None,
                        item.validation_report_hash,
                        command.report_artifact.artifact_id
                        if command.report_artifact is not None
                        else None,
                        _json(item.operational_error.model_dump(mode="json"))
                        if item.operational_error
                        else None,
                        item.terminal_reason.value if item.terminal_reason else None,
                        item.validation_id,
                    ),
                )
            else:
                if command.report_artifact is not None:
                    raise ProjectStoreError(
                        "INTEGRITY_FAILURE",
                        "schema 1 validation completion does not accept artifacts",
                        False,
                        {"subject": "database_relation"},
                    )
                validation_cursor = connection.execute(
                    """
                    UPDATE validations SET status=?, finished_at=?, outcome=?, metrics=?,
                           validation_report_hash=?, report_payload_json=?,
                           operational_error=?, terminal_reason=?
                     WHERE validation_id=? AND status='RUNNING'
                    """,
                    (
                        item.status.value,
                        _timestamp(cast(datetime, item.finished_at)),
                        item.outcome.value if item.outcome else None,
                        _json(item.metrics.model_dump(mode="json"))
                        if item.metrics
                        else None,
                        item.validation_report_hash,
                        _json(item.report_payload.model_dump(mode="json"))
                        if item.report_payload
                        else None,
                        _json(item.operational_error.model_dump(mode="json"))
                        if item.operational_error
                        else None,
                        item.terminal_reason.value if item.terminal_reason else None,
                        item.validation_id,
                    ),
                )
            if validation_cursor.rowcount != 1:
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "validation completion was rejected",
                    False,
                    {"subject": "database_relation"},
                )
            refs: JsonObject = {"validation_id": item.validation_id}
            idempotency_cursor = connection.execute(
                """
                UPDATE idempotency_records SET status='COMPLETED',
                       result_entity_references=?
                 WHERE scope_id=? AND tool_name='validate_experiment' AND operation_id=?
                   AND status='IN_PROGRESS' AND canonical_request_hash=?
                """,
                (
                    _json(refs),
                    row["project_id"],
                    command.operation.operation_id,
                    command.operation.canonical_request_hash,
                ),
            )
            if idempotency_cursor.rowcount != 1:
                raise ProjectStoreError(
                    "INTEGRITY_FAILURE",
                    "validation idempotency completion was rejected",
                    False,
                    {"subject": "database_relation"},
                )
            return StoredValidationResult(
                validation=item,
                report_artifact=command.report_artifact,
            )

    def recover_previous_session(
        self, current_session_id: str, recovered_at: datetime
    ) -> RecoveryReport:
        """Atomically converge active rows left by an earlier writer session."""
        if not self._schema_two:
            raise ProjectStoreError(
                "UNSUPPORTED_VERSION",
                "startup recovery requires database schema 2",
                False,
                {"subject": "database_schema"},
            )
        recovered_attempts: tuple[str, ...] = ()
        recovered_validations: tuple[str, ...] = ()
        integrity_failures: tuple[str, ...] = ()
        with self._write(degrade_on_failure=True) as connection:
            active_attempts = connection.execute(
                """
                SELECT a.attempt_id, a.experiment_id, e.project_id
                  FROM attempts a
                  JOIN experiments e ON e.experiment_id=a.experiment_id
                 WHERE a.status IN ('PENDING', 'RUNNING')
                   AND a.session_id<>?
                 ORDER BY a.attempt_id
                """,
                (current_session_id,),
            ).fetchall()
            live_attempts = connection.execute(
                """
                SELECT attempt_id FROM attempts
                 WHERE status IN ('PENDING', 'RUNNING') AND session_id=?
                """,
                (current_session_id,),
            ).fetchall()
            run_operations = connection.execute(
                """
                SELECT scope_id, operation_id FROM idempotency_records
                 WHERE tool_name='run_experiment' AND status='IN_PROGRESS'
                 ORDER BY operation_id
                """
            ).fetchall()
            if active_attempts or (run_operations and not live_attempts):
                valid_pair = (
                    len(active_attempts) == 1
                    and len(run_operations) == 1
                    and active_attempts[0]["project_id"]
                    == run_operations[0]["scope_id"]
                )
                if not valid_pair:
                    integrity_failures = tuple(
                        sorted(
                            {
                                *(row["attempt_id"] for row in active_attempts),
                                *(row["operation_id"] for row in run_operations),
                            },
                            key=lambda item: item.encode("utf-8"),
                        )
                    )
                    self._degraded = True
                else:
                    attempt_id = active_attempts[0]["attempt_id"]
                    operation_id = run_operations[0]["operation_id"]
                    connection.execute(
                        """
                        UPDATE attempts
                           SET status='ABANDONED', finished_at=?,
                               terminal_reason='server_recovery'
                         WHERE attempt_id=? AND status IN ('PENDING', 'RUNNING')
                        """,
                        (_timestamp(recovered_at), attempt_id),
                    )
                    references: JsonObject = {
                        "experiment_id": active_attempts[0]["experiment_id"],
                        "attempt_id": attempt_id,
                    }
                    connection.execute(
                        """
                        UPDATE idempotency_records
                           SET status='COMPLETED', result_entity_references=?
                         WHERE scope_id=? AND tool_name='run_experiment'
                           AND operation_id=? AND status='IN_PROGRESS'
                        """,
                        (
                            _json(references),
                            active_attempts[0]["project_id"],
                            operation_id,
                        ),
                    )
                    recovered_attempts = (attempt_id,)
            active_validations = connection.execute(
                """
                SELECT v.validation_id, e.project_id
                  FROM validations v
                  JOIN attempts a ON a.attempt_id=v.attempt_id
                  JOIN experiments e ON e.experiment_id=a.experiment_id
                 WHERE v.status IN ('PENDING', 'RUNNING')
                 ORDER BY v.validation_id
                """
            ).fetchall()
            validation_operations = connection.execute(
                """
                SELECT scope_id, operation_id FROM idempotency_records
                 WHERE tool_name='validate_experiment' AND status='IN_PROGRESS'
                 ORDER BY operation_id
                """
            ).fetchall()
            if active_validations or validation_operations:
                valid_pair = (
                    len(active_validations) == 1
                    and len(validation_operations) == 1
                    and active_validations[0]["project_id"]
                    == validation_operations[0]["scope_id"]
                )
                if not valid_pair:
                    integrity_failures = tuple(
                        sorted(
                            {
                                *integrity_failures,
                                *(row["validation_id"] for row in active_validations),
                                *(row["operation_id"] for row in validation_operations),
                            },
                            key=lambda item: item.encode("utf-8"),
                        )
                    )
                    self._degraded = True
                else:
                    validation_id = active_validations[0]["validation_id"]
                    operation_id = validation_operations[0]["operation_id"]
                    connection.execute(
                        """
                        UPDATE validations
                           SET status='ABANDONED', finished_at=?,
                               terminal_reason='server_recovery'
                         WHERE validation_id=?
                           AND status IN ('PENDING', 'RUNNING')
                        """,
                        (_timestamp(recovered_at), validation_id),
                    )
                    references = {"validation_id": validation_id}
                    connection.execute(
                        """
                        UPDATE idempotency_records
                           SET status='COMPLETED', result_entity_references=?
                         WHERE scope_id=? AND tool_name='validate_experiment'
                           AND operation_id=? AND status='IN_PROGRESS'
                        """,
                        (
                            _json(references),
                            active_validations[0]["project_id"],
                            operation_id,
                        ),
                    )
                    recovered_validations = (validation_id,)
        return RecoveryReport(
            recovered_attempt_ids=recovered_attempts,
            recovered_validation_ids=recovered_validations,
            integrity_failure_ids=integrity_failures,
        )

    def inspect_integrity(self, deep: bool) -> StoreIntegrityReport:
        inspection = self.inspect_project_state()
        if inspection.state is ProjectState.DEGRADED:
            return StoreIntegrityReport(
                state=ProjectState.DEGRADED, issues=("project_state",)
            )
        if inspection.state is ProjectState.UNINITIALIZED:
            return StoreIntegrityReport(state=inspection.state, issues=())
        mode: Literal["quick", "integrity"] = "integrity" if deep else "quick"
        check: StoreIntegrityCheck | None = None
        issues: list[StoreIntegrityIssue] = []
        legacy_attempts: tuple[LegacyAttempt, ...] = ()
        legacy_validations: tuple[LegacyValidation, ...] = ()
        legacy_operations: tuple[LegacyIdempotencyRecord, ...] = ()
        referenced_artifact_ids: tuple[str, ...] = ()
        input_drift_ids: tuple[str, ...] = ()
        recovered_entity_ids: tuple[str, ...] = ()
        reproducibility_metadata_issue_ids: tuple[str, ...] = ()
        artifact_inspection = None
        try:
            with self._read() as connection:
                try:
                    raw_check_rows = connection.execute(
                        f"PRAGMA {mode}_check"
                    ).fetchall()
                except (
                    ProjectStoreError,
                    OSError,
                    sqlite3.DatabaseError,
                    TypeError,
                    ValueError,
                ):
                    check = StoreIntegrityCheck(mode=mode, outcome="ERROR")
                    issues.append("database_relation")
                else:
                    exact_ok = False
                    if type(raw_check_rows) is list and len(raw_check_rows) == 1:
                        row = raw_check_rows[0]
                        if isinstance(row, (tuple, sqlite3.Row)):
                            exact_ok = len(row) == 1 and row[0] == "ok"
                    if exact_ok:
                        check = StoreIntegrityCheck(mode=mode, outcome="PASS")
                    else:
                        check = StoreIntegrityCheck(mode=mode, outcome="FAIL")
                        issues.append(
                            "sqlite_integrity_check" if deep else "sqlite_quick_check"
                        )

                try:
                    foreign_key_row = connection.execute(
                        "PRAGMA foreign_key_check"
                    ).fetchone()
                except (
                    ProjectStoreError,
                    OSError,
                    sqlite3.DatabaseError,
                    TypeError,
                    ValueError,
                ):
                    issues.append("database_relation")
                else:
                    if foreign_key_row is not None:
                        issues.append("foreign_key")

                try:
                    rows = connection.execute(
                        """
                        SELECT attempt_id, status
                          FROM attempts
                         WHERE status IN ('PENDING','RUNNING')
                         ORDER BY status COLLATE BINARY, attempt_id COLLATE BINARY
                         LIMIT 101
                        """
                    ).fetchall()
                    attempt_records = tuple(
                        LegacyAttempt(row[0], row[1]) for row in rows
                    )
                    legacy_attempts = StoreIntegrityReport(
                        state=inspection.state,
                        issues=(),
                        legacy_attempts=attempt_records,
                    ).legacy_attempts
                except (
                    ProjectStoreError,
                    OSError,
                    sqlite3.DatabaseError,
                    IndexError,
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    issues.append("database_relation")
                else:
                    if legacy_attempts:
                        issues.append("stale_attempt")

                try:
                    rows = connection.execute(
                        """
                        SELECT validation_id, status
                          FROM validations
                         WHERE status IN ('PENDING','RUNNING')
                         ORDER BY status COLLATE BINARY, validation_id COLLATE BINARY
                         LIMIT 101
                        """
                    ).fetchall()
                    validation_records = tuple(
                        LegacyValidation(row[0], row[1]) for row in rows
                    )
                    legacy_validations = StoreIntegrityReport(
                        state=inspection.state,
                        issues=(),
                        legacy_validations=validation_records,
                    ).legacy_validations
                except (
                    ProjectStoreError,
                    OSError,
                    sqlite3.DatabaseError,
                    IndexError,
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    issues.append("database_relation")
                else:
                    if legacy_validations:
                        issues.append("stale_validation")

                try:
                    rows = connection.execute(
                        """
                        SELECT scope_id, tool_name, operation_id, status
                          FROM idempotency_records
                         WHERE status='IN_PROGRESS'
                         ORDER BY scope_id COLLATE BINARY,
                                  tool_name COLLATE BINARY,
                                  operation_id COLLATE BINARY
                         LIMIT 101
                        """
                    ).fetchall()
                    operation_records = tuple(
                        LegacyIdempotencyRecord(row[0], row[1], row[2], row[3])
                        for row in rows
                    )
                    legacy_operations = StoreIntegrityReport(
                        state=inspection.state,
                        issues=(),
                        legacy_idempotency_records=operation_records,
                    ).legacy_idempotency_records
                except (
                    ProjectStoreError,
                    OSError,
                    sqlite3.DatabaseError,
                    IndexError,
                    KeyError,
                    TypeError,
                    ValueError,
                ):
                    issues.append("database_relation")
                else:
                    if legacy_operations:
                        issues.append("stale_operation")
                if self._versions.database_schema_version == 2 and deep:
                    try:
                        referenced_artifact_ids = tuple(
                            row[0]
                            for row in connection.execute(
                                """
                                SELECT result_artifact_id FROM result_snapshots
                                UNION
                                SELECT report_artifact_id FROM validations
                                 WHERE report_artifact_id IS NOT NULL
                                ORDER BY 1 COLLATE BINARY
                                """
                            ).fetchall()
                        )
                        artifact_schema_version = (
                            self._versions.result_schema_version.rsplit("/", 1)[1]
                        )
                        result_schema_id = (
                            "https://schemas.math-modeling-mcp.local/common/"
                            f"{artifact_schema_version}/modeling-result.schema.json"
                        )
                        report_schema_id = (
                            "https://schemas.math-modeling-mcp.local/common/"
                            f"{artifact_schema_version}/"
                            "modeling-validation-report.schema.json"
                        )
                        invalid_artifact_relation = connection.execute(
                            """
                            SELECT 1
                              FROM attempts AS a
                         LEFT JOIN result_snapshots AS r
                                ON r.attempt_id=a.attempt_id
                         LEFT JOIN artifacts AS art
                                ON art.artifact_id=r.result_artifact_id
                             WHERE (a.status IN ('SUCCEEDED','NUMERICAL_FAILURE')
                                    AND r.result_snapshot_id IS NULL)
                                OR (a.status NOT IN ('SUCCEEDED','NUMERICAL_FAILURE')
                                    AND r.result_snapshot_id IS NOT NULL)
                                OR (r.result_snapshot_id IS NOT NULL AND (
                                       r.result_hash<>r.result_artifact_id
                                       OR art.artifact_id IS NULL
                                       OR art.sha256<>r.result_artifact_id
                                       OR art.role<>'result'
                                       OR art.media_type<>'application/json'
                                       OR art.schema_id<>?
                                   ))
                            UNION ALL
                            SELECT 1
                              FROM validations AS v
                         LEFT JOIN result_snapshots AS r
                                ON r.attempt_id=v.attempt_id
                         LEFT JOIN artifacts AS art
                                ON art.artifact_id=v.report_artifact_id
                             WHERE r.result_hash IS NULL
                                OR v.expected_result_hash<>v.result_hash
                                OR v.result_hash<>r.result_hash
                                OR (v.status='SUCCEEDED' AND (
                                       v.validation_report_hash IS NULL
                                       OR v.report_artifact_id IS NULL
                                   ))
                                OR ((v.validation_report_hash IS NULL)
                                    <> (v.report_artifact_id IS NULL))
                                OR (v.report_artifact_id IS NOT NULL AND (
                                       v.validation_report_hash<>v.report_artifact_id
                                       OR art.artifact_id IS NULL
                                       OR art.sha256<>v.report_artifact_id
                                       OR art.role<>'validation_report'
                                       OR art.media_type<>'application/json'
                                       OR art.schema_id<>?
                                   ))
                             LIMIT 1
                            """,
                            (result_schema_id, report_schema_id),
                        ).fetchone()
                        input_drift_ids = tuple(
                            row[0]
                            for row in connection.execute(
                                """
                                SELECT e.experiment_id
                                  FROM experiments AS e
                                  JOIN input_snapshots AS i
                                    ON i.input_snapshot_id=e.input_snapshot_id
                                 WHERE e.canonical_input_schema_version<>i.canonical_input_schema_version
                                    OR e.canonical_payload_hash<>i.canonical_payload_hash
                                    OR e.model_snapshot_hash<>i.model_snapshot_hash
                                    OR e.data_snapshot_references<>i.data_snapshot_references
                                    OR e.data_snapshot_set_hash<>i.data_snapshot_set_hash
                                 ORDER BY e.experiment_id COLLATE BINARY
                                 LIMIT 100
                                """
                            ).fetchall()
                        )
                        recovered_entity_ids = tuple(
                            row[0]
                            for row in connection.execute(
                                """
                                SELECT attempt_id FROM attempts
                                 WHERE status='ABANDONED' AND terminal_reason='server_recovery'
                                UNION
                                SELECT validation_id FROM validations
                                 WHERE status='ABANDONED' AND terminal_reason='server_recovery'
                                ORDER BY 1 COLLATE BINARY
                                LIMIT 100
                                """
                            ).fetchall()
                        )
                        reproducibility_metadata_issue_ids = tuple(
                            row[0]
                            for row in connection.execute(
                                """
                                SELECT a.attempt_id
                                  FROM attempts AS a
                                  JOIN experiments AS e
                                    ON e.experiment_id=a.experiment_id
                                 WHERE e.capability_id='numerical.root_finding'
                                   AND (a.randomness<>'not_used' OR a.seed IS NOT NULL
                                        OR a.implementation_id=''
                                        OR a.implementation_version='')
                                 ORDER BY a.attempt_id COLLATE BINARY
                                 LIMIT 100
                                """
                            ).fetchall()
                        )
                    except (sqlite3.DatabaseError, IndexError, TypeError, ValueError):
                        issues.append("database_relation")
                    else:
                        if invalid_artifact_relation is not None:
                            issues.append("artifact_reference")
                        if input_drift_ids:
                            issues.append("input_drift")
                        if reproducibility_metadata_issue_ids:
                            issues.append("reproducibility_metadata")
            if (
                self._versions.database_schema_version == 2
                and deep
                and self._artifact_store
            ):
                try:
                    artifact_inspection = self._artifact_store.inspect(
                        frozenset(referenced_artifact_ids)
                    )
                except Exception:
                    issues.append("artifact_reference")
                else:
                    if artifact_inspection.missing_artifacts:
                        issues.append("artifact_reference")
        except (ProjectStoreError, OSError, sqlite3.DatabaseError, ValueError):
            check = StoreIntegrityCheck(mode=mode, outcome="ERROR")
            issues = ["database_relation"]
            legacy_attempts = ()
            legacy_validations = ()
            legacy_operations = ()
            referenced_artifact_ids = ()
            input_drift_ids = ()
            recovered_entity_ids = ()
            reproducibility_metadata_issue_ids = ()
            artifact_inspection = None
        return StoreIntegrityReport(
            state=ProjectState.DEGRADED if issues else inspection.state,
            issues=tuple(sorted(set(issues), key=lambda item: item.encode("utf-8"))),
            check=check,
            legacy_attempts=legacy_attempts,
            legacy_validations=legacy_validations,
            legacy_idempotency_records=legacy_operations,
            artifact_inspection=artifact_inspection,
            input_drift_ids=input_drift_ids,
            recovered_entity_ids=recovered_entity_ids,
            reproducibility_metadata_issue_ids=reproducibility_metadata_issue_ids,
        )


if TYPE_CHECKING:
    _project_store_contract: ProjectStore = SQLiteProjectStore(Path(), VersionSet.m1a())


__all__ = ["SQLiteProjectStore"]
