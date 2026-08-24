from __future__ import annotations

import json
from pathlib import Path

import pytest

from modeling_cli.main import main
from modeling_core.contracts.canonical_json import canonical_json_bytes, sha256_json
from modeling_core.contracts.tools import TOOL_NAMES
from modeling_harness import verify as verification
from modeling_harness import release_evidence as release_module
from modeling_harness.evidence import EvidenceValidationError
from modeling_harness.release_evidence import (
    ReleaseEvidenceInputs,
    assemble_release_bundle,
    validate_release_bundle,
)


COMMIT = "b" * 40
HASH = "sha256:" + "c" * 64
ROOT = 2**0.5
PROJECT_ID = "10000000-0000-4000-8000-000000000001"
EXPERIMENT_ID = "10000000-0000-4000-8000-000000000002"
ATTEMPT_ID = "10000000-0000-4000-8000-000000000003"
VALIDATION_ID = "10000000-0000-4000-8000-000000000004"
RESULT_SNAPSHOT_ID = "10000000-0000-4000-8000-000000000005"
SESSION_ID = "10000000-0000-4000-8000-000000000006"
TIMESTAMP = "2026-07-23T12:34:56.789Z"
SOURCE_INVENTORY = [
    {"path": "src/modeling_core/__init__.py", "sha256": HASH},
]
FINGERPRINT = sha256_json(SOURCE_INVENTORY)
EXPRESSION = {
    "kind": "binary",
    "op": "subtract",
    "left": {
        "kind": "binary",
        "op": "multiply",
        "left": {"kind": "variable", "name": "x"},
        "right": {"kind": "variable", "name": "x"},
    },
    "right": {"kind": "number", "value": 2.0},
}
CANONICAL_PAYLOAD = {
    "canonical_input_schema_version": ("numerical.root_finding.canonical-input/1.0.0"),
    "expression_ast": EXPRESSION,
    "lower": 0.0,
    "upper": 2.0,
    "absolute_tolerance": 1e-10,
    "relative_tolerance": 1e-10,
    "function_tolerance": 1e-10,
    "max_iterations": 100,
}
CANONICAL_PAYLOAD_HASH = sha256_json(CANONICAL_PAYLOAD)
MODEL_SNAPSHOT_HASH = sha256_json({"language": "math-expr-v1", "ast": EXPRESSION})
DATA_SNAPSHOT_SET_HASH = sha256_json([])
POLICY_HASH = sha256_json({})
RESULT_PAYLOAD = {
    "result_schema_version": "modeling-result/1.0.0",
    "capability_id": "numerical.root_finding",
    "contract_version": "1.0.0",
    "result_kind": "success",
    "data": {
        "root": ROOT,
        "function_value": ROOT * ROOT - 2.0,
        "iterations": 8,
        "evaluations": 10,
        "termination_reason": "residual_tolerance",
    },
}
RESULT_HASH = sha256_json(RESULT_PAYLOAD)
REPORT_PAYLOAD = {
    "report_schema_version": "modeling-validation-report/1.0.0",
    "validator_id": "numerical.root_finding.residual",
    "validator_implementation_id": "builtin.numerical.root_finding.residual",
    "validator_implementation_version": "1.0.0",
    "policy_version": "1.0.0",
    "policy": {},
    "policy_hash": POLICY_HASH,
    "capability_id": "numerical.root_finding",
    "contract_version": "1.0.0",
    "canonical_payload_hash": CANONICAL_PAYLOAD_HASH,
    "model_snapshot_hash": MODEL_SNAPSHOT_HASH,
    "data_snapshot_set_hash": DATA_SNAPSHOT_SET_HASH,
    "result_hash": RESULT_HASH,
    "outcome": "PASSED",
    "metrics": {
        "root_within_interval": True,
        "reported_function_value": ROOT * ROOT - 2.0,
        "recomputed_function_value": ROOT * ROOT - 2.0,
        "absolute_reported_delta": 0.0,
        "absolute_residual": abs(ROOT * ROOT - 2.0),
        "function_tolerance": 1e-10,
        "failed_checks": [],
    },
}
REPORT_HASH = sha256_json(REPORT_PAYLOAD)
ACCEPTANCE_IDS = tuple(
    f"{prefix}-{number:02d}" for prefix in ("A", "B") for number in range(1, 11)
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="utf-8",
    )


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _platform_report(root: Path, *, os_family: str) -> Path:
    report_dir = root / os_family.lower()
    distribution = (
        {"id": "windows", "version": "10.0"}
        if os_family == "Windows"
        else {"id": "ubuntu", "version": "24.04"}
    )
    nodes_by_check = {check_id: set() for check_id in verification.M1B_CHECK_IDS}
    for requirement in verification._M1B_ACCEPTANCE_REQUIREMENTS:
        for clause in requirement.clauses:
            for check_id in clause.check_ids:
                nodes_by_check[check_id].update(
                    node.selector for node in clause.required_nodes
                )
    checks = [
        {
            "check_id": check_id,
            "status": "PASS",
            "duration_ms": 1,
            "exit_code": 0,
            "test_counts": (
                {
                    "total": len(nodes_by_check[check_id]),
                    "passed": len(nodes_by_check[check_id]),
                    "failed": 0,
                    "errors": 0,
                    "skipped": 0,
                }
                if nodes_by_check[check_id]
                else None
            ),
            "diagnostic_code": None,
            "test_nodes": (
                sorted(nodes_by_check[check_id]) if nodes_by_check[check_id] else None
            ),
        }
        for check_id in verification.M1B_CHECK_IDS
    ]
    acceptance_map = {
        "schema_version": "m1b-acceptance-map/1.0.0",
        "source_fingerprint": FINGERPRINT,
        "entries": [
            {
                "acceptance_id": requirement.acceptance_id,
                "status": "PASS",
                "test_nodes": [
                    {
                        "selector": node.selector,
                        "match": node.match,
                        "observed_nodes": [node.selector],
                    }
                    for clause in requirement.clauses
                    for node in clause.required_nodes
                ],
                "evidence": [
                    {
                        "artifact": reference.artifact,
                        "json_pointer": reference.json_pointer,
                    }
                    for clause in requirement.clauses
                    for reference in clause.success_evidence
                ],
            }
            for requirement in verification._M1B_ACCEPTANCE_REQUIREMENTS
        ],
    }
    report = {
        "schema_version": "m1b-verification-report/1.0.0",
        "milestone": "m1b",
        "status": "PASSED",
        "source_fingerprint": FINGERPRINT,
        "commit": COMMIT,
        "required_skips": 0,
        "environment": {
            "architecture": "AMD64" if os_family == "Windows" else "x86_64",
            "distribution": distribution,
            "lock_sha256": HASH,
            "os_family": os_family,
            "os_version": distribution["version"],
            "python_version": "3.11.15",
            "uv_executable_sha256": HASH,
            "uv_version": "0.11.28",
        },
        "checks": checks,
        "artifacts": {
            "source_inventory": "source-inventory.json",
            "package_assets": "package-assets.json",
            "architecture_report": "architecture-report.json",
            "stdio_transcript": "stdio-transcript.json",
            "golden_trace": "golden-trace.json",
        },
        "golden_ids": {
            "project_id": PROJECT_ID,
            "experiment_id": EXPERIMENT_ID,
            "attempt_id": ATTEMPT_ID,
            "validation_id": VALIDATION_ID,
        },
        "incomplete_groups": [],
        "acceptance_map": acceptance_map,
    }
    _write_json(report_dir / "verification-report.json", report)
    _write_json(
        report_dir / "architecture-report.json",
        {
            "schema_version": "m1b-architecture-report/1.0.0",
            "status": "PASS",
            "check_id": "pytest-architecture",
            "test_counts": {
                "passed": 1,
                "failed": 0,
                "errors": 0,
                "skipped": 0,
                "total": 1,
            },
        },
    )
    _write_json(
        report_dir / "source-inventory.json",
        SOURCE_INVENTORY,
    )
    _write_json(
        report_dir / "package-assets.json",
        [{"path": "modeling_core/__init__.py", "sha256": HASH}],
    )
    _write_json(
        report_dir / "stdio-transcript.json",
        {
            "schema_version": "m1a-stdio-transcript/0.1.0",
            "events": [
                {
                    "direction": "client_to_server",
                    "kind": "initialize",
                    "is_error": False,
                    "status": "READY",
                    "versions": {
                        "mcp_protocol": "2025-11-25",
                        "application": "0.2.0",
                    },
                }
            ],
        },
    )
    _write_json(
        report_dir / "golden-trace.json",
        {
            "schema_version": "m1a-golden-trace/0.1.0",
            **report["golden_ids"],
            "capability_id": "numerical.root_finding",
            "contract_version": "1.0.0",
            "attempt_status": "SUCCEEDED",
            "validation_status": "SUCCEEDED",
            "validation_outcome": "PASSED",
            "result_hash": RESULT_HASH,
            "validation_report_hash": REPORT_HASH,
        },
    )
    (report_dir / "SUMMARY.md").write_text("M1b PASSED\n", encoding="utf-8")
    return report_dir / "verification-report.json"


def _codex_transcript(path: Path) -> Path:
    lines: list[dict[str, object]] = [
        {"type": "session", "status": "PASS", "server": "modeling"}
    ]
    lines.extend(
        {
            "type": "mcp_tool_call",
            "server": "modeling",
            "tool": tool,
            "status": "PASS",
        }
        for tool in TOOL_NAMES
    )
    lines.append(
        {
            "type": "result",
            "status": "PASS",
            "root": 2**0.5,
            "residual": 4.440892098500626e-16,
            "validation_outcome": "PASSED",
            "result_hash": HASH,
            "validation_report_hash": HASH,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(line, separators=(",", ":"), sort_keys=True) + "\n"
            for line in lines
        ),
        encoding="utf-8",
    )
    return path


def _raw_codex_transcript(path: Path) -> Path:
    def artifact(
        hash_value: str, role: str, payload: dict[str, object]
    ) -> dict[str, object]:
        digest = hash_value.removeprefix("sha256:")
        return {
            "artifact_id": hash_value,
            "role": role,
            "sha256": hash_value,
            "media_type": "application/json",
            "size_bytes": len(canonical_json_bytes(payload)),
            "project_relative_path": (
                f".modeling/artifacts/sha256/{digest[:2]}/{digest}.json"
            ),
        }

    def corpus_result(tool: str) -> dict[str, object]:
        corpus = json.loads(
            (
                Path(__file__).parents[2]
                / f"tests/contract/corpus/tools/1.0.0/{tool}.json"
            ).read_text(encoding="utf-8")
        )
        return next(
            item["instance"] for item in corpus if item["label"] == "valid_result"
        )

    common = {
        "tool_contract_version": "modeling-tools/1.0.0",
        "correlation_id": "20000000-0000-4000-8000-000000000001",
        "server_time": TIMESTAMP,
    }
    experiment_trace: dict[str, object] = {
        **common,
        "view": "experiment",
        "project": {
            "project_id": PROJECT_ID,
            "display_name": "release-smoke",
            "project_format_version": "modeling-project/1.0.0",
            "project_state": "READY",
            "created_at": TIMESTAMP,
        },
        "experiment": {
            "experiment_id": EXPERIMENT_ID,
            "project_id": PROJECT_ID,
            "capability_id": "numerical.root_finding",
            "contract_version": "1.0.0",
            "canonical_input_schema_version": (
                "numerical.root_finding.canonical-input/1.0.0"
            ),
            "canonical_payload": CANONICAL_PAYLOAD,
            "canonical_payload_hash": CANONICAL_PAYLOAD_HASH,
            "canonicalization_version": "canonical-json/1.0.0",
            "model_snapshot_hash": MODEL_SNAPSHOT_HASH,
            "data_snapshot_references": [],
            "data_snapshot_set_hash": DATA_SNAPSHOT_SET_HASH,
            "execution_policy": {"timeout_ms": 10000, "seed": None},
            "created_at": TIMESTAMP,
        },
        "trace": [
            {
                "record_type": "attempt",
                "attempt_id": ATTEMPT_ID,
                "experiment_id": EXPERIMENT_ID,
                "implementation_id": "builtin.numerical.root_finding.bisection",
                "implementation_version": "1.0.0",
                "environment_summary": {
                    "python_version": "3.11.15",
                    "application_version": "0.2.0",
                    "lock_hash": HASH,
                },
                "randomness": "not_used",
                "seed": None,
                "session_id": SESSION_ID,
                "status": "SUCCEEDED",
                "created_at": TIMESTAMP,
                "started_at": TIMESTAMP,
                "finished_at": TIMESTAMP,
                "warnings": [],
                "result": {
                    "result_snapshot_id": RESULT_SNAPSHOT_ID,
                    "result_kind": "success",
                    "result_schema_version": "modeling-result/1.0.0",
                    "result_hash": RESULT_HASH,
                    "result_payload": RESULT_PAYLOAD,
                },
                "system_error": None,
                "numerical_failure": None,
                "terminal_reason": None,
            },
            {
                "record_type": "validation",
                "validation_id": VALIDATION_ID,
                "attempt_id": ATTEMPT_ID,
                "status": "SUCCEEDED",
                "created_at": TIMESTAMP,
                "started_at": TIMESTAMP,
                "finished_at": TIMESTAMP,
                "outcome": "PASSED",
                "expected_result_hash": RESULT_HASH,
                "result_hash": RESULT_HASH,
                "validator_id": "numerical.root_finding.residual",
                "validator_implementation_id": (
                    "builtin.numerical.root_finding.residual"
                ),
                "validator_implementation_version": "1.0.0",
                "policy_version": "1.0.0",
                "policy": {},
                "policy_hash": POLICY_HASH,
                "metrics": REPORT_PAYLOAD["metrics"],
                "validation_report_hash": REPORT_HASH,
                "report_payload": REPORT_PAYLOAD,
                "operational_error": None,
                "terminal_reason": None,
            },
        ],
    }
    run_result = {
        **common,
        "operation_id": "20000000-0000-4000-8000-000000000002",
        "replayed": False,
        "experiment_id": EXPERIMENT_ID,
        "attempt_id": ATTEMPT_ID,
        "attempt_status": "SUCCEEDED",
        "capability_id": "numerical.root_finding",
        "contract_version": "1.0.0",
        "implementation_id": "builtin.numerical.root_finding.bisection",
        "implementation_version": "1.0.0",
        "randomness": "not_used",
        "seed": None,
        "warnings": [],
        "result_kind": "success",
        "result_summary": RESULT_PAYLOAD["data"],
        "result_hash": RESULT_HASH,
        "artifacts": [artifact(RESULT_HASH, "result", RESULT_PAYLOAD)],
    }
    validation_result = {
        **common,
        "operation_id": "20000000-0000-4000-8000-000000000003",
        "replayed": False,
        "validation_id": VALIDATION_ID,
        "attempt_id": ATTEMPT_ID,
        "result_hash": RESULT_HASH,
        "validator_id": "numerical.root_finding.residual",
        "validator_implementation_id": "builtin.numerical.root_finding.residual",
        "validator_implementation_version": "1.0.0",
        "policy_version": "1.0.0",
        "policy_hash": POLICY_HASH,
        "validation_status": "SUCCEEDED",
        "outcome": "PASSED",
        "metrics": REPORT_PAYLOAD["metrics"],
        "validation_report_hash": REPORT_HASH,
        "report_artifact": artifact(REPORT_HASH, "validation_report", REPORT_PAYLOAD),
    }
    structured_by_tool = {tool: corpus_result(tool) for tool in TOOL_NAMES}
    create = structured_by_tool["create_project"]
    create["project_id"] = PROJECT_ID
    structured_by_tool["get_project_status"] = experiment_trace
    structured_by_tool["run_experiment"] = run_result
    structured_by_tool["validate_experiment"] = validation_result
    for tool in (
        "register_problem_assets",
        "put_subproblem_mmir",
        "confirm_subproblem_mmir",
        "export_subproblem",
    ):
        structured_by_tool[tool]["project_id"] = PROJECT_ID
    put = structured_by_tool["put_subproblem_mmir"]
    confirm = structured_by_tool["confirm_subproblem_mmir"]
    exported = structured_by_tool["export_subproblem"]
    confirm["subproblem_id"] = put["subproblem_id"]
    confirm["mmir_revision"] = put["mmir_revision"]
    exported["subproblem_id"] = put["subproblem_id"]
    exports = exported["exports"]
    assert isinstance(exports, list) and isinstance(exports[0], dict)
    exports[0]["sha256"] = put["mmir_revision"]
    events: list[dict[str, object]] = [
        {"type": "thread.started", "thread_id": "release-smoke"}
    ]
    for index, tool in enumerate(TOOL_NAMES):
        structured = structured_by_tool[tool]
        events.append(
            {
                "type": "item.completed",
                "item": {
                    "id": f"item-{index}",
                    "type": "mcp_tool_call",
                    "server": "modeling",
                    "tool": tool,
                    "arguments": {"redacted_by_assembler": True},
                    "result": {"structuredContent": structured, "isError": False},
                    "status": "completed",
                    "error": None,
                },
            }
        )
    events.append({"type": "turn.completed", "usage": {"input_tokens": 1}})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n"
            for event in events
        ),
        encoding="utf-8",
    )
    return path


def _valid_inputs(root: Path) -> ReleaseEvidenceInputs:
    return ReleaseEvidenceInputs(
        windows_report=_platform_report(root, os_family="Windows"),
        ubuntu_report=_platform_report(root, os_family="Linux"),
        codex_transcript=_raw_codex_transcript(root / "codex-transcript.jsonl"),
    )


def test_release_bundle_assembles_exact_redacted_tamper_evident_evidence(
    tmp_path: Path,
) -> None:
    inputs = _valid_inputs(tmp_path / "inputs")
    destination = tmp_path / "bundle"

    manifest = assemble_release_bundle(inputs, destination)
    validated = validate_release_bundle(destination, FINGERPRINT)

    assert manifest.commit == COMMIT
    assert manifest.source_fingerprint == FINGERPRINT
    assert validated.valid is True
    assert validated.commit == COMMIT
    assert validated.source_fingerprint == FINGERPRINT
    assert {item.path for item in manifest.files} == {
        "SUMMARY.md",
        "acceptance/coverage-map.json",
        "hosts/codex-transcript.jsonl",
        "math/reproducibility-report.json",
        "recovery/fault-report.json",
        "schema/compatibility-report.json",
        "security/security-report.json",
        "stdio/generic-mcp-transcript.json",
        "trace/artifact-hashes.json",
        "trace/golden-trace.json",
        *{
            f"verification/{platform}/{name}"
            for platform in ("windows", "ubuntu")
            for name in (
                "SUMMARY.md",
                "architecture-report.json",
                "golden-trace.json",
                "package-assets.json",
                "source-inventory.json",
                "stdio-transcript.json",
                "verification-report.json",
            )
        },
    }


def test_release_bundle_accepts_current_codex_cli_structured_content(
    tmp_path: Path,
) -> None:
    inputs = _valid_inputs(tmp_path / "inputs")
    events = [
        json.loads(line)
        for line in inputs.codex_transcript.read_text(encoding="utf-8").splitlines()
    ]
    for event in events:
        item = event.get("item")
        if not isinstance(item, dict) or item.get("type") != "mcp_tool_call":
            continue
        result = item["result"]
        assert isinstance(result, dict)
        item["result"] = {
            "content": [],
            "structured_content": result["structuredContent"],
        }
    inputs.codex_transcript.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )

    manifest = assemble_release_bundle(inputs, tmp_path / "bundle")

    assert manifest.commit == COMMIT


def test_release_bundle_accepts_distinct_per_run_golden_ids(tmp_path: Path) -> None:
    inputs = _valid_inputs(tmp_path / "inputs")
    replacements = {
        "project_id": "40000000-0000-4000-8000-000000000001",
        "experiment_id": "40000000-0000-4000-8000-000000000002",
        "attempt_id": "40000000-0000-4000-8000-000000000003",
        "validation_id": "40000000-0000-4000-8000-000000000004",
    }
    report = _read_json(inputs.ubuntu_report)
    report["golden_ids"] = replacements
    _write_json(inputs.ubuntu_report, report)
    trace_path = inputs.ubuntu_report.parent / "golden-trace.json"
    trace = _read_json(trace_path)
    trace.update(replacements)
    _write_json(trace_path, trace)

    manifest = assemble_release_bundle(inputs, tmp_path / "bundle")

    assert manifest.commit == COMMIT


@pytest.mark.parametrize(
    "case",
    (
        "stale-fingerprint",
        "duplicate-platform",
        "failed-check",
        "required-skip",
        "missing-b-id",
        "empty-acceptance-node",
        "missing-acceptance-evidence",
        "absolute-path",
        "embedded-path",
        "secret",
        "raw-environment",
        "normalized-transcript",
        "shell-call",
        "extra-tool",
        "turn-failed",
        "is-error",
        "forged-root",
        "bool-root",
        "invalid-artifact-hash",
        "extra-check-field",
        "extra-count-field",
        "extra-architecture-field",
        "extra-inventory-field",
        "extra-transcript-field",
        "extra-trace-field",
        "forged-source-inventory",
        "platform-inventory-mismatch",
        "schema-invalid-result",
        "cross-project",
        "cross-attempt",
        "cross-mmir-revision",
        "forged-canonical-hash",
        "forged-model-hash",
        "forged-data-hash",
        "forged-policy-hash",
        "contract-tolerance-failure",
        "embedded-posix-path",
        "embedded-posix-boundary",
        "forged-validation-policy-hash",
        "ubuntu-artifact-hash",
    ),
)
def test_release_assembly_rejects_incomplete_or_unredacted_inputs(
    tmp_path: Path, case: str
) -> None:
    root = tmp_path / case
    inputs = _valid_inputs(root / "inputs")
    ubuntu = inputs.ubuntu_report
    windows = inputs.windows_report
    codex = inputs.codex_transcript

    if case == "stale-fingerprint":
        report = _read_json(ubuntu)
        report["source_fingerprint"] = "sha256:" + "d" * 64
        _write_json(ubuntu, report)
    elif case == "duplicate-platform":
        report = _read_json(ubuntu)
        environment = report["environment"]
        assert isinstance(environment, dict)
        environment["os_family"] = "Windows"
        environment["distribution"] = {"id": "windows", "version": "10.0"}
        _write_json(ubuntu, report)
    elif case == "failed-check":
        report = _read_json(windows)
        checks = report["checks"]
        assert isinstance(checks, list) and isinstance(checks[0], dict)
        checks[0]["status"] = "FAIL"
        _write_json(windows, report)
    elif case == "required-skip":
        report = _read_json(windows)
        report["required_skips"] = 1
        _write_json(windows, report)
    elif case == "missing-b-id":
        report = _read_json(windows)
        acceptance = report["acceptance_map"]
        assert isinstance(acceptance, dict)
        entries = acceptance["entries"]
        assert isinstance(entries, list)
        entries.pop()
        _write_json(windows, report)
    elif case in {"empty-acceptance-node", "missing-acceptance-evidence"}:
        report = _read_json(windows)
        acceptance = report["acceptance_map"]
        assert isinstance(acceptance, dict)
        entries = acceptance["entries"]
        assert isinstance(entries, list) and isinstance(entries[0], dict)
        if case == "empty-acceptance-node":
            entries[0]["test_nodes"] = []
        else:
            entries[0]["evidence"] = []
        _write_json(windows, report)
    elif case in {
        "absolute-path",
        "embedded-path",
        "embedded-posix-path",
        "embedded-posix-boundary",
        "secret",
    }:
        artifact = windows.parent / "architecture-report.json"
        value = _read_json(artifact)
        if case == "absolute-path":
            value["diagnostic"] = "C:\\Users\\release\\artifact.json"
        elif case == "embedded-path":
            value["diagnostic"] = "failed at C:\\Users\\release\\artifact.json"
        elif case == "embedded-posix-path":
            value["diagnostic"] = "failed at /opt/build/artifact.json"
        elif case == "embedded-posix-boundary":
            value["diagnostic"] = "path=/opt/build/artifact.json"
        else:
            value["api_token"] = "sk-release-secret"
        _write_json(artifact, value)
    elif case in {"extra-check-field", "extra-count-field"}:
        report = _read_json(windows)
        checks = report["checks"]
        assert isinstance(checks, list) and isinstance(checks[0], dict)
        if case == "extra-check-field":
            checks[0]["note"] = "looks safe"
        else:
            counts = checks[0]["test_counts"]
            assert isinstance(counts, dict)
            counts["xpassed"] = 0
        _write_json(windows, report)
    elif case in {
        "extra-architecture-field",
        "extra-inventory-field",
        "extra-transcript-field",
        "extra-trace-field",
    }:
        name = {
            "extra-architecture-field": "architecture-report.json",
            "extra-inventory-field": "source-inventory.json",
            "extra-transcript-field": "stdio-transcript.json",
            "extra-trace-field": "golden-trace.json",
        }[case]
        artifact = windows.parent / name
        value = json.loads(artifact.read_text(encoding="utf-8"))
        if case == "extra-inventory-field":
            assert isinstance(value, list) and isinstance(value[0], dict)
            value[0]["mode"] = "0644"
        else:
            assert isinstance(value, dict)
            value["note"] = "looks safe"
        _write_json(artifact, value)
    elif case == "raw-environment":
        report = _read_json(windows)
        environment = report["environment"]
        assert isinstance(environment, dict)
        environment["HOME"] = "C:\\Users\\release"
        _write_json(windows, report)
    elif case in {"forged-source-inventory", "platform-inventory-mismatch"}:
        targets = (windows, ubuntu) if case == "forged-source-inventory" else (ubuntu,)
        for report_path in targets:
            inventory = report_path.parent / "source-inventory.json"
            value = json.loads(inventory.read_text(encoding="utf-8"))
            assert isinstance(value, list) and isinstance(value[0], dict)
            value[0]["sha256"] = "sha256:" + "d" * 64
            _write_json(inventory, value)
    elif case == "ubuntu-artifact-hash":
        trace = ubuntu.parent / "golden-trace.json"
        value = _read_json(trace)
        value["result_hash"] = "sha256:" + "d" * 64
        _write_json(trace, value)
    elif case == "normalized-transcript":
        _codex_transcript(codex)
    elif case in {
        "shell-call",
        "extra-tool",
        "turn-failed",
        "is-error",
        "forged-root",
        "bool-root",
        "schema-invalid-result",
        "cross-project",
        "cross-attempt",
        "cross-mmir-revision",
        "forged-canonical-hash",
        "forged-model-hash",
        "forged-data-hash",
        "forged-policy-hash",
        "forged-validation-policy-hash",
        "contract-tolerance-failure",
    }:
        lines = [
            json.loads(line) for line in codex.read_text(encoding="utf-8").splitlines()
        ]
        items = [line["item"] for line in lines if "item" in line]
        assert all(isinstance(item, dict) for item in items)
        if case == "shell-call":
            lines.append(
                {
                    "type": "item.completed",
                    "item": {"id": "shell", "type": "command_execution"},
                }
            )
        elif case == "extra-tool":
            items[0]["tool"] = "outside_tool"
        elif case == "turn-failed":
            lines.append({"type": "turn.failed", "error": {"message": "failed"}})
        elif case == "is-error":
            result = items[0]["result"]
            assert isinstance(result, dict)
            result["isError"] = True
        elif case == "schema-invalid-result":
            health = next(item for item in items if item["tool"] == "health_check")
            structured = health["result"]["structuredContent"]
            assert isinstance(structured, dict)
            structured["note"] = "looks safe"
        elif case == "cross-project":
            register = next(
                item for item in items if item["tool"] == "register_problem_assets"
            )
            structured = register["result"]["structuredContent"]
            assert isinstance(structured, dict)
            structured["project_id"] = "30000000-0000-4000-8000-000000000001"
        elif case == "cross-attempt":
            validation = next(
                item for item in items if item["tool"] == "validate_experiment"
            )
            structured = validation["result"]["structuredContent"]
            assert isinstance(structured, dict)
            structured["attempt_id"] = "30000000-0000-4000-8000-000000000002"
        elif case == "cross-mmir-revision":
            confirm = next(
                item for item in items if item["tool"] == "confirm_subproblem_mmir"
            )
            structured = confirm["result"]["structuredContent"]
            assert isinstance(structured, dict)
            structured["mmir_revision"] = "sha256:" + "d" * 64
        elif case in {
            "forged-canonical-hash",
            "forged-model-hash",
            "forged-data-hash",
            "contract-tolerance-failure",
        }:
            status = next(
                item for item in items if item["tool"] == "get_project_status"
            )
            structured = status["result"]["structuredContent"]
            assert isinstance(structured, dict)
            experiment = structured["experiment"]
            assert isinstance(experiment, dict)
            if case == "contract-tolerance-failure":
                canonical = experiment["canonical_payload"]
                assert isinstance(canonical, dict)
                canonical["function_tolerance"] = 1e-20
            else:
                field = {
                    "forged-canonical-hash": "canonical_payload_hash",
                    "forged-model-hash": "model_snapshot_hash",
                    "forged-data-hash": "data_snapshot_set_hash",
                }[case]
                experiment[field] = "sha256:" + "d" * 64
        elif case == "forged-policy-hash":
            status = next(
                item for item in items if item["tool"] == "get_project_status"
            )
            structured = status["result"]["structuredContent"]
            assert isinstance(structured, dict)
            trace = structured["trace"]
            assert isinstance(trace, list) and isinstance(trace[1], dict)
            trace[1]["policy_hash"] = "sha256:" + "d" * 64
        elif case == "forged-validation-policy-hash":
            validation = next(
                item for item in items if item["tool"] == "validate_experiment"
            )
            structured = validation["result"]["structuredContent"]
            assert isinstance(structured, dict)
            structured["policy_hash"] = "sha256:" + "d" * 64
        else:
            run = next(item for item in items if item["tool"] == "run_experiment")
            result = run["result"]
            assert isinstance(result, dict)
            structured = result["structuredContent"]
            assert isinstance(structured, dict)
            summary = structured["result_summary"]
            assert isinstance(summary, dict)
            summary["root"] = True if case == "bool-root" else 1.5
        codex.write_text(
            "".join(
                json.dumps(line, separators=(",", ":"), sort_keys=True) + "\n"
                for line in lines
            ),
            encoding="utf-8",
        )
    else:
        trace = windows.parent / "golden-trace.json"
        value = _read_json(trace)
        value["result_hash"] = "not-a-hash"
        _write_json(trace, value)

    destination = root / "bundle"
    with pytest.raises(EvidenceValidationError):
        assemble_release_bundle(inputs, destination)
    assert not destination.exists()


def test_release_validation_rejects_altered_evidence_bytes(tmp_path: Path) -> None:
    destination = tmp_path / "bundle"
    assemble_release_bundle(_valid_inputs(tmp_path / "inputs"), destination)
    target = destination / "trace/golden-trace.json"
    target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(EvidenceValidationError, match="hash"):
        validate_release_bundle(destination, FINGERPRINT)


def test_release_validation_rejects_nested_uninventoried_manifest(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "bundle"
    assemble_release_bundle(_valid_inputs(tmp_path / "inputs"), destination)
    nested = destination / "extra/release-manifest.json"
    nested.parent.mkdir()
    nested.write_text("{}\n", encoding="utf-8")

    with pytest.raises(EvidenceValidationError):
        validate_release_bundle(destination, FINGERPRINT)


def test_release_assembly_revalidates_staging_before_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = release_module._copy_verification_directory

    def tampering_copy(source: Path, destination: Path) -> None:
        original(source, destination)
        artifact = destination / "architecture-report.json"
        value = _read_json(artifact)
        value["diagnostic"] = "failed at C:\\Users\\attacker\\artifact.json"
        _write_json(artifact, value)

    monkeypatch.setattr(release_module, "_copy_verification_directory", tampering_copy)
    destination = tmp_path / "bundle"

    with pytest.raises(EvidenceValidationError):
        assemble_release_bundle(_valid_inputs(tmp_path / "inputs"), destination)
    assert not destination.exists()


def test_release_assembly_rejects_oversized_codex_input(tmp_path: Path) -> None:
    inputs = _valid_inputs(tmp_path / "inputs")
    inputs.codex_transcript.write_bytes(b" " * (8 * 1024 * 1024 + 1))

    with pytest.raises(EvidenceValidationError, match="size"):
        assemble_release_bundle(inputs, tmp_path / "bundle")


def test_release_assembly_normalizes_official_codex_cli_jsonl(tmp_path: Path) -> None:
    inputs = _valid_inputs(tmp_path / "inputs")
    inputs = ReleaseEvidenceInputs(
        windows_report=inputs.windows_report,
        ubuntu_report=inputs.ubuntu_report,
        codex_transcript=_raw_codex_transcript(tmp_path / "raw-codex.jsonl"),
    )
    destination = tmp_path / "bundle"

    assemble_release_bundle(inputs, destination)

    normalized = (destination / "hosts/codex-transcript.jsonl").read_text(
        encoding="utf-8"
    )
    assert "thread_id" not in normalized
    assert "arguments" not in normalized
    assert "structuredContent" not in normalized
    assert {
        json.loads(line)["tool"]
        for line in normalized.splitlines()
        if "tool" in json.loads(line)
    } == set(TOOL_NAMES)


def test_release_evidence_cli_assembles_and_validates(tmp_path: Path) -> None:
    inputs = _valid_inputs(tmp_path / "inputs")
    destination = tmp_path / "bundle"

    assert (
        main(
            [
                "evidence",
                "assemble",
                "--windows-report",
                str(inputs.windows_report),
                "--ubuntu-report",
                str(inputs.ubuntu_report),
                "--codex-transcript",
                str(inputs.codex_transcript),
                "--destination",
                str(destination),
            ]
        )
        == 0
    )
    assert (
        main(
            [
                "evidence",
                "validate",
                "--bundle",
                str(destination),
                "--source-fingerprint",
                FINGERPRINT,
            ]
        )
        == 0
    )
