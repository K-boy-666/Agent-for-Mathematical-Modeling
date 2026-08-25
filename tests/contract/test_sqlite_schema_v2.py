"""B4 contract tests for SQLite schema v2.

These tests are RED until schema_v2.sql is created and _create_database
routes to the correct schema file based on VersionSet.database_schema_version.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from modeling_core.contracts.versions import VersionSet
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import (
    StorageError,
    bootstrap_storage,
)

# ---------------------------------------------------------------------------
# Expected schema v2 tables
# ---------------------------------------------------------------------------

EXPECTED_V2_TABLES = {
    "metadata",
    "projects",
    "input_snapshots",
    "experiments",
    "environment_snapshots",
    "attempts",
    "result_snapshots",
    "artifacts",
    "validations",
    "idempotency_records",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_tables(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return {row[0] for row in rows}


def _get_foreign_keys_for_table(
    connection: sqlite3.Connection, table: str
) -> list[tuple[str, str, str]]:
    """Return list of (from_col, ref_table, ref_col) for a table."""
    rows = connection.execute(f"PRAGMA foreign_key_list({table!r})").fetchall()
    return [(row[3], row[2], row[4]) for row in rows]


# ===================================================================
# Test: schema v2 tables
# ===================================================================


class TestSchemaV2Tables:
    """Verify schema v2 has exactly the expected 10 tables."""

    def test_m1b_bootstrap_creates_user_version_2(self, tmp_path: Path) -> None:
        metadata = bootstrap_storage(tmp_path, VersionSet.m1b())
        assert metadata.database_schema_version == 2
        assert metadata.created is True

    def test_schema_v2_has_exactly_ten_tables(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            tables = _get_tables(connection)
            # sqlite_stat* tables are excluded
            tables = {t for t in tables if not t.startswith("sqlite_")}

        assert tables == EXPECTED_V2_TABLES, (
            f"Expected exactly 10 tables, got {len(tables)}: {sorted(tables)}"
        )

    def test_input_snapshots_table_exists(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            tables = _get_tables(connection)
        assert "input_snapshots" in tables

    def test_environment_snapshots_table_exists(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            tables = _get_tables(connection)
        assert "environment_snapshots" in tables

    def test_artifacts_table_exists(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            tables = _get_tables(connection)
        assert "artifacts" in tables

    def test_artifacts_has_expected_columns(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            info = connection.execute("PRAGMA table_info('artifacts')").fetchall()

        column_names = {row[1] for row in info}
        assert column_names == {
            "artifact_id",
            "role",
            "media_type",
            "byte_size",
            "sha256",
            "schema_id",
            "created_at",
        }

    def test_result_snapshots_has_result_artifact_id_column(
        self, tmp_path: Path
    ) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            info = connection.execute(
                "PRAGMA table_info('result_snapshots')"
            ).fetchall()

        column_names = {row[1] for row in info}
        assert "result_artifact_id" in column_names
        assert "result_payload_json" not in column_names, (
            "result_payload_json must be removed from result_snapshots in v2"
        )

    def test_validations_has_report_artifact_id_column(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            info = connection.execute("PRAGMA table_info('validations')").fetchall()

        column_names = {row[1] for row in info}
        assert "report_artifact_id" in column_names
        assert "report_payload_json" not in column_names, (
            "report_payload_json must be removed from validations in v2"
        )

    def test_attempts_has_session_id_column(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            info = connection.execute("PRAGMA table_info('attempts')").fetchall()

        column_names = {row[1] for row in info}
        assert "session_id" in column_names


# ===================================================================
# Test: foreign keys
# ===================================================================


class TestSchemaV2ForeignKeys:
    """Verify artifact foreign keys are declared and enforced."""

    def test_result_artifact_id_fk_declared(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            fks = _get_foreign_keys_for_table(connection, "result_snapshots")

        fk_targets = {
            (from_col, ref_table, ref_col) for from_col, ref_table, ref_col in fks
        }
        assert ("result_artifact_id", "artifacts", "artifact_id") in fk_targets, (
            f"result_artifact_id FK not found in result_snapshots. Found: {fk_targets}"
        )

    def test_report_artifact_id_fk_declared(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            fks = _get_foreign_keys_for_table(connection, "validations")

        fk_targets = {
            (from_col, ref_table, ref_col) for from_col, ref_table, ref_col in fks
        }
        assert ("report_artifact_id", "artifacts", "artifact_id") in fk_targets, (
            f"report_artifact_id FK not found in validations. Found: {fk_targets}"
        )

    def test_dangling_result_artifact_id_rejected(self, tmp_path: Path) -> None:
        """Inserting a result_snapshot with non-existent artifact_id must fail."""
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")

            # Insert minimal required rows: project, input_snapshot, experiment, attempt
            connection.execute(
                "INSERT INTO projects(project_id, storage_instance_id, "
                "project_format_version, display_name, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000001",
                    "00000000-0000-4000-8000-000000000002",
                    "modeling-project/1.0.0",
                    "test",
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO input_snapshots(input_snapshot_id, "
                "canonical_input_schema_version, canonical_payload_hash, "
                "model_snapshot_hash, data_snapshot_references, "
                "data_snapshot_set_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000009",
                    "numerical.root_finding.canonical-input/1.0.0",
                    "sha256:" + "0" * 64,
                    "sha256:" + "0" * 64,
                    "[]",
                    "sha256:" + "0" * 64,
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO experiments(experiment_id, project_id, capability_id, "
                "contract_version, canonical_input_schema_version, canonical_payload, "
                "canonical_payload_hash, canonicalization_version, model_snapshot_hash, "
                "data_snapshot_references, data_snapshot_set_hash, execution_policy, "
                "input_snapshot_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000003",
                    "00000000-0000-4000-8000-000000000001",
                    "numerical.root_finding",
                    "1.0.0",
                    "numerical.root_finding.canonical-input/1.0.0",
                    "{}",
                    "sha256:" + "0" * 64,
                    "canonical-json/1.0.0",
                    "sha256:" + "0" * 64,
                    "[]",
                    "sha256:" + "0" * 64,
                    "{}",
                    "00000000-0000-4000-8000-000000000009",
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO environment_snapshots(environment_snapshot_id, "
                "environment_json, environment_hash, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000008",
                    "{}",
                    "sha256:" + "0" * 64,
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO attempts(attempt_id, experiment_id, implementation_id, "
                "implementation_version, environment_summary, randomness, seed, "
                "session_id, input_snapshot_id, environment_snapshot_id, "
                "status, created_at, warnings) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000004",
                    "00000000-0000-4000-8000-000000000003",
                    "echo",
                    "1.0.0",
                    "{}",
                    "none",
                    None,
                    "00000000-0000-4000-8000-000000000007",
                    "00000000-0000-4000-8000-000000000009",
                    "00000000-0000-4000-8000-000000000008",
                    "SUCCEEDED",
                    "2026-08-17T00:00:00.000Z",
                    "[]",
                ),
            )
            connection.commit()

            # Now try to insert a result_snapshot referencing a non-existent artifact
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO result_snapshots(result_snapshot_id, attempt_id, "
                    "result_kind, result_schema_version, result_hash, "
                    "result_artifact_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "00000000-0000-4000-8000-000000000005",
                        "00000000-0000-4000-8000-000000000004",
                        "success",
                        "modeling-result/0.1.0",
                        "sha256:" + "0" * 64,
                        "sha256:" + "f" * 64,  # nonexistent
                    ),
                )

    def test_dangling_report_artifact_id_rejected(self, tmp_path: Path) -> None:
        """Inserting a validation with non-existent report_artifact_id must fail."""
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")

            # Insert minimal required rows
            connection.execute(
                "INSERT INTO projects(project_id, storage_instance_id, "
                "project_format_version, display_name, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000001",
                    "00000000-0000-4000-8000-000000000002",
                    "modeling-project/1.0.0",
                    "test",
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO input_snapshots(input_snapshot_id, "
                "canonical_input_schema_version, canonical_payload_hash, "
                "model_snapshot_hash, data_snapshot_references, "
                "data_snapshot_set_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000009",
                    "numerical.root_finding.canonical-input/1.0.0",
                    "sha256:" + "0" * 64,
                    "sha256:" + "0" * 64,
                    "[]",
                    "sha256:" + "0" * 64,
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO experiments(experiment_id, project_id, capability_id, "
                "contract_version, canonical_input_schema_version, canonical_payload, "
                "canonical_payload_hash, canonicalization_version, model_snapshot_hash, "
                "data_snapshot_references, data_snapshot_set_hash, execution_policy, "
                "input_snapshot_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000003",
                    "00000000-0000-4000-8000-000000000001",
                    "numerical.root_finding",
                    "1.0.0",
                    "numerical.root_finding.canonical-input/1.0.0",
                    "{}",
                    "sha256:" + "0" * 64,
                    "canonical-json/1.0.0",
                    "sha256:" + "0" * 64,
                    "[]",
                    "sha256:" + "0" * 64,
                    "{}",
                    "00000000-0000-4000-8000-000000000009",
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO environment_snapshots(environment_snapshot_id, "
                "environment_json, environment_hash, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000008",
                    "{}",
                    "sha256:" + "0" * 64,
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO attempts(attempt_id, experiment_id, implementation_id, "
                "implementation_version, environment_summary, randomness, seed, "
                "session_id, input_snapshot_id, environment_snapshot_id, "
                "status, created_at, warnings) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000004",
                    "00000000-0000-4000-8000-000000000003",
                    "echo",
                    "1.0.0",
                    "{}",
                    "none",
                    None,
                    "00000000-0000-4000-8000-000000000007",
                    "00000000-0000-4000-8000-000000000009",
                    "00000000-0000-4000-8000-000000000008",
                    "SUCCEEDED",
                    "2026-08-17T00:00:00.000Z",
                    "[]",
                ),
            )
            connection.commit()

            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO validations(validation_id, attempt_id, "
                    "expected_result_hash, result_hash, validator_id, "
                    "validator_implementation_id, validator_implementation_version, "
                    "policy_version, policy, policy_hash, status, created_at, "
                    "report_artifact_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        "00000000-0000-4000-8000-000000000006",
                        "00000000-0000-4000-8000-000000000004",
                        "sha256:" + "0" * 64,
                        "sha256:" + "0" * 64,
                        "echo",
                        "echo",
                        "1.0.0",
                        "1.0.0",
                        "{}",
                        "sha256:" + "0" * 64,
                        "SUCCEEDED",
                        "2026-08-17T00:00:00.000Z",
                        "sha256:" + "f" * 64,  # nonexistent
                    ),
                )


# ===================================================================
# Test: unique constraints
# ===================================================================


class TestSchemaV2UniqueConstraints:
    """Verify that schema v2 enforces appropriate uniqueness."""

    def test_result_snapshots_attempt_id_unique(self, tmp_path: Path) -> None:
        """Each attempt_id must have at most one result_snapshot."""
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")

            # Set up minimal data
            connection.execute(
                "INSERT INTO projects(project_id, storage_instance_id, "
                "project_format_version, display_name, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000001",
                    "00000000-0000-4000-8000-000000000002",
                    "modeling-project/1.0.0",
                    "test",
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO input_snapshots(input_snapshot_id, "
                "canonical_input_schema_version, canonical_payload_hash, "
                "model_snapshot_hash, data_snapshot_references, "
                "data_snapshot_set_hash, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000009",
                    "numerical.root_finding.canonical-input/1.0.0",
                    "sha256:" + "0" * 64,
                    "sha256:" + "0" * 64,
                    "[]",
                    "sha256:" + "0" * 64,
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO experiments(experiment_id, project_id, capability_id, "
                "contract_version, canonical_input_schema_version, canonical_payload, "
                "canonical_payload_hash, canonicalization_version, model_snapshot_hash, "
                "data_snapshot_references, data_snapshot_set_hash, execution_policy, "
                "input_snapshot_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000003",
                    "00000000-0000-4000-8000-000000000001",
                    "numerical.root_finding",
                    "1.0.0",
                    "numerical.root_finding.canonical-input/1.0.0",
                    "{}",
                    "sha256:" + "0" * 64,
                    "canonical-json/1.0.0",
                    "sha256:" + "0" * 64,
                    "[]",
                    "sha256:" + "0" * 64,
                    "{}",
                    "00000000-0000-4000-8000-000000000009",
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO environment_snapshots(environment_snapshot_id, "
                "environment_json, environment_hash, created_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000008",
                    "{}",
                    "sha256:" + "0" * 64,
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO attempts(attempt_id, experiment_id, implementation_id, "
                "implementation_version, environment_summary, randomness, seed, "
                "session_id, input_snapshot_id, environment_snapshot_id, "
                "status, created_at, warnings) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000004",
                    "00000000-0000-4000-8000-000000000003",
                    "echo",
                    "1.0.0",
                    "{}",
                    "none",
                    None,
                    "00000000-0000-4000-8000-000000000007",
                    "00000000-0000-4000-8000-000000000009",
                    "00000000-0000-4000-8000-000000000008",
                    "SUCCEEDED",
                    "2026-08-17T00:00:00.000Z",
                    "[]",
                ),
            )
            # Insert an artifact for the result
            connection.execute(
                "INSERT INTO artifacts(artifact_id, role, media_type, byte_size, "
                "sha256, schema_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "sha256:" + "0" * 64,
                    "result",
                    "application/json",
                    0,
                    "sha256:" + "0" * 64,
                    "modeling-result/0.1.0",
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.commit()

            # First insert should succeed
            connection.execute(
                "INSERT INTO result_snapshots(result_snapshot_id, attempt_id, "
                "result_kind, result_schema_version, result_hash, "
                "result_artifact_id) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000005",
                    "00000000-0000-4000-8000-000000000004",
                    "success",
                    "modeling-result/0.1.0",
                    "sha256:" + "0" * 64,
                    "sha256:" + "0" * 64,
                ),
            )
            connection.commit()

            # Second insert with same attempt_id must fail
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO result_snapshots(result_snapshot_id, attempt_id, "
                    "result_kind, result_schema_version, result_hash, "
                    "result_artifact_id) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "00000000-0000-4000-8000-000000000006",
                        "00000000-0000-4000-8000-000000000004",  # same attempt_id
                        "success",
                        "modeling-result/0.1.0",
                        "sha256:" + "0" * 64,
                        "sha256:" + "1" * 64,
                    ),
                )

    def test_artifacts_sha256_unique(self, tmp_path: Path) -> None:
        """Each artifact must have a unique sha256."""
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")

            connection.execute(
                "INSERT INTO artifacts(artifact_id, role, media_type, byte_size, "
                "sha256, schema_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    "sha256:" + "0" * 64,
                    "result",
                    "application/json",
                    0,
                    "sha256:" + "0" * 64,
                    "modeling-result/0.1.0",
                    "2026-08-17T00:00:00.000Z",
                ),
            )
            connection.commit()

            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO artifacts(artifact_id, role, media_type, byte_size, "
                    "sha256, schema_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        "sha256:" + "1" * 64,
                        "report",
                        "application/json",
                        0,
                        "sha256:" + "0" * 64,  # same sha256, different artifact_id
                        "modeling-validation-report/1.0.0",
                        "2026-08-17T00:00:00.000Z",
                    ),
                )

    def test_idempotency_records_scope_tool_operation_unique(
        self, tmp_path: Path
    ) -> None:
        """(scope_id, tool_name, operation_id) must be unique."""
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                "INSERT INTO idempotency_records(scope_id, tool_name, operation_id, "
                "canonical_request_hash, status, result_entity_references) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    "00000000-0000-4000-8000-000000000001",
                    "run_experiment",
                    "00000000-0000-4000-8000-000000000008",
                    "sha256:" + "0" * 64,
                    "IN_PROGRESS",
                    "[]",
                ),
            )
            connection.commit()

            with pytest.raises(sqlite3.IntegrityError):
                connection.execute(
                    "INSERT INTO idempotency_records(scope_id, tool_name, operation_id, "
                    "canonical_request_hash, status, result_entity_references) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "00000000-0000-4000-8000-000000000001",
                        "run_experiment",
                        "00000000-0000-4000-8000-000000000008",  # same triple
                        "sha256:" + "0" * 64,
                        "COMPLETED",
                        "[]",
                    ),
                )


# ===================================================================
# Test: pragmas
# ===================================================================


class TestSchemaV2Pragmas:
    """Verify required pragmas are set on schema v2 databases."""

    def test_user_version_is_2(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            user_version = connection.execute("PRAGMA user_version").fetchone()[0]

        assert user_version == 2

    def test_foreign_keys_is_on(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        store = SQLiteProjectStore(tmp_path, VersionSet.m1b())

        with closing(store._connect()) as connection:
            foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]

        assert foreign_keys == 1

    def test_journal_mode_is_wal(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            journal_mode = connection.execute("PRAGMA journal_mode").fetchone()[0]

        assert journal_mode == "wal"

    def test_synchronous_is_full(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            synchronous = connection.execute("PRAGMA synchronous").fetchone()[0]

        assert synchronous == 2

    def test_busy_timeout_is_250(self, tmp_path: Path) -> None:
        bootstrap_storage(tmp_path, VersionSet.m1b())
        store = SQLiteProjectStore(tmp_path, VersionSet.m1b())

        with closing(store._connect()) as connection:
            busy_timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]

        assert busy_timeout == 250


# ===================================================================
# Test: version rejection
# ===================================================================


class TestSchemaV2VersionRejection:
    """Verify that user_version 1 and 3 are rejected by M1b bootstrap."""

    def test_m1a_database_rejected_by_m1b_bootstrap(self, tmp_path: Path) -> None:
        """An M1a database (user_version=1) must not be accepted as M1b."""
        bootstrap_storage(tmp_path, VersionSet.m1a())

        with pytest.raises(StorageError) as captured:
            bootstrap_storage(tmp_path, VersionSet.m1b())

        # user_version=1 < database_schema_version=2 → UNSUPPORTED_VERSION
        assert captured.value.code == "UNSUPPORTED_VERSION"

    def test_user_version_3_rejected_as_unsupported(self, tmp_path: Path) -> None:
        """A database with user_version=3 must raise UNSUPPORTED_VERSION."""
        bootstrap_storage(tmp_path, VersionSet.m1b())
        database = tmp_path / ".modeling" / "state.sqlite3"

        with closing(sqlite3.connect(database)) as connection:
            connection.execute("PRAGMA user_version=3")
            connection.commit()

        with pytest.raises(StorageError) as captured:
            bootstrap_storage(tmp_path, VersionSet.m1b())

        assert captured.value.code == "UNSUPPORTED_VERSION"
        assert captured.value.details is not None
        assert "requested_version" in captured.value.details
        assert captured.value.details["requested_version"] == "3"

    def test_m1b_fresh_bootstrap_does_not_produce_m1a_database(
        self, tmp_path: Path
    ) -> None:
        """A fresh M1b bootstrap must yield user_version=2, not 1."""
        metadata = bootstrap_storage(tmp_path, VersionSet.m1b())
        assert metadata.database_schema_version == 2
        assert metadata.database_schema_version != 1
