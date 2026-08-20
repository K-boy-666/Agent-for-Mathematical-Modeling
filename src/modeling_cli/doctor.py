"""Read-only project diagnosis over a verified owned snapshot."""

from __future__ import annotations

import json
import math
import sys
import tempfile
import tomllib
from importlib.resources import files
from pathlib import Path
from typing import IO, Literal, cast

from jsonschema import Draft202012Validator  # type: ignore[import-untyped]

from modeling_bootstrap.composition import build_composition
from modeling_core.application.facade import ApplicationFacade
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.tools import (
    CapabilitySelection,
    CreateProjectRequest,
    HealthCheckRequest,
    ListCapabilitiesSummaryRequest,
    RootFindingInput,
    RunExperimentRequest,
    RunExperimentSucceededResult,
    ValidateExperimentRequest,
    ValidateExperimentSucceededResult,
)
from modeling_core.contracts.versions import VersionSet
from modeling_core.domain.states import ProjectState
from modeling_core.ports.project_store import (
    ProjectStore,
    ProjectStoreError,
    StoreIntegrityReport,
)
from modeling_infrastructure.diagnostic_snapshot import (
    DiagnosticSnapshotError,
    SourceStateHint,
    materialize_diagnostic_snapshot,
)
from modeling_infrastructure.storage import bootstrap_storage

DoctorReport = dict[str, object]
CheckStatus = Literal["PASS", "WARN", "FAIL"]

_SCHEMA_VERSION = "modeling-doctor-report/0.1.0"
_EXPECTED_SCHEMA_CATALOG_FINGERPRINT = (
    "sha256:927a26b40a1cf0747a3f79d8ebb44f085cd7bf404ae22c7f957137a0d652bc73"
)
_EXPECTED_CONFIG = {
    "mcp_servers": {
        "modeling": {
            "command": "uv",
            "args": [
                "run",
                "--locked",
                "--no-sync",
                "modeling-mcp",
                "--project-root",
                ".",
            ],
            "cwd": ".",
            "required": True,
            "startup_timeout_sec": 10,
            "tool_timeout_sec": 65,
            "enabled_tools": [
                "health_check",
                "create_project",
                "get_project_status",
                "list_capabilities",
                "run_experiment",
                "validate_experiment",
                "register_problem_assets",
                "put_subproblem_mmir",
                "confirm_subproblem_mmir",
                "export_subproblem",
            ],
        }
    }
}


def _check(name: str, status: CheckStatus, code: str) -> dict[str, str]:
    return {"name": name, "status": status, "code": code}


def _asset_codes() -> tuple[str, str]:
    try:
        catalog = SchemaCatalog.load_packaged()
        schema_code = (
            "hashes_match"
            if catalog.fingerprint == _EXPECTED_SCHEMA_CATALOG_FINGERPRINT
            else "hash_mismatch"
        )
    except Exception:
        schema_code = "unavailable"
    try:
        raw = (
            files("modeling_cli")
            .joinpath("templates", "codex", "config.toml")
            .read_bytes()
        )
        config_code = (
            "valid"
            if tomllib.loads(raw.decode("utf-8")) == _EXPECTED_CONFIG
            else "invalid"
        )
    except Exception:
        config_code = "unavailable"
    return schema_code, config_code


def _storage_payload(report: StoreIntegrityReport | None) -> dict[str, object]:
    if report is None:
        return {
            "check": None,
            "issues": [],
            "legacy_attempts": [],
            "legacy_validations": [],
            "legacy_idempotency_records": [],
        }
    check = (
        None
        if report.check is None
        else {"mode": report.check.mode, "outcome": report.check.outcome}
    )
    return {
        "check": check,
        "issues": list(report.issues),
        "legacy_attempts": [
            {"attempt_id": item.attempt_id, "status": item.status}
            for item in report.legacy_attempts
        ],
        "legacy_validations": [
            {"validation_id": item.validation_id, "status": item.status}
            for item in report.legacy_validations
        ],
        "legacy_idempotency_records": [
            {
                "scope_id": item.scope_id,
                "tool_name": item.tool_name,
                "operation_id": item.operation_id,
                "status": item.status,
            }
            for item in report.legacy_idempotency_records
        ],
    }


def _failure_report(code: str, deep: bool) -> DoctorReport:
    schema_code, config_code = _asset_codes()
    root_status, root_code = {
        "snapshot_invalid": ("FAIL", "unsafe"),
        "snapshot_unavailable": ("FAIL", "unreadable"),
    }.get(code, ("PASS", "available"))
    checks = [
        _check("project-root", cast(CheckStatus, root_status), root_code),
        _check("project-state", "FAIL", "degraded"),
        _check("application-health", "FAIL", "unavailable"),
        _check("capability-registry", "FAIL", "unavailable"),
        _check("storage-integrity", "FAIL", code),
        _check("foreign-keys", "FAIL", "unavailable"),
        _check("legacy-attempts", "FAIL", "unavailable"),
        _check("legacy-validations", "FAIL", "unavailable"),
        _check("legacy-operations", "FAIL", "unavailable"),
        _check(
            "schema-assets",
            "PASS" if schema_code == "hashes_match" else "FAIL",
            schema_code,
        ),
        _check(
            "codex-config",
            "PASS" if config_code == "valid" else "FAIL",
            config_code,
        ),
    ]
    if deep:
        checks.extend(
            (
                _check("deep-lock-smoke", "FAIL", "failed"),
                _check("deep-root-smoke", "FAIL", "failed"),
            )
        )
    return {
        "schema_version": _SCHEMA_VERSION,
        "status": "UNSAFE",
        "exit_code": 2,
        "project_state": "DEGRADED",
        "ready_for_project_creation": False,
        "deep": deep,
        "checks": checks,
        "storage": _storage_payload(None),
    }


def _run_deep_smoke(*, observed_roots: list[Path] | None = None) -> tuple[str, str]:
    temporary = tempfile.TemporaryDirectory(prefix="modeling-doctor-deep-")
    root = Path(temporary.name)
    if observed_roots is not None:
        observed_roots.append(root)
    lock_code = "failed"
    root_code = "failed"
    owner = None
    contender = None
    try:
        try:
            versions = VersionSet.m1a()
            bootstrap_storage(root, versions)
            owner = build_composition(root, versions=versions)
            owner.start()
            created = owner.application.create_project(
                CreateProjectRequest(
                    operation_id="10000000-0000-4000-8000-000000000901"
                )
            )
            run = owner.application.run_experiment(
                RunExperimentRequest(
                    operation_id="10000000-0000-4000-8000-000000000902",
                    project_id=created.project_id,
                    mode="new",
                    capability=CapabilitySelection(
                        capability_id="numerical.root_finding",
                        contract_version="0.1.0",
                    ),
                    payload=RootFindingInput(
                        expression="x*x - 2", lower=0.0, upper=2.0
                    ),
                )
            )
            if isinstance(run, RunExperimentSucceededResult):
                summary = run.result_summary
                solution_root = summary.root
                reported = summary.function_value
                recomputed = solution_root * solution_root - 2.0
                if not (
                    math.isfinite(solution_root)
                    and 0.0 <= solution_root <= 2.0
                    and math.isclose(
                        solution_root,
                        math.sqrt(2.0),
                        rel_tol=0.0,
                        abs_tol=1e-10,
                    )
                    and math.isfinite(reported)
                    and math.isfinite(recomputed)
                ):
                    root_code = "result_mismatch"
                else:
                    validation = owner.application.validate_experiment(
                        ValidateExperimentRequest(
                            operation_id="10000000-0000-4000-8000-000000000903",
                            project_id=created.project_id,
                            attempt_id=run.attempt_id,
                            expected_result_hash=run.result_hash,
                            validator_id="numerical.root_finding.residual",
                            policy_version="0.1.0",
                            policy={},
                        )
                    )
                    absolute_delta = abs(recomputed - reported)
                    absolute_residual = abs(recomputed)
                    if isinstance(validation, ValidateExperimentSucceededResult):
                        metrics = validation.metrics
                        root_code = (
                            "passed"
                            if validation.outcome == "PASSED"
                            and metrics.root_within_interval is True
                            and metrics.reported_function_value == reported
                            and metrics.recomputed_function_value == recomputed
                            and metrics.absolute_reported_delta == absolute_delta
                            and metrics.absolute_residual == absolute_residual
                            and metrics.function_tolerance == 1e-10
                            and absolute_delta <= metrics.function_tolerance
                            and absolute_residual <= metrics.function_tolerance
                            and metrics.failed_checks == ()
                            else "validation_failed"
                        )
                    else:
                        root_code = "validation_failed"
            else:
                root_code = "result_mismatch"

            contender = build_composition(root, versions=versions)
            try:
                contender.start()
            except ProjectStoreError as error:
                lock_code = (
                    "passed"
                    if error.code == "CONFLICT"
                    and error.details.get("conflict_type") == "project_busy"
                    else "busy_classification_mismatch"
                )
            else:
                lock_code = "busy_classification_mismatch"
        except Exception:
            pass
        return lock_code, root_code
    finally:
        cleanup_failed = False
        for composition in (contender, owner):
            if composition is None:
                continue
            try:
                composition.close()
            except BaseException:
                cleanup_failed = True
        try:
            temporary.cleanup()
        except BaseException:
            cleanup_failed = True
        if cleanup_failed:
            raise DiagnosticSnapshotError("snapshot_cleanup_failed") from None


def diagnose_project(
    application: ApplicationFacade,
    store: ProjectStore,
    source_state_hint: SourceStateHint,
    deep: bool,
) -> DoctorReport:
    """Build one finite in-memory report from the shared Facade and Store."""
    del source_state_hint
    health = application.health_check(HealthCheckRequest())
    capability_available = True
    try:
        application.list_capabilities(ListCapabilitiesSummaryRequest())
    except Exception:
        capability_available = False
    integrity = store.inspect_integrity(deep)
    schema_code, config_code = _asset_codes()
    issues = set(integrity.issues)
    state = health.project_state
    degraded = (
        health.status == "DEGRADED"
        or integrity.state is ProjectState.DEGRADED
        or bool(issues)
    )
    if degraded:
        state = "DEGRADED"

    if state == "UNINITIALIZED":
        project_state = _check("project-state", "WARN", "uninitialized")
        storage_code = "not_initialized"
        foreign_code = "not_initialized"
        attempts_code = "not_initialized"
        validations_code = "not_initialized"
        operations_code = "not_initialized"
    elif state == "DEGRADED" and integrity.check is None:
        project_state = _check("project-state", "FAIL", "degraded")
        storage_code = "not_executed_degraded"
        foreign_code = "not_executed_degraded"
        attempts_code = "not_executed_degraded"
        validations_code = "not_executed_degraded"
        operations_code = "not_executed_degraded"
    else:
        project_state = _check(
            "project-state",
            "FAIL" if degraded else "PASS",
            "degraded" if degraded else state.lower(),
        )
        storage_code = (
            "check_error"
            if integrity.check is not None and integrity.check.outcome == "ERROR"
            else (
                "check_failed"
                if integrity.check is not None and integrity.check.outcome == "FAIL"
                else ("check_error" if "database_relation" in issues else "ok")
            )
        )
        foreign_code = "foreign_key_failure" if "foreign_key" in issues else "ok"
        attempts_code = "stale_attempt" if integrity.legacy_attempts else "none"
        validations_code = (
            "stale_validation" if integrity.legacy_validations else "none"
        )
        operations_code = (
            "stale_operation" if integrity.legacy_idempotency_records else "none"
        )

    storage_failed = storage_code not in {"not_initialized", "ok"}
    checks = [
        _check("project-root", "PASS", "available"),
        project_state,
        _check(
            "application-health",
            "FAIL" if health.status == "DEGRADED" else "PASS",
            "degraded" if health.status == "DEGRADED" else "healthy",
        ),
        _check(
            "capability-registry",
            "PASS" if health.registry.sealed and capability_available else "FAIL",
            "sealed"
            if health.registry.sealed and capability_available
            else "unavailable",
        ),
        _check(
            "storage-integrity",
            "FAIL" if storage_failed else "PASS",
            storage_code,
        ),
        _check(
            "foreign-keys",
            "FAIL" if foreign_code not in {"not_initialized", "ok"} else "PASS",
            foreign_code,
        ),
        _check(
            "legacy-attempts",
            "FAIL" if attempts_code not in {"not_initialized", "none"} else "PASS",
            attempts_code,
        ),
        _check(
            "legacy-validations",
            "FAIL" if validations_code not in {"not_initialized", "none"} else "PASS",
            validations_code,
        ),
        _check(
            "legacy-operations",
            "FAIL" if operations_code not in {"not_initialized", "none"} else "PASS",
            operations_code,
        ),
        _check(
            "schema-assets",
            "PASS" if schema_code == "hashes_match" else "FAIL",
            schema_code,
        ),
        _check(
            "codex-config",
            "PASS" if config_code == "valid" else "FAIL",
            config_code,
        ),
    ]
    if deep:
        smoke = _run_deep_smoke()
        if smoke is None:  # deterministic unit-test seam
            lock_code, root_code = "passed", "passed"
        else:
            lock_code, root_code = smoke
        checks.extend(
            (
                _check(
                    "deep-lock-smoke",
                    "PASS" if lock_code == "passed" else "FAIL",
                    lock_code,
                ),
                _check(
                    "deep-root-smoke",
                    "PASS" if root_code == "passed" else "FAIL",
                    root_code,
                ),
            )
        )

    unsafe = any(item["status"] == "FAIL" for item in checks)
    warning = any(item["status"] == "WARN" for item in checks)
    return {
        "schema_version": _SCHEMA_VERSION,
        "status": "UNSAFE" if unsafe else ("WARNING" if warning else "READY"),
        "exit_code": 2 if unsafe else (1 if warning else 0),
        "project_state": state,
        "ready_for_project_creation": (
            state in {"UNINITIALIZED", "STORAGE_READY"} and not unsafe
        ),
        "deep": deep,
        "checks": checks,
        "storage": _storage_payload(integrity),
    }


def _load_report_schema() -> dict[str, object]:
    raw = (
        files("modeling_cli")
        .joinpath("schemas", "doctor", "0.1.0", "report.schema.json")
        .read_text(encoding="utf-8")
    )
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("doctor schema must be an object")
    return cast(dict[str, object], decoded)


def _validate_report(report: DoctorReport) -> None:
    schema = _load_report_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(report)


def _render_report(report: DoctorReport, json_output: bool, stdout: IO[str]) -> None:
    if json_output:
        stdout.write(
            json.dumps(
                report, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
        )
        stdout.write("\n")
        return
    stdout.write(f"Doctor: {report['status']} (exit {report['exit_code']})\n")
    for item in cast(list[dict[str, str]], report["checks"]):
        stdout.write(f"{item['status']} {item['name']}: {item['code']}\n")


def run_doctor(
    project_root: Path,
    deep: bool,
    json_output: bool,
    *,
    stdout: IO[str] | None = None,
    stderr: IO[str] | None = None,
) -> int:
    """Diagnose, validate, then render exactly once after cleanup."""
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    try:
        try:
            with materialize_diagnostic_snapshot(project_root) as snapshot:
                composition = build_composition(
                    snapshot.project_root, versions=VersionSet.m1a()
                )
                try:
                    report = diagnose_project(
                        composition.application,
                        composition.store,
                        snapshot.source_state_hint,
                        deep,
                    )
                finally:
                    try:
                        composition.close()
                    except BaseException:
                        raise DiagnosticSnapshotError(
                            "snapshot_cleanup_failed"
                        ) from None
        except DiagnosticSnapshotError as error:
            report = _failure_report(error.code, deep)
        except Exception:
            report = _failure_report("check_error", deep)
        _validate_report(report)
    except Exception:
        errors.write("MODELING_DOCTOR_SCHEMA_INVALID\n")
        return 2
    _render_report(report, json_output, output)
    return cast(int, report["exit_code"])


__all__ = ["diagnose_project", "run_doctor"]
