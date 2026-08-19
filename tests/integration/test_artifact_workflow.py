"""B5 integration test: the artifact-backed M1b traceability chain.

The explicitly composed M1b application persists immutable input and
environment snapshots, publishes result/report bytes as content-addressed
artifacts before their database references, and rereads committed results
through verified storage before validation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator

import pytest
from pydantic import ValidationError

from modeling_capabilities.root_finding.solver import (
    BisectionRootFindingCapability,
)
from modeling_capabilities.root_finding.validator import (
    ResidualRootFindingValidator,
)
from modeling_core.application import ModelingApplication
from modeling_core.application.idempotency import (
    run_experiment_request_hash,
    validate_experiment_request_hash,
)
from modeling_core.contracts.canonical_json import (
    canonical_json_bytes,
    sha256_json,
)
from modeling_core.contracts.errors import ModelingError
from modeling_core.contracts.tools import (
    CapabilitySelection,
    CreateProjectRequest,
    EnvironmentSummary,
    ExecutionOptions,
    GetProjectStatusExperimentRequest,
    GetProjectStatusSummaryRequest,
    RootFindingInput,
    RunExperimentRequest,
    RunExperimentSucceededResult,
    ValidateExperimentRequest,
    ValidateExperimentSucceededResult,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.registry import CapabilityRegistry
from modeling_infrastructure.artifacts.store import ContentAddressedArtifactStore
from modeling_infrastructure.environment import capture_environment_snapshot
from modeling_infrastructure.project_paths import ProjectPaths
from modeling_infrastructure.sqlite.store import SQLiteProjectStore
from modeling_infrastructure.storage import bootstrap_storage

# Fixed canonical-JSON vectors from design section 8.5.
EMPTY_DATA_SET_HASH = (
    "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
)
EMPTY_POLICY_HASH = (
    "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
)
ENVIRONMENT_ALLOWLIST_KEYS = frozenset(
    {
        "python_version",
        "uv_version",
        "os_name",
        "os_version",
        "architecture",
        "application_version",
        "lock_hash",
        "capability_versions",
        "validator_versions",
        "numerical_libraries",
        "locale",
    }
)


class FakeClock:
    def __init__(self, start: datetime, monotonic_start: float = 0.0) -> None:
        self._now = start
        self._monotonic = monotonic_start

    def utc_now(self) -> datetime:
        return self._now

    def monotonic(self) -> float:
        return self._monotonic

    def advance(self, seconds: float) -> None:
        self._now += timedelta(seconds=seconds)
        self._monotonic += seconds


class FixedIdGenerator:
    def __init__(self, values: Iterable[str]) -> None:
        self._values: Iterator[str] = iter(values)

    def new_uuid4(self) -> str:
        return next(self._values)


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


def _uuid(index: int) -> str:
    return f"00000000-0000-4000-8000-{index:012x}"


def _m1b_versions() -> VersionSet:
    """M1a contract axes with the M1b database schema and artifact layer."""
    return VersionSet.m1a().model_copy(update={"database_schema_version": 2})


def _build_m1b_application(
    project_root: Path,
    *,
    id_start: int = 100,
    clock_start: datetime | None = None,
) -> tuple[ModelingApplication, SQLiteProjectStore]:
    versions = _m1b_versions()
    lock_file = project_root / "uv.lock"
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_bytes(b"m1b-artifact-workflow-lock")
    bootstrap_storage(project_root, versions)
    capability = BisectionRootFindingCapability()
    validator = ResidualRootFindingValidator()
    registry = CapabilityRegistry(versions)
    registry.register_capability(capability)
    registry.register_validator(validator)
    registry_summary = registry.seal(frozenset())
    artifact_store = ContentAddressedArtifactStore(ProjectPaths.bind(project_root))
    store = SQLiteProjectStore(
        project_root,
        versions,
        FakeClock(clock_start or datetime(2026, 8, 17, tzinfo=UTC)),
        FixedIdGenerator(_uuid(index) for index in range(id_start, id_start + 500)),
        session_id=_uuid(90),
        artifact_store=artifact_store,
    )
    application = ModelingApplication(
        store=store,
        registry=registry,
        registry_summary=registry_summary,
        versions=versions,
        clock=FakeClock(clock_start or datetime(2026, 8, 17, tzinfo=UTC)),
        id_generator=FixedIdGenerator(
            _uuid(index) for index in range(id_start, id_start + 500)
        ),
        session_id=_uuid(90),
        environment_summary=EnvironmentSummary(
            python_version="3.11.14",
            application_version="0.1.0",
            lock_hash="sha256:" + ("1" * 64),
        ),
        cancellation=_NeverCancelled(),
        default_display_name="artifact workflow",
        artifact_store=artifact_store,
        environment_document=capture_environment_snapshot(
            lock_file=lock_file,
            capability_descriptor=capability.descriptor,
            validator_descriptor=validator.descriptor,
        ),
    )
    return application, store


def _run_request(project_id: str, operation_index: int) -> RunExperimentRequest:
    return RunExperimentRequest(
        operation_id=_uuid(operation_index),
        project_id=project_id,
        mode="new",
        capability=CapabilitySelection(
            capability_id="numerical.root_finding",
            contract_version="0.1.0",
        ),
        payload=RootFindingInput(expression="x*x - 2", lower=0.0, upper=2.0),
    )


def _artifact_path(project_root: Path, artifact_id: str) -> Path:
    full_hex = artifact_id.removeprefix("sha256:")
    return (
        project_root
        / ".modeling"
        / "artifacts"
        / "sha256"
        / full_hex[:2]
        / f"{full_hex}.json"
    )


def _encode_cursor(document: dict[str, object]) -> str:
    return (
        base64.urlsafe_b64encode(canonical_json_bytes(document))
        .decode("ascii")
        .rstrip("=")
    )


def _rows(connection: sqlite3.Connection, sql: str, parameters: tuple = ()) -> list:
    return connection.execute(sql, parameters).fetchall()


def test_artifact_workflow_persists_full_traceability_chain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches missing snapshots, artifact references or named-hash drift."""
    application, _store = _build_m1b_application(tmp_path)
    project = application.create_project(CreateProjectRequest(operation_id=_uuid(1)))
    request = _run_request(project.project_id, 2)

    observed_before_execution: list[tuple[int, int, int]] = []
    original_execute = BisectionRootFindingCapability.execute

    def probed_execute(
        self: BisectionRootFindingCapability,
        canonical: object,
        context: object,
    ) -> object:
        database = tmp_path / ".modeling" / "state.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            observed_before_execution.append(
                (
                    connection.execute(
                        "SELECT COUNT(*) FROM input_snapshots"
                    ).fetchone()[0],
                    connection.execute(
                        "SELECT COUNT(*) FROM environment_snapshots"
                    ).fetchone()[0],
                    connection.execute("SELECT COUNT(*) FROM attempts").fetchone()[0],
                )
            )
        return original_execute(self, canonical, context)  # type: ignore[arg-type]

    monkeypatch.setattr(BisectionRootFindingCapability, "execute", probed_execute)

    run = application.run_experiment(request)
    assert isinstance(run, RunExperimentSucceededResult)
    validation = application.validate_experiment(
        ValidateExperimentRequest(
            operation_id=_uuid(3),
            project_id=project.project_id,
            attempt_id=run.attempt_id,
            expected_result_hash=run.result_hash,
            validator_id="numerical.root_finding.residual",
            policy_version="0.1.0",
            policy={},
        )
    )
    assert isinstance(validation, ValidateExperimentSucceededResult)

    # 3. snapshots, experiment and attempt exist before execution started.
    assert observed_before_execution == [(1, 1, 1)]

    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        connection.row_factory = sqlite3.Row
        input_snapshot = connection.execute("SELECT * FROM input_snapshots").fetchone()
        environment_snapshot = connection.execute(
            "SELECT * FROM environment_snapshots"
        ).fetchone()
        experiment = connection.execute("SELECT * FROM experiments").fetchone()
        attempt = connection.execute("SELECT * FROM attempts").fetchone()
        artifacts = connection.execute(
            "SELECT * FROM artifacts ORDER BY role"
        ).fetchall()
        result_snapshot = connection.execute(
            "SELECT * FROM result_snapshots"
        ).fetchone()
        validation_row = connection.execute("SELECT * FROM validations").fetchone()
        run_idem = connection.execute(
            "SELECT canonical_request_hash, status FROM idempotency_records "
            "WHERE tool_name='run_experiment'"
        ).fetchone()
        validate_idem = connection.execute(
            "SELECT canonical_request_hash, status FROM idempotency_records "
            "WHERE tool_name='validate_experiment'"
        ).fetchone()
        result_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info('result_snapshots')")
        }
        validation_columns = {
            row[1] for row in connection.execute("PRAGMA table_info('validations')")
        }

    # 1. one of each snapshot entity, wired by foreign keys.
    assert input_snapshot is not None
    assert environment_snapshot is not None
    assert experiment["input_snapshot_id"] == input_snapshot["input_snapshot_id"]
    assert attempt["input_snapshot_id"] == input_snapshot["input_snapshot_id"]
    assert (
        attempt["environment_snapshot_id"]
        == (environment_snapshot["environment_snapshot_id"])
    )
    assert attempt["experiment_id"] == experiment["experiment_id"]
    assert attempt["randomness"] == "not_used"
    assert attempt["seed"] is None

    # 6. no result/report payload is duplicated inline in SQLite v2.
    assert "result_payload_json" not in result_columns
    assert "report_payload_json" not in validation_columns

    # 2. every named hash recomputes from its exact canonical byte domain.
    canonical_payload = json.loads(experiment["canonical_payload"])
    assert experiment["canonical_payload_hash"] == sha256_json(canonical_payload)
    assert experiment["model_snapshot_hash"] == sha256_json(
        {"language": "math-expr-v1", "ast": canonical_payload["expression_ast"]}
    )
    assert experiment["data_snapshot_set_hash"] == EMPTY_DATA_SET_HASH
    assert (
        input_snapshot["canonical_payload_hash"]
        == (experiment["canonical_payload_hash"])
    )
    assert input_snapshot["model_snapshot_hash"] == experiment["model_snapshot_hash"]
    assert input_snapshot["data_snapshot_set_hash"] == EMPTY_DATA_SET_HASH
    assert validation_row["policy_hash"] == EMPTY_POLICY_HASH

    capability = BisectionRootFindingCapability()
    canonical = capability.normalize_and_validate(
        RootFindingInput(expression="x*x - 2", lower=0.0, upper=2.0).model_dump(
            mode="json"
        )
    )
    assert run_idem["canonical_request_hash"] == run_experiment_request_hash(
        project_id=project.project_id,
        mode="new",
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        canonical_input=canonical,
        execution=ExecutionOptions(),
    )
    assert run_idem["status"] == "COMPLETED"
    assert validate_idem["canonical_request_hash"] == validate_experiment_request_hash(
        project_id=project.project_id,
        attempt_id=run.attempt_id,
        expected_result_hash=run.result_hash,
        validator_id="numerical.root_finding.residual",
        policy_version="0.1.0",
        policy={},
        timeout_ms=10000,
    )
    assert validate_idem["status"] == "COMPLETED"

    # 4. exactly one result artifact and one validation report artifact.
    assert [row["role"] for row in artifacts] == ["result", "validation_report"]
    result_artifact, report_artifact = artifacts

    # 5. manifest, artifact row, foreign key and file agree on identity.
    assert result_artifact["artifact_id"] == result_artifact["sha256"]
    assert result_artifact["artifact_id"] == result_snapshot["result_artifact_id"]
    assert result_artifact["artifact_id"] == result_snapshot["result_hash"]
    assert result_artifact["artifact_id"] == run.result_hash
    assert result_artifact["media_type"] == "application/json"
    assert report_artifact["artifact_id"] == report_artifact["sha256"]
    assert report_artifact["artifact_id"] == validation_row["report_artifact_id"]
    assert report_artifact["artifact_id"] == validation_row["validation_report_hash"]
    assert report_artifact["artifact_id"] == validation.validation_report_hash
    assert report_artifact["media_type"] == "application/json"

    result_path = _artifact_path(tmp_path, result_artifact["artifact_id"])
    report_path = _artifact_path(tmp_path, report_artifact["artifact_id"])
    assert result_path.is_file()
    assert report_path.is_file()
    result_bytes = result_path.read_bytes()
    report_bytes = report_path.read_bytes()
    assert len(result_bytes) == result_artifact["byte_size"]
    assert len(report_bytes) == report_artifact["byte_size"]
    assert (
        "sha256:" + hashlib.sha256(result_bytes).hexdigest()
        == result_artifact["artifact_id"]
    )
    assert (
        "sha256:" + hashlib.sha256(report_bytes).hexdigest()
        == report_artifact["artifact_id"]
    )
    result_document = json.loads(result_bytes)
    report_document = json.loads(report_bytes)
    assert canonical_json_bytes(result_document) == result_bytes
    assert canonical_json_bytes(report_document) == report_bytes
    assert sha256_json(result_document) == result_snapshot["result_hash"]
    assert sha256_json(report_document) == validation_row["validation_report_hash"]
    assert result_document["result_kind"] == "success"
    assert result_document["result_schema_version"] == "modeling-result/0.1.0"
    assert report_document["report_schema_version"] == (
        "modeling-validation-report/0.1.0"
    )

    # 8. the persisted environment snapshot is exactly the allowlist.
    environment_document = json.loads(environment_snapshot["environment_json"])
    assert frozenset(environment_document) == ENVIRONMENT_ALLOWLIST_KEYS
    assert environment_snapshot["environment_hash"] == sha256_json(environment_document)
    assert environment_document["application_version"] == "0.1.0"
    assert (
        environment_document["lock_hash"]
        == "sha256:" + hashlib.sha256((tmp_path / "uv.lock").read_bytes()).hexdigest()
    )
    assert environment_document["capability_versions"] == [
        {
            "capability_id": "numerical.root_finding",
            "contract_version": "0.1.0",
            "implementation_id": "builtin.numerical.root_finding.bisection",
            "implementation_version": "0.1.0",
            "canonical_input_schema_hash": (
                capability.descriptor.canonical_input_schema.schema_hash
            ),
            "input_schema_hash": capability.descriptor.input_schema.schema_hash,
            "success_schema_hash": capability.descriptor.success_schema.schema_hash,
            "failure_schema_hash": capability.descriptor.failure_schema.schema_hash,
        }
    ]
    assert environment_document["validator_versions"] == [
        {
            "validator_id": "numerical.root_finding.residual",
            "policy_version": "0.1.0",
            "implementation_id": "builtin.numerical.root_finding.residual",
            "implementation_version": "0.1.0",
        }
    ]
    libraries = environment_document["numerical_libraries"]
    assert libraries == sorted(libraries, key=lambda item: item["name"])
    assert all(set(item) == {"name", "version"} for item in libraries)


def test_environment_snapshot_excludes_sensitive_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Catches username, hostname, paths or secrets entering persisted state."""
    monkeypatch.setenv("USERNAME", "secret-username")
    monkeypatch.setenv("COMPUTERNAME", "secret-hostname")
    monkeypatch.setenv("MODELING_SECRET_TOKEN", "secret-token-value")
    lock_file = tmp_path / "uv.lock"
    lock_file.write_bytes(b"lock")

    document = capture_environment_snapshot(
        lock_file=lock_file,
        capability_descriptor=BisectionRootFindingCapability().descriptor,
        validator_descriptor=ResidualRootFindingValidator().descriptor,
    )
    serialized = canonical_json_bytes(document).decode("utf-8")

    assert frozenset(document) == ENVIRONMENT_ALLOWLIST_KEYS
    assert "secret-username" not in serialized
    assert "secret-hostname" not in serialized
    assert "secret-token-value" not in serialized
    assert str(lock_file.resolve()) not in serialized
    assert "USERNAME" not in serialized
    assert "COMPUTERNAME" not in serialized
    assert os.environ.get("PATH", "") not in serialized


@pytest.mark.parametrize(
    "tamper",
    ["overwrite_file", "delete_file", "corrupt_row_hash"],
)
def test_validator_rereads_committed_result_and_rejects_tampering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tamper: str,
) -> None:
    """Catches validation trusting solver-held or caller-supplied payloads."""
    application, _store = _build_m1b_application(tmp_path)
    project = application.create_project(CreateProjectRequest(operation_id=_uuid(1)))
    run = application.run_experiment(_run_request(project.project_id, 2))
    assert isinstance(run, RunExperimentSucceededResult)

    result_path = _artifact_path(tmp_path, run.result_hash)
    assert result_path.is_file()
    if tamper == "overwrite_file":
        forged = json.loads(result_path.read_bytes())
        forged["data"]["root"] = forged["data"]["root"] + 1.0
        result_path.write_bytes(canonical_json_bytes(forged))
    elif tamper == "delete_file":
        result_path.unlink()
    else:
        database = tmp_path / ".modeling" / "state.sqlite3"
        with closing(sqlite3.connect(database)) as connection:
            connection.execute(
                "UPDATE artifacts SET sha256=? WHERE artifact_id=?",
                ("sha256:" + ("e" * 64), run.result_hash),
            )
            connection.commit()

    def forbidden(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("validator executed on unverified result bytes")

    monkeypatch.setattr(ResidualRootFindingValidator, "validate", forbidden)
    with pytest.raises(ModelingError) as captured:
        application.validate_experiment(
            ValidateExperimentRequest(
                operation_id=_uuid(3),
                project_id=project.project_id,
                attempt_id=run.attempt_id,
                expected_result_hash=run.result_hash,
                validator_id="numerical.root_finding.residual",
                policy_version="0.1.0",
                policy={},
            )
        )
    assert captured.value.response.code == "INTEGRITY_FAILURE"
    assert captured.value.response.details.subject == "result_artifact"


def test_failed_final_commit_leaves_orphan_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches error handling deleting published but unreferenced artifacts."""
    from modeling_core.ports.project_store import ProjectStoreError

    application, store = _build_m1b_application(tmp_path)
    project = application.create_project(CreateProjectRequest(operation_id=_uuid(1)))

    def fail(*_args: object, **_kwargs: object) -> object:
        raise ProjectStoreError(
            "INTEGRITY_FAILURE",
            "injected final transaction failure",
            False,
            {"subject": "database_relation"},
        )

    monkeypatch.setattr(store, "complete_attempt", fail)
    with pytest.raises(ModelingError) as captured:
        application.run_experiment(_run_request(project.project_id, 2))
    assert captured.value.response.code == "INTEGRITY_FAILURE"

    artifact_files = sorted(
        (tmp_path / ".modeling" / "artifacts" / "sha256").rglob("*.json")
    )
    assert len(artifact_files) == 1
    database = tmp_path / ".modeling" / "state.sqlite3"
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM artifacts").fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM result_snapshots"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM idempotency_records WHERE tool_name='run_experiment'"
        ).fetchone() == (1,)
    assert artifact_files[0].is_file()


def test_experiment_view_pagination_follows_total_order(
    tmp_path: Path,
) -> None:
    """Catches duplicate, omitted or misordered trace records per section 11.5."""
    application, _store = _build_m1b_application(tmp_path)
    project = application.create_project(CreateProjectRequest(operation_id=_uuid(1)))
    run = application.run_experiment(_run_request(project.project_id, 2))
    assert isinstance(run, RunExperimentSucceededResult)
    validation = application.validate_experiment(
        ValidateExperimentRequest(
            operation_id=_uuid(3),
            project_id=project.project_id,
            attempt_id=run.attempt_id,
            expected_result_hash=run.result_hash,
            validator_id="numerical.root_finding.residual",
            policy_version="0.1.0",
            policy={},
        )
    )
    assert isinstance(validation, ValidateExperimentSucceededResult)

    def query(cursor: str | None = None) -> GetProjectStatusExperimentRequest:
        return GetProjectStatusExperimentRequest(
            project_id=project.project_id,
            view="experiment",
            experiment_id=run.experiment_id,
            limit=1,
            cursor=cursor,
        )

    first_page = application.get_project_status(query())
    assert [record.record_type for record in first_page.trace] == ["attempt"]
    assert first_page.next_cursor is not None
    second_page = application.get_project_status(query(first_page.next_cursor))
    assert [record.record_type for record in second_page.trace] == ["validation"]
    assert second_page.next_cursor is None

    # Malformed cursors fail closed.
    for malformed in ("!!!!", "aGVsbG8", "eyJ2aWV3IjogInVubGtub3duIn0"):
        with pytest.raises(ModelingError) as captured:
            application.get_project_status(query(malformed))
        assert captured.value.response.code == "INVALID_REQUEST"
        assert captured.value.response.details.reason == "invalid_cursor"

    # A wrong-view cursor is rejected.
    summary_cursor = _encode_cursor(
        {
            "view": "summary",
            "created_at": "2026-08-17T00:00:00.000Z",
            "experiment_id": run.experiment_id,
        }
    )
    with pytest.raises(ModelingError) as captured:
        application.get_project_status(query(summary_cursor))
    assert captured.value.response.code == "INVALID_REQUEST"
    assert captured.value.response.details.reason == "invalid_cursor"

    # A cursor bound to another project's experiment is rejected.
    other_root = tmp_path / "other-project"
    other_application, _other_store = _build_m1b_application(other_root, id_start=500)
    other_project = other_application.create_project(
        CreateProjectRequest(operation_id=_uuid(600))
    )
    other_run = other_application.run_experiment(
        _run_request(other_project.project_id, 601)
    )
    assert isinstance(other_run, RunExperimentSucceededResult)
    other_application.validate_experiment(
        ValidateExperimentRequest(
            operation_id=_uuid(602),
            project_id=other_project.project_id,
            attempt_id=other_run.attempt_id,
            expected_result_hash=other_run.result_hash,
            validator_id="numerical.root_finding.residual",
            policy_version="0.1.0",
            policy={},
        )
    )
    other_page = other_application.get_project_status(
        GetProjectStatusExperimentRequest(
            project_id=other_project.project_id,
            view="experiment",
            experiment_id=other_run.experiment_id,
            limit=1,
        )
    )
    assert other_page.next_cursor is not None
    with pytest.raises(ModelingError) as captured:
        application.get_project_status(query(other_page.next_cursor))
    assert captured.value.response.code == "INVALID_REQUEST"
    assert captured.value.response.details.reason == "invalid_cursor"

    # Summary view rejects cursor and out-of-range limits forbidden by schema.
    with pytest.raises(ValidationError):
        GetProjectStatusSummaryRequest(
            project_id=project.project_id, view="summary", cursor="opaque"
        )
    with pytest.raises(ValidationError):
        GetProjectStatusSummaryRequest(
            project_id=project.project_id, view="summary", limit=0
        )
    with pytest.raises(ValidationError):
        GetProjectStatusSummaryRequest(
            project_id=project.project_id, view="summary", limit=101
        )
    summary = application.get_project_status(
        GetProjectStatusSummaryRequest(
            project_id=project.project_id, view="summary", limit=100
        )
    )
    assert len(summary.experiments.items) == 1
