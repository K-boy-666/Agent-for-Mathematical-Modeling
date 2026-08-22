from __future__ import annotations

import io
import json
import math
import shutil
import sqlite3
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest
from jsonschema import Draft202012Validator

from modeling_core.contracts.tools import (
    RunExperimentSucceededResult,
    ValidateExperimentSucceededResult,
)
from modeling_core.domain.states import ProjectState
from modeling_core.ports.artifact_store import (
    ArtifactInspectionReport,
    ArtifactManifest,
)
from modeling_core.ports.project_store import (
    LegacyAttempt,
    LegacyIdempotencyRecord,
    LegacyValidation,
    StoreIntegrityCheck,
    StoreIntegrityReport,
    ProjectStoreError,
)
from modeling_infrastructure.diagnostic_snapshot import (
    DiagnosticSnapshot,
    DiagnosticSnapshotError,
)


def _uuid(index: int) -> str:
    return f"10000000-0000-4000-8000-{index:012x}"


class _Application:
    def __init__(self, state: str = "READY", status: str = "OK") -> None:
        self.health = SimpleNamespace(
            status=status,
            project_state=state,
            ready_for_project_creation=state in {"UNINITIALIZED", "STORAGE_READY"},
            registry=SimpleNamespace(sealed=True),
        )
        self.calls: list[str] = []

    def health_check(self, request: object) -> object:
        self.calls.append("health_check")
        return self.health

    def list_capabilities(self, request: object) -> object:
        self.calls.append("list_capabilities")
        return SimpleNamespace(capabilities=(SimpleNamespace(capability_id="root"),))


class _Store:
    def __init__(self, report: StoreIntegrityReport) -> None:
        self.report = report
        self.deep: list[bool] = []

    def inspect_integrity(self, deep: bool) -> StoreIntegrityReport:
        self.deep.append(deep)
        return self.report


def _diagnose(
    state: ProjectState,
    *,
    issues: tuple[str, ...] = (),
    check: StoreIntegrityCheck | None = None,
    attempts: tuple[LegacyAttempt, ...] = (),
    validations: tuple[LegacyValidation, ...] = (),
    operations: tuple[LegacyIdempotencyRecord, ...] = (),
    deep: bool = False,
) -> dict[str, object]:
    from modeling_cli.doctor import diagnose_project

    application = _Application(state.value, "DEGRADED" if issues else "OK")
    store = _Store(
        StoreIntegrityReport(
            state=ProjectState.DEGRADED if issues else state,
            issues=issues,  # type: ignore[arg-type]
            check=check,
            legacy_attempts=attempts,
            legacy_validations=validations,
            legacy_idempotency_records=operations,
        )
    )
    report = diagnose_project(
        application,
        store,
        "UNINITIALIZED" if state is ProjectState.UNINITIALIZED else "INITIALIZED",
        deep,
    )
    assert application.calls == ["health_check", "list_capabilities"]
    assert store.deep == [deep]
    return report


def _checks(report: dict[str, object]) -> dict[str, tuple[str, str]]:
    return {
        item["name"]: (item["status"], item["code"])
        for item in report["checks"]  # type: ignore[union-attr]
    }


def _check_payload(report: dict[str, object], name: str) -> dict[str, str]:
    return next(
        item
        for item in report["checks"]  # type: ignore[union-attr]
        if item["name"] == name
    )


def _doctor_schema_validator() -> Draft202012Validator:
    schema = json.loads(
        files("modeling_cli")
        .joinpath("schemas", "doctor", "0.1.0", "report.schema.json")
        .read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_uninitialized_is_warning_and_storage_ready_and_ready_are_ready() -> None:
    uninitialized = _diagnose(ProjectState.UNINITIALIZED)
    storage_ready = _diagnose(
        ProjectState.STORAGE_READY,
        check=StoreIntegrityCheck("quick", "PASS"),
    )
    ready = _diagnose(
        ProjectState.READY,
        check=StoreIntegrityCheck("quick", "PASS"),
    )

    assert (uninitialized["status"], uninitialized["exit_code"]) == ("WARNING", 1)
    assert uninitialized["ready_for_project_creation"] is True
    assert _checks(uninitialized)["project-state"] == ("WARN", "uninitialized")
    assert _checks(uninitialized)["storage-integrity"] == (
        "PASS",
        "not_initialized",
    )
    assert (storage_ready["status"], storage_ready["exit_code"]) == ("READY", 0)
    assert storage_ready["ready_for_project_creation"] is True
    assert (ready["status"], ready["exit_code"]) == ("READY", 0)
    assert ready["ready_for_project_creation"] is False


def test_schema_assets_reject_a_valid_catalog_with_mutated_fingerprint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modeling_cli import doctor
    from modeling_core.contracts import schema_catalog

    copied_root = tmp_path / "contracts"
    shutil.copytree(
        files("modeling_core.contracts").joinpath("schemas"),
        copied_root / "schemas",
    )
    schema_path = (
        copied_root
        / "schemas"
        / "tools"
        / "0.1.0"
        / "create_project.request.schema.json"
    )
    original = schema_path.read_text(encoding="utf-8")
    mutated = original.replace('"type": "string"', '"type": "number"', 1)
    assert mutated != original
    assert len(mutated.encode()) == len(original.encode())
    Draft202012Validator.check_schema(json.loads(mutated))
    schema_path.write_text(mutated, encoding="utf-8")
    monkeypatch.setattr(schema_catalog, "files", lambda package: copied_root)

    assert doctor._asset_codes()[0] == "hash_mismatch"


def test_degraded_legacy_and_integrity_failures_are_unsafe() -> None:
    report = _diagnose(
        ProjectState.READY,
        issues=(
            "foreign_key",
            "sqlite_quick_check",
            "stale_attempt",
            "stale_operation",
            "stale_validation",
        ),
        check=StoreIntegrityCheck("quick", "FAIL"),
        attempts=(LegacyAttempt(_uuid(1), "PENDING"),),
        validations=(LegacyValidation(_uuid(2), "RUNNING"),),
        operations=(
            LegacyIdempotencyRecord(
                _uuid(3), "run_experiment", _uuid(4), "IN_PROGRESS"
            ),
        ),
    )

    assert (report["status"], report["exit_code"]) == ("UNSAFE", 2)
    assert report["project_state"] == "DEGRADED"
    assert report["ready_for_project_creation"] is False
    checks = _checks(report)
    assert checks["storage-integrity"] == ("FAIL", "check_failed")
    assert checks["foreign-keys"] == ("FAIL", "foreign_key_failure")
    assert checks["legacy-attempts"] == ("FAIL", "stale_attempt")
    assert checks["legacy-validations"] == ("FAIL", "stale_validation")
    assert checks["legacy-operations"] == ("FAIL", "stale_operation")


def test_m1b_findings_distinguish_unsafe_references_from_safe_orphans() -> None:
    """Catches doctor hiding artifact drift or treating safe debris as corruption."""
    artifact = ArtifactManifest(
        artifact_id="sha256:" + "1" * 64,
        role="result",
        media_type="application/json",
        byte_size=2,
        sha256="sha256:" + "1" * 64,
        schema_id="modeling-result/1.0.0",
        created_at="2026-08-22T00:00:00.000Z",
    )
    application = _Application("READY", "DEGRADED")
    store = _Store(
        StoreIntegrityReport(
            state=ProjectState.DEGRADED,
            issues=("artifact_reference", "input_drift"),
            check=StoreIntegrityCheck("integrity", "PASS"),
            artifact_inspection=ArtifactInspectionReport(
                referenced_artifact_ids=(artifact.artifact_id,),
                present_artifacts=(),
                missing_artifacts=(artifact.artifact_id,),
                orphan_artifacts=(artifact,),
                staging_files=("previous-session.json",),
            ),
            input_drift_ids=(_uuid(20),),
            recovered_entity_ids=(_uuid(21),),
            reproducibility_metadata_issue_ids=(),
        )
    )

    from modeling_cli.doctor import diagnose_project

    report = diagnose_project(application, store, "INITIALIZED", True)
    checks = _checks(report)

    assert (report["status"], report["exit_code"]) == ("UNSAFE", 2)
    assert checks["artifact_references"] == ("FAIL", "missing_or_tampered")
    assert checks["input_drift"] == ("FAIL", "detected")
    assert checks["recovery_state"] == ("PASS", "recovered")
    assert checks["orphan_artifacts"] == ("WARN", "present")
    assert checks["staging_files"] == ("WARN", "present")
    assert checks["reproducibility_metadata"] == ("PASS", "complete")
    assert report["warnings"] == ["orphan_artifacts", "staging_files"]
    assert report["unsafe_findings"] == ["artifact_references", "input_drift"]


def test_doctor_uses_shared_facade_and_store_without_starting_inspected_composition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modeling_cli import doctor

    events: list[str] = []
    application = _Application("STORAGE_READY")
    store = _Store(
        StoreIntegrityReport(
            state=ProjectState.STORAGE_READY,
            issues=(),
            check=StoreIntegrityCheck("quick", "PASS"),
        )
    )

    class Composition:
        def __init__(self) -> None:
            self.application = application
            self.store = store

        def start(self) -> None:
            raise AssertionError("inspected composition must not start")

        def close(self) -> None:
            events.append("composition-close")

    @contextmanager
    def snapshot(_: Path) -> Iterator[DiagnosticSnapshot]:
        yield DiagnosticSnapshot(tmp_path / "owned", "INITIALIZED")
        events.append("snapshot-exit")

    monkeypatch.setattr(doctor, "materialize_diagnostic_snapshot", snapshot)
    monkeypatch.setattr(
        doctor, "build_composition", lambda root, **kwargs: Composition()
    )
    stdout = io.StringIO()

    code = doctor.run_doctor(tmp_path, deep=False, json_output=True, stdout=stdout)

    assert code == 0
    assert json.loads(stdout.getvalue())["status"] == "READY"
    assert events == ["composition-close", "snapshot-exit"]


@pytest.mark.parametrize(
    ("code", "root_check"),
    [
        ("snapshot_unstable", ("PASS", "available")),
        ("snapshot_invalid", ("FAIL", "unsafe")),
        ("snapshot_resource_limit", ("PASS", "available")),
        ("snapshot_unavailable", ("FAIL", "unreadable")),
        ("snapshot_cleanup_failed", ("PASS", "available")),
    ],
)
def test_all_snapshot_failure_codes_map_to_empty_redacted_pre_store_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    root_check: tuple[str, str],
) -> None:
    from modeling_cli import doctor

    @contextmanager
    def failed(_: Path) -> Iterator[DiagnosticSnapshot]:
        raise DiagnosticSnapshotError(code)  # type: ignore[arg-type]
        yield

    monkeypatch.setattr(doctor, "materialize_diagnostic_snapshot", failed)
    stdout = io.StringIO()
    secret = str(tmp_path / "credential-secret")

    exit_code = doctor.run_doctor(
        Path(secret), deep=False, json_output=True, stdout=stdout
    )

    report = json.loads(stdout.getvalue())
    assert exit_code == 2
    assert _checks(report)["project-root"] == root_check
    assert _checks(report)["storage-integrity"] == ("FAIL", code)
    assert report["storage"] == {
        "check": None,
        "issues": [],
        "legacy_attempts": [],
        "legacy_validations": [],
        "legacy_idempotency_records": [],
        "m1b": {
            "referenced_artifact_ids": [],
            "missing_artifact_ids": [],
            "orphan_artifact_ids": [],
            "staging_files": [],
            "input_drift_ids": [],
            "recovered_entity_ids": [],
            "reproducibility_metadata_issue_ids": [],
        },
    }
    assert secret not in stdout.getvalue()


def test_unexpected_doctor_error_maps_to_fixed_redacted_check_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modeling_cli import doctor

    secret = "credential-super-secret"

    @contextmanager
    def failed(_: Path) -> Iterator[DiagnosticSnapshot]:
        raise RuntimeError(secret)
        yield

    monkeypatch.setattr(doctor, "materialize_diagnostic_snapshot", failed)
    stdout = io.StringIO()

    assert doctor.run_doctor(tmp_path, False, True, stdout=stdout) == 2
    assert _checks(json.loads(stdout.getvalue()))["storage-integrity"] == (
        "FAIL",
        "check_error",
    )
    assert secret not in stdout.getvalue()


def test_doctor_schema_is_strict_versioned_finite_and_packaged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modeling_cli import doctor

    monkeypatch.setattr(doctor, "_run_deep_smoke", lambda: ("passed", "passed"))
    schema_asset = files("modeling_cli").joinpath(
        "schemas", "doctor", "0.1.0", "report.schema.json"
    )
    schema = json.loads(schema_asset.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == (
        "https://schemas.math-modeling-mcp.local/cli/doctor/0.1.0/report.schema.json"
    )
    assert schema["additionalProperties"] is False

    report = _diagnose(
        ProjectState.STORAGE_READY,
        check=StoreIntegrityCheck("quick", "PASS"),
        deep=True,
    )
    Draft202012Validator(schema).validate(report)
    invalid = dict(report)
    invalid["secret"] = "leak"
    assert list(Draft202012Validator(schema).iter_errors(invalid))
    invalid_status = json.loads(json.dumps(report))
    invalid_status["checks"][0]["status"] = "FAIL"
    assert list(Draft202012Validator(schema).iter_errors(invalid_status))
    inconsistent = json.loads(json.dumps(report))
    inconsistent["checks"][0].update(status="FAIL", code="unsafe")
    assert list(Draft202012Validator(schema).iter_errors(inconsistent))
    inconsistent_state = json.loads(json.dumps(report))
    inconsistent_state["project_state"] = "DEGRADED"
    assert list(Draft202012Validator(schema).iter_errors(inconsistent_state))

    repository = Path(__file__).parents[2]
    packaged_config = (
        files("modeling_cli").joinpath("templates", "codex", "config.toml").read_bytes()
    )
    assert (
        packaged_config
        == (repository / "docs/templates/codex/config.toml").read_bytes()
    )


def test_doctor_schema_rejects_cross_field_state_status_and_check_mutations() -> None:
    schema = json.loads(
        files("modeling_cli")
        .joinpath("schemas", "doctor", "0.1.0", "report.schema.json")
        .read_text(encoding="utf-8")
    )
    validator = Draft202012Validator(schema)
    ready = _diagnose(
        ProjectState.STORAGE_READY,
        check=StoreIntegrityCheck("quick", "PASS"),
    )
    warning = _diagnose(ProjectState.UNINITIALIZED)

    ready_with_warn = json.loads(json.dumps(ready))
    ready_with_warn["checks"][1].update(status="WARN", code="uninitialized")
    ready_state_check_mismatch = json.loads(json.dumps(ready))
    ready_state_check_mismatch["project_state"] = "READY"
    ready_state_check_mismatch["ready_for_project_creation"] = False
    ready_flag_mismatch = json.loads(json.dumps(ready))
    ready_flag_mismatch["ready_for_project_creation"] = False
    warning_with_fail = json.loads(json.dumps(warning))
    warning_with_fail["checks"][2].update(status="FAIL", code="degraded")
    unsafe_with_warn = json.loads(json.dumps(warning))
    unsafe_with_warn.update(
        status="UNSAFE",
        exit_code=2,
        project_state="DEGRADED",
        ready_for_project_creation=False,
    )
    unsafe_with_warn["checks"][9].update(status="FAIL", code="unavailable")

    for mutated in (
        ready_with_warn,
        ready_state_check_mismatch,
        ready_flag_mismatch,
        warning_with_fail,
        unsafe_with_warn,
    ):
        assert list(validator.iter_errors(mutated))


@pytest.mark.parametrize(
    "mutation",
    [
        "check-outcome",
        "issues",
        "attempts",
        "validations",
        "operations",
    ],
)
def test_doctor_schema_rejects_ready_store_contradictions(mutation: str) -> None:
    validator = _doctor_schema_validator()
    report = _diagnose(
        ProjectState.READY,
        check=StoreIntegrityCheck("quick", "PASS"),
    )
    storage = report["storage"]
    assert isinstance(storage, dict)

    if mutation == "check-outcome":
        storage["check"]["outcome"] = "FAIL"
    elif mutation == "issues":
        storage["issues"] = ["foreign_key"]
    elif mutation == "attempts":
        storage["legacy_attempts"] = [{"attempt_id": _uuid(20), "status": "PENDING"}]
    elif mutation == "validations":
        storage["legacy_validations"] = [
            {"validation_id": _uuid(21), "status": "RUNNING"}
        ]
    elif mutation == "operations":
        storage["legacy_idempotency_records"] = [
            {
                "scope_id": _uuid(22),
                "tool_name": "run_experiment",
                "operation_id": _uuid(23),
                "status": "IN_PROGRESS",
            }
        ]
    assert list(validator.iter_errors(report))


@pytest.mark.parametrize(
    "mutation",
    [
        "check",
        "issues",
        "attempts",
        "validations",
        "operations",
        "storage-code",
        "foreign-code",
        "attempts-code",
        "validations-code",
        "operations-code",
    ],
)
def test_doctor_schema_rejects_uninitialized_store_contradictions(
    mutation: str,
) -> None:
    validator = _doctor_schema_validator()
    report = _diagnose(ProjectState.UNINITIALIZED)
    storage = report["storage"]
    assert isinstance(storage, dict)

    if mutation == "check":
        storage["check"] = {"mode": "quick", "outcome": "PASS"}
    elif mutation == "issues":
        storage["issues"] = ["foreign_key"]
    elif mutation == "attempts":
        storage["legacy_attempts"] = [{"attempt_id": _uuid(30), "status": "PENDING"}]
    elif mutation == "validations":
        storage["legacy_validations"] = [
            {"validation_id": _uuid(31), "status": "RUNNING"}
        ]
    elif mutation == "operations":
        storage["legacy_idempotency_records"] = [
            {
                "scope_id": _uuid(32),
                "tool_name": "validate_experiment",
                "operation_id": _uuid(33),
                "status": "IN_PROGRESS",
            }
        ]
    else:
        name, code = {
            "storage-code": ("storage-integrity", "ok"),
            "foreign-code": ("foreign-keys", "ok"),
            "attempts-code": ("legacy-attempts", "none"),
            "validations-code": ("legacy-validations", "none"),
            "operations-code": ("legacy-operations", "none"),
        }[mutation]
        _check_payload(report, name).update(code=code)

    assert list(validator.iter_errors(report))


@pytest.mark.parametrize("code", ["snapshot_invalid", "snapshot_unavailable"])
@pytest.mark.parametrize(
    "mutation",
    [
        "root",
        "application",
        "capability",
        "foreign",
        "attempts",
        "validations",
        "operations",
        "storage-check",
        "storage-issues",
        "storage-attempts",
        "storage-validations",
        "storage-operations",
    ],
)
def test_doctor_schema_rejects_snapshot_failure_dependency_contradictions(
    code: str,
    mutation: str,
) -> None:
    from modeling_cli import doctor

    validator = _doctor_schema_validator()
    report = doctor._failure_report(code, deep=False)
    storage = report["storage"]
    assert isinstance(storage, dict)

    if mutation == "root":
        _check_payload(report, "project-root").update(status="PASS", code="available")
    elif mutation == "application":
        _check_payload(report, "application-health").update(
            status="PASS", code="healthy"
        )
    elif mutation == "capability":
        _check_payload(report, "capability-registry").update(
            status="PASS", code="sealed"
        )
    elif mutation in {"foreign", "attempts", "validations", "operations"}:
        name, success_code = {
            "foreign": ("foreign-keys", "ok"),
            "attempts": ("legacy-attempts", "none"),
            "validations": ("legacy-validations", "none"),
            "operations": ("legacy-operations", "none"),
        }[mutation]
        _check_payload(report, name).update(status="PASS", code=success_code)
    elif mutation == "storage-check":
        storage["check"] = {"mode": "quick", "outcome": "PASS"}
    elif mutation == "storage-issues":
        storage["issues"] = ["database_relation"]
    elif mutation == "storage-attempts":
        storage["legacy_attempts"] = [{"attempt_id": _uuid(40), "status": "PENDING"}]
    elif mutation == "storage-validations":
        storage["legacy_validations"] = [
            {"validation_id": _uuid(41), "status": "RUNNING"}
        ]
    else:
        storage["legacy_idempotency_records"] = [
            {
                "scope_id": _uuid(42),
                "tool_name": "run_experiment",
                "operation_id": _uuid(43),
                "status": "IN_PROGRESS",
            }
        ]

    assert list(validator.iter_errors(report))


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("check-outcome", "check_failed"),
        ("storage-code", "check_error"),
        ("foreign-issue", "foreign_key_failure"),
        ("foreign-code", "ok"),
        ("attempts", "stale_attempt"),
        ("attempts-code", "none"),
        ("validations", "stale_validation"),
        ("validations-code", "none"),
        ("operations", "stale_operation"),
        ("operations-code", "none"),
    ],
)
def test_doctor_schema_binds_store_payload_to_corresponding_check_codes(
    mutation: str,
    expected_code: str,
) -> None:
    validator = _doctor_schema_validator()
    report = _diagnose(
        ProjectState.READY,
        issues=(
            "foreign_key",
            "sqlite_quick_check",
            "stale_attempt",
            "stale_operation",
            "stale_validation",
        ),
        check=StoreIntegrityCheck("quick", "FAIL"),
        attempts=(LegacyAttempt(_uuid(50), "PENDING"),),
        validations=(LegacyValidation(_uuid(51), "RUNNING"),),
        operations=(
            LegacyIdempotencyRecord(
                _uuid(52), "run_experiment", _uuid(53), "IN_PROGRESS"
            ),
        ),
    )
    assert not list(validator.iter_errors(report))
    storage = report["storage"]
    assert isinstance(storage, dict)

    if mutation == "check-outcome":
        storage["check"]["outcome"] = "PASS"
    elif mutation == "storage-code":
        _check_payload(report, "storage-integrity")["code"] = expected_code
    elif mutation == "foreign-issue":
        storage["issues"].remove("foreign_key")
    elif mutation == "foreign-code":
        _check_payload(report, "foreign-keys").update(status="PASS", code=expected_code)
    elif mutation in {"attempts", "validations", "operations"}:
        field = {
            "attempts": "legacy_attempts",
            "validations": "legacy_validations",
            "operations": "legacy_idempotency_records",
        }[mutation]
        storage[field] = []
    else:
        name = {
            "attempts-code": "legacy-attempts",
            "validations-code": "legacy-validations",
            "operations-code": "legacy-operations",
        }[mutation]
        _check_payload(report, name).update(status="PASS", code=expected_code)

    assert list(validator.iter_errors(report))


@pytest.mark.parametrize(
    "mutation",
    [
        "fail-keeps-ok",
        "error-keeps-ok",
        "foreign-issue-unavailable",
        "fail-degraded-code",
        "fail-without-sqlite-issue",
        "stale-row-without-issue",
        "stale-row-unavailable",
        "stale-issue-empty-row",
        "error-without-database-issue",
    ],
)
def test_doctor_schema_rejects_reverse_store_mapping_contradictions(
    mutation: str,
) -> None:
    validator = _doctor_schema_validator()
    if mutation in {
        "fail-keeps-ok",
        "error-keeps-ok",
        "foreign-issue-unavailable",
    }:
        report = _diagnose(
            ProjectState.READY,
            issues=("foreign_key",),
            check=StoreIntegrityCheck("quick", "PASS"),
        )
    elif mutation in {"fail-degraded-code", "fail-without-sqlite-issue"}:
        report = _diagnose(
            ProjectState.READY,
            issues=("sqlite_quick_check",),
            check=StoreIntegrityCheck("quick", "FAIL"),
        )
    elif mutation.startswith("stale-"):
        report = _diagnose(
            ProjectState.READY,
            issues=("stale_attempt",),
            check=StoreIntegrityCheck("quick", "PASS"),
            attempts=(LegacyAttempt(_uuid(60), "PENDING"),),
        )
    else:
        report = _diagnose(
            ProjectState.READY,
            issues=("database_relation",),
            check=StoreIntegrityCheck("quick", "ERROR"),
        )
    assert not list(validator.iter_errors(report))
    storage = report["storage"]
    assert isinstance(storage, dict)

    if mutation == "fail-keeps-ok":
        storage["check"]["outcome"] = "FAIL"
    elif mutation == "error-keeps-ok":
        storage["check"]["outcome"] = "ERROR"
    elif mutation == "foreign-issue-unavailable":
        _check_payload(report, "foreign-keys").update(status="FAIL", code="unavailable")
    elif mutation == "fail-degraded-code":
        _check_payload(report, "storage-integrity")["code"] = "not_executed_degraded"
    elif mutation == "fail-without-sqlite-issue":
        storage["issues"] = []
    elif mutation == "stale-row-without-issue":
        storage["issues"] = []
    elif mutation == "stale-row-unavailable":
        _check_payload(report, "legacy-attempts")["code"] = "unavailable"
    elif mutation == "stale-issue-empty-row":
        storage["legacy_attempts"] = []
        _check_payload(report, "legacy-attempts").update(status="PASS", code="none")
    else:
        storage["issues"] = []

    assert list(validator.iter_errors(report))


@pytest.mark.parametrize(
    "check",
    [StoreIntegrityCheck("quick", "PASS"), StoreIntegrityCheck("quick", "ERROR")],
)
def test_doctor_schema_accepts_database_relation_with_completed_or_errored_check(
    check: StoreIntegrityCheck,
) -> None:
    report = _diagnose(
        ProjectState.READY,
        issues=("database_relation",),
        check=check,
    )

    assert not list(_doctor_schema_validator().iter_errors(report))


def test_build_composition_failures_render_one_redacted_unsafe_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modeling_cli import doctor

    @contextmanager
    def snapshot(_: Path) -> Iterator[DiagnosticSnapshot]:
        yield DiagnosticSnapshot(tmp_path / "owned", "INITIALIZED")

    monkeypatch.setattr(doctor, "materialize_diagnostic_snapshot", snapshot)
    monkeypatch.setattr(
        doctor,
        "build_composition",
        lambda root: (_ for _ in ()).throw(RuntimeError("secret-build-error")),
    )
    stdout = io.StringIO()

    assert doctor.run_doctor(tmp_path, False, True, stdout=stdout) == 2
    assert stdout.getvalue().count("\n") == 1
    assert "secret-build-error" not in stdout.getvalue()
    assert _checks(json.loads(stdout.getvalue()))["storage-integrity"] == (
        "FAIL",
        "check_error",
    )


def test_schema_validation_failure_is_stderr_only_and_exit_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modeling_cli import doctor

    monkeypatch.setattr(
        doctor,
        "_validate_report",
        lambda report: (_ for _ in ()).throw(ValueError("schema secret")),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert doctor.run_doctor(tmp_path, False, True, stdout=stdout, stderr=stderr) == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "MODELING_DOCTOR_SCHEMA_INVALID\n"


def test_render_occurs_once_only_after_base_and_deep_context_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modeling_cli import doctor

    events: list[str] = []
    application = _Application("STORAGE_READY")
    store = _Store(
        StoreIntegrityReport(
            state=ProjectState.STORAGE_READY,
            issues=(),
            check=StoreIntegrityCheck("integrity", "PASS"),
        )
    )

    class Composition:
        def __init__(self) -> None:
            self.application = application
            self.store = store

        def close(self) -> None:
            events.append("composition-close")

    @contextmanager
    def snapshot(_: Path) -> Iterator[DiagnosticSnapshot]:
        yield DiagnosticSnapshot(tmp_path / "owned", "INITIALIZED")
        events.append("base-exit")

    monkeypatch.setattr(doctor, "materialize_diagnostic_snapshot", snapshot)
    monkeypatch.setattr(
        doctor, "build_composition", lambda root, **kwargs: Composition()
    )
    monkeypatch.setattr(
        doctor, "_run_deep_smoke", lambda: events.append("deep-exit") or None
    )
    monkeypatch.setattr(
        doctor,
        "_render_report",
        lambda report, json_output, stdout: events.append("render"),
    )

    assert doctor.run_doctor(tmp_path, True, True) == 0
    assert events == ["deep-exit", "composition-close", "base-exit", "render"]


def test_cleanup_failure_discards_ready_report_without_prior_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from modeling_cli import doctor

    application = _Application("STORAGE_READY")
    store = _Store(
        StoreIntegrityReport(
            state=ProjectState.STORAGE_READY,
            issues=(),
            check=StoreIntegrityCheck("quick", "PASS"),
        )
    )

    class Composition:
        def __init__(self) -> None:
            self.application = application
            self.store = store

        def close(self) -> None:
            pass

    @contextmanager
    def snapshot(_: Path) -> Iterator[DiagnosticSnapshot]:
        yield DiagnosticSnapshot(tmp_path / "owned", "INITIALIZED")
        raise DiagnosticSnapshotError("snapshot_cleanup_failed")

    monkeypatch.setattr(doctor, "materialize_diagnostic_snapshot", snapshot)
    monkeypatch.setattr(
        doctor, "build_composition", lambda root, **kwargs: Composition()
    )
    stdout = io.StringIO()

    assert doctor.run_doctor(tmp_path, False, True, stdout=stdout) == 2
    report = json.loads(stdout.getvalue())
    assert report["status"] == "UNSAFE"
    assert _checks(report)["storage-integrity"] == (
        "FAIL",
        "snapshot_cleanup_failed",
    )
    assert stdout.getvalue().count("\n") == 1


@pytest.mark.parametrize(
    "diagnosis_fails", [False, True], ids=["ready", "pending-error"]
)
def test_composition_close_failure_overrides_pending_result_or_error_as_cleanup_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    diagnosis_fails: bool,
) -> None:
    from modeling_cli import doctor

    class Composition:
        application = _Application("STORAGE_READY")
        store = _Store(
            StoreIntegrityReport(
                state=ProjectState.STORAGE_READY,
                issues=(),
                check=StoreIntegrityCheck("quick", "PASS"),
            )
        )

        def close(self) -> None:
            raise OSError("secret composition cleanup")

    @contextmanager
    def snapshot(_: Path) -> Iterator[DiagnosticSnapshot]:
        yield DiagnosticSnapshot(tmp_path / "owned", "INITIALIZED")

    monkeypatch.setattr(doctor, "materialize_diagnostic_snapshot", snapshot)
    monkeypatch.setattr(
        doctor, "build_composition", lambda root, **kwargs: Composition()
    )
    if diagnosis_fails:
        monkeypatch.setattr(
            doctor,
            "diagnose_project",
            lambda *args: (_ for _ in ()).throw(RuntimeError("secret diagnosis")),
        )
    stdout = io.StringIO()

    assert doctor.run_doctor(tmp_path, False, True, stdout=stdout) == 2
    assert _checks(json.loads(stdout.getvalue()))["storage-integrity"] == (
        "FAIL",
        "snapshot_cleanup_failed",
    )
    assert stdout.getvalue().count("\n") == 1
    assert "secret" not in stdout.getvalue()


def test_deep_doctor_runs_owned_root_and_lock_smokes_then_cleans_up(
    tmp_path: Path,
) -> None:
    from modeling_cli.doctor import run_doctor
    from modeling_core.contracts.versions import VersionSet
    from modeling_infrastructure.storage import bootstrap_storage

    bootstrap_storage(tmp_path, VersionSet.m1a())
    stdout = io.StringIO()

    assert run_doctor(tmp_path, True, True, stdout=stdout) == 0
    report = json.loads(stdout.getvalue())
    assert _checks(report)["deep-lock-smoke"] == ("PASS", "passed")
    assert _checks(report)["deep-root-smoke"] == ("PASS", "passed")
    assert not [
        path for path in tmp_path.parent.iterdir() if "doctor-deep" in path.name
    ]


def test_deep_cleanup_attempts_contender_owner_and_root_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from modeling_cli import doctor

    events: list[str] = []

    class Composition:
        def __init__(self, number: int) -> None:
            self.number = number
            self.application = SimpleNamespace(
                create_project=lambda request: SimpleNamespace(project_id=_uuid(90)),
                run_experiment=lambda request: SimpleNamespace(),
            )

        def start(self) -> None:
            if self.number == 2:
                raise RuntimeError("stop after both compositions exist")

        def close(self) -> None:
            events.append(f"close-{self.number}")
            if self.number == 2:
                raise OSError("contender cleanup secret")

    class Temporary:
        name = "C:/doctor-deep-test"

        def cleanup(self) -> None:
            events.append("cleanup-root")

    compositions = iter((Composition(1), Composition(2)))
    monkeypatch.setattr(
        doctor.tempfile, "TemporaryDirectory", lambda **kwargs: Temporary()
    )
    monkeypatch.setattr(doctor, "bootstrap_storage", lambda *args: None)
    monkeypatch.setattr(
        doctor, "build_composition", lambda root, **kwargs: next(compositions)
    )

    with pytest.raises(DiagnosticSnapshotError) as captured:
        doctor._run_deep_smoke()

    assert captured.value.code == "snapshot_cleanup_failed"
    assert events == ["close-2", "close-1", "cleanup-root"]


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        ("root", 1.5, "result_mismatch"),
        ("function_value", math.inf, "result_mismatch"),
        ("root_within_interval", False, "validation_failed"),
        ("reported_function_value", 1.0, "validation_failed"),
        ("recomputed_function_value", 1.0, "validation_failed"),
        ("absolute_reported_delta", 1.0, "validation_failed"),
        ("absolute_residual", 1.0, "validation_failed"),
        ("function_tolerance", 1e-6, "validation_failed"),
        ("failed_checks", ("reported_value_mismatch",), "validation_failed"),
    ],
)
def test_deep_root_smoke_rejects_each_type_correct_wrong_result_field(
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: object,
    expected: str,
) -> None:
    from modeling_cli import doctor

    root = math.sqrt(2.0)
    function_value = root * root - 2.0
    result_summary = SimpleNamespace(
        root=root,
        function_value=function_value,
    )
    metrics = SimpleNamespace(
        root_within_interval=True,
        reported_function_value=function_value,
        recomputed_function_value=function_value,
        absolute_reported_delta=0.0,
        absolute_residual=abs(function_value),
        function_tolerance=1e-10,
        failed_checks=(),
    )
    target = result_summary if field in {"root", "function_value"} else metrics
    setattr(target, field, value)
    run = RunExperimentSucceededResult.model_construct(
        attempt_id=_uuid(91),
        result_hash="sha256:" + "1" * 64,
        result_summary=result_summary,
    )
    validation = ValidateExperimentSucceededResult.model_construct(
        outcome="PASSED",
        metrics=metrics,
    )

    class Application:
        def create_project(self, request: object) -> object:
            return SimpleNamespace(project_id=_uuid(90))

        def run_experiment(self, request: object) -> object:
            return run

        def validate_experiment(self, request: object) -> object:
            return validation

    class Composition:
        application = Application()

        def __init__(self, contender: bool) -> None:
            self.contender = contender

        def start(self) -> None:
            if self.contender:
                raise ProjectStoreError(
                    "CONFLICT", "busy", True, {"conflict_type": "project_busy"}
                )

        def close(self) -> None:
            pass

    compositions = iter((Composition(False), Composition(True)))
    monkeypatch.setattr(doctor, "bootstrap_storage", lambda *args: None)
    monkeypatch.setattr(
        doctor, "build_composition", lambda root, **kwargs: next(compositions)
    )

    assert doctor._run_deep_smoke()[1] == expected


def test_doctor_inspects_a_real_schema_two_artifact_graph_read_only(
    tmp_path: Path,
) -> None:
    """Catches doctor binding a stable project with preview versions and hiding artifacts."""
    from modeling_bootstrap.composition import build_composition
    from modeling_cli.doctor import run_doctor
    from modeling_core.contracts.tools import (
        CapabilitySelection,
        CreateProjectRequest,
        RootFindingInput,
        RunExperimentRequest,
        ValidateExperimentRequest,
    )

    composition = build_composition(tmp_path)
    with composition:
        project = composition.application.create_project(
            CreateProjectRequest(operation_id=_uuid(100))
        )
        run = composition.application.run_experiment(
            RunExperimentRequest(
                operation_id=_uuid(101),
                project_id=project.project_id,
                mode="new",
                capability=CapabilitySelection(
                    capability_id="numerical.root_finding",
                    contract_version="1.0.0",
                ),
                payload=RootFindingInput(expression="x*x-2", lower=0.0, upper=2.0),
            )
        )
        composition.application.validate_experiment(
            ValidateExperimentRequest(
                operation_id=_uuid(102),
                project_id=project.project_id,
                attempt_id=run.attempt_id,
                expected_result_hash=run.result_hash,
                validator_id="numerical.root_finding.residual",
                policy_version="1.0.0",
                policy={},
            )
        )
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    stdout = io.StringIO()

    exit_code = run_doctor(tmp_path, True, True, stdout=stdout)
    assert exit_code == 0, stdout.getvalue()

    report = json.loads(stdout.getvalue())
    assert _checks(report)["artifact_references"] == ("PASS", "verified")
    assert _checks(report)["input_drift"] == ("PASS", "clean")
    assert _checks(report)["reproducibility_metadata"] == ("PASS", "complete")
    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before

    def assert_artifact_unsafe() -> None:
        unsafe_stdout = io.StringIO()
        assert run_doctor(tmp_path, True, True, stdout=unsafe_stdout) == 2
        assert _checks(json.loads(unsafe_stdout.getvalue()))["artifact_references"] == (
            "FAIL",
            "missing_or_tampered",
        )

    with sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3") as database:
        result_row = database.execute(
            "SELECT * FROM result_snapshots WHERE attempt_id=?", (run.attempt_id,)
        ).fetchone()
        assert result_row is not None
        database.execute(
            "DELETE FROM result_snapshots WHERE attempt_id=?", (run.attempt_id,)
        )
        database.commit()
    assert_artifact_unsafe()

    with sqlite3.connect(tmp_path / ".modeling" / "state.sqlite3") as database:
        database.execute(
            "INSERT INTO result_snapshots VALUES (?, ?, ?, ?, ?, ?)", result_row
        )
        database.execute(
            "UPDATE validations SET report_artifact_id=NULL WHERE status='SUCCEEDED'"
        )
        database.commit()
    assert_artifact_unsafe()
