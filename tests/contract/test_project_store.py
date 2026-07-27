from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from modeling_core.contracts.versions import VersionSet
from modeling_core.domain.states import ProjectState
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import bootstrap_storage


EXPECTED_TABLES = {
    "metadata",
    "projects",
    "experiments",
    "attempts",
    "result_snapshots",
    "validations",
    "idempotency_records",
}

REQUIRED_COLUMNS = {
    "metadata": {"key", "value"},
    "projects": {
        "project_id",
        "storage_instance_id",
        "project_format_version",
        "display_name",
        "created_at",
    },
    "experiments": {
        "experiment_id",
        "project_id",
        "capability_id",
        "contract_version",
        "canonical_input_schema_version",
        "canonical_payload",
        "canonical_payload_hash",
        "model_snapshot_hash",
        "data_snapshot_references",
        "data_snapshot_set_hash",
        "execution_policy",
        "created_at",
    },
    "attempts": {
        "attempt_id",
        "experiment_id",
        "implementation_id",
        "implementation_version",
        "environment_summary",
        "randomness",
        "seed",
        "session_id",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "warnings",
        "system_error",
        "numerical_failure",
        "terminal_reason",
    },
    "result_snapshots": {
        "result_snapshot_id",
        "attempt_id",
        "result_kind",
        "result_schema_version",
        "result_hash",
        "result_payload_json",
    },
    "validations": {
        "validation_id",
        "attempt_id",
        "expected_result_hash",
        "result_hash",
        "validator_id",
        "validator_implementation_id",
        "validator_implementation_version",
        "policy_version",
        "policy",
        "policy_hash",
        "status",
        "created_at",
        "started_at",
        "finished_at",
        "outcome",
        "metrics",
        "validation_report_hash",
        "report_payload_json",
        "operational_error",
        "terminal_reason",
    },
    "idempotency_records": {
        "scope_id",
        "tool_name",
        "operation_id",
        "canonical_request_hash",
        "status",
        "result_entity_references",
    },
}


def _database(project_root: Path) -> Path:
    return project_root / ".modeling" / "state.sqlite3"


def test_schema_one_has_required_tables_columns_foreign_keys_and_unique_key(
    tmp_path: Path,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())

    with closing(sqlite3.connect(_database(tmp_path))) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert tables == EXPECTED_TABLES

        for table, expected_columns in REQUIRED_COLUMNS.items():
            actual_columns = {
                row[1] for row in connection.execute(f"PRAGMA table_info({table})")
            }
            assert expected_columns <= actual_columns

        foreign_keys = {
            table: {
                (row[2], row[3], row[4])
                for row in connection.execute(f"PRAGMA foreign_key_list({table})")
            }
            for table in (
                "experiments",
                "attempts",
                "result_snapshots",
                "validations",
            )
        }
        assert foreign_keys == {
            "experiments": {("projects", "project_id", "project_id")},
            "attempts": {("experiments", "experiment_id", "experiment_id")},
            "result_snapshots": {("attempts", "attempt_id", "attempt_id")},
            "validations": {("attempts", "attempt_id", "attempt_id")},
        }

        indexes = connection.execute("PRAGMA index_list(idempotency_records)").fetchall()
        unique_columns = {
            tuple(
                row[2]
                for row in connection.execute(f"PRAGMA index_info({index[1]})")
            )
            for index in indexes
            if index[2] == 1
        }
        assert ("scope_id", "tool_name", "operation_id") in unique_columns


def test_schema_constraints_reject_invalid_entity_ids_and_hashes(
    tmp_path: Path,
) -> None:
    metadata = bootstrap_storage(tmp_path, VersionSet.m1a())

    with closing(sqlite3.connect(_database(tmp_path))) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO projects (
                    project_id, storage_instance_id, project_format_version,
                    display_name, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    "invalid",
                    metadata.storage_instance_id,
                    "modeling-project/0.1.0",
                    "bad id",
                    "2026-07-17T00:00:00.000Z",
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO idempotency_records (
                    scope_id, tool_name, operation_id, canonical_request_hash,
                    status, result_entity_references
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    metadata.storage_instance_id,
                    "create_project",
                    "00000000-0000-4000-8000-000000000001",
                    "not-a-hash",
                    "COMPLETED",
                    "{}",
                ),
            )


def test_storage_ready_has_no_project_domain_row(tmp_path: Path) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    store = SQLiteProjectStore(tmp_path, VersionSet.m1a())

    inspection = store.inspect_project_state()

    assert inspection.state is ProjectState.STORAGE_READY
    assert inspection.project is None
    with closing(sqlite3.connect(_database(tmp_path))) as connection:
        assert connection.execute("SELECT COUNT(*) FROM projects").fetchone() == (0,)


def test_project_metadata_matches_the_shipped_draft_2020_12_schema(
    tmp_path: Path,
) -> None:
    bootstrap_storage(tmp_path, VersionSet.m1a())
    schema_path = (
        Path(__file__).parents[2]
        / "src"
        / "modeling_core"
        / "contracts"
        / "schemas"
        / "common"
        / "0.1.0"
        / "modeling-project.schema.json"
    )
    instance_path = tmp_path / ".modeling" / "project.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    instance = json.loads(instance_path.read_text(encoding="utf-8"))

    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(instance)
