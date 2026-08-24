"""Deterministic, offline assembly of the final M1 release evidence bundle."""

from __future__ import annotations

import hashlib
import math
import os
import re
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Final, cast

from modeling_core.contracts.canonical_json import (
    canonical_json_bytes,
    sha256_json,
    strict_json_loads,
)
from modeling_core.contracts.common import JsonValue
from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.tools import TOOL_NAMES
from modeling_harness.evidence import (
    EvidenceValidationError,
    _redact_trace,
    _redact_transcript,
    validate_m1b_acceptance_report,
)


RELEASE_MANIFEST_SCHEMA_VERSION: Final = "m1-release-bundle/1.0.0"
_REPORT_SCHEMA_VERSION: Final = "m1b-verification-report/1.0.0"
_ACCEPTANCE_SCHEMA_VERSION: Final = "m1b-acceptance-map/1.0.0"
_HASH_PATTERN: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COMMIT_PATTERN: Final = re.compile(r"[0-9a-f]{40}\Z")
_SECRET_KEY_PATTERN: Final = re.compile(
    r"(?:authorization|api[_-]?key|password|secret|token)", re.IGNORECASE
)
_SECRET_VALUE_PATTERN: Final = re.compile(
    r"(?:\bBearer\s+\S+|\bsk-[A-Za-z0-9_-]{8,}|\bgh[oprsu]_[A-Za-z0-9]{8,})",
    re.IGNORECASE,
)
_EMBEDDED_PATH_PATTERN: Final = re.compile(
    r"(?:[A-Za-z]:[\\/]|\\\\[^\\\s]+[\\/]|(?:^|[^A-Za-z0-9_:/])/(?!/)[^\s]*)"
)
_MAX_FILE_BYTES: Final = 8 * 1024 * 1024
_MAX_BUNDLE_BYTES: Final = 64 * 1024 * 1024
_MAX_JSON_DEPTH: Final = 64
_UNREDACTED_KEYS: Final = frozenset(
    {"arguments", "command", "input", "output", "payload", "raw_environment"}
)
_ACCEPTANCE_IDS: Final = tuple(
    f"{prefix}-{number:02d}" for prefix in ("A", "B") for number in range(1, 11)
)
_VERIFICATION_FILES: Final = (
    "SUMMARY.md",
    "architecture-report.json",
    "golden-trace.json",
    "package-assets.json",
    "source-inventory.json",
    "stdio-transcript.json",
    "verification-report.json",
)
_ARTIFACT_MAP: Final = {
    "architecture_report": "architecture-report.json",
    "golden_trace": "golden-trace.json",
    "package_assets": "package-assets.json",
    "source_inventory": "source-inventory.json",
    "stdio_transcript": "stdio-transcript.json",
}
_ENVIRONMENT_KEYS: Final = frozenset(
    {
        "architecture",
        "distribution",
        "lock_sha256",
        "os_family",
        "os_version",
        "python_version",
        "uv_executable_sha256",
        "uv_version",
    }
)
_REPORT_KEYS: Final = frozenset(
    {
        "acceptance_map",
        "artifacts",
        "checks",
        "commit",
        "environment",
        "golden_ids",
        "incomplete_groups",
        "milestone",
        "required_skips",
        "schema_version",
        "source_fingerprint",
        "status",
    }
)
_REPORT_GROUPS: Final = {
    "schema/compatibility-report.json": (
        "stable-schema-corpus",
        "canonical-json-conformance",
        "pytest-contract",
    ),
    "math/reproducibility-report.json": (
        "pytest-math",
        "pytest-reproducibility",
        "affine-math",
        "restart-reproducibility",
    ),
    "recovery/fault-report.json": ("recovery-rerun", "fault-windows"),
    "security/security-report.json": ("pytest-security", "m1b-security"),
}
_CHECK_KEYS: Final = frozenset(
    {
        "check_id",
        "status",
        "duration_ms",
        "exit_code",
        "test_counts",
        "test_nodes",
        "diagnostic_code",
    }
)
_COUNT_KEYS: Final = frozenset({"total", "passed", "failed", "errors", "skipped"})


def _expected_payload_paths() -> frozenset[str]:
    return frozenset(
        {
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
                for name in _VERIFICATION_FILES
            },
        }
    )


@dataclass(frozen=True)
class ReleaseEvidenceInputs:
    """Operator-provided, already-produced evidence paths."""

    windows_report: Path
    ubuntu_report: Path
    codex_transcript: Path


@dataclass(frozen=True)
class ReleaseFile:
    """One payload file covered by the release manifest."""

    path: str
    sha256: str
    byte_size: int


@dataclass(frozen=True)
class ReleaseBundleManifest:
    """Validated manifest returned after deterministic assembly."""

    source_fingerprint: str
    commit: str
    files: tuple[ReleaseFile, ...]


@dataclass(frozen=True)
class ReleaseValidationReport:
    """Successful validation result; failures raise before construction."""

    valid: bool
    source_fingerprint: str
    commit: str
    file_count: int


def _hash_bytes(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _json_bytes(value: JsonValue) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _read_bytes(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise EvidenceValidationError("release evidence input is missing or unsafe")
    try:
        if path.stat().st_size > _MAX_FILE_BYTES:
            raise EvidenceValidationError("release evidence file size exceeds limit")
        payload = path.read_bytes()
    except OSError as error:
        raise EvidenceValidationError(
            "release evidence input cannot be read"
        ) from error
    if len(payload) > _MAX_FILE_BYTES:
        raise EvidenceValidationError("release evidence file size exceeds limit")
    return payload


def _read_json(path: Path) -> JsonValue:
    try:
        return strict_json_loads(_read_bytes(path))
    except (RecursionError, TypeError, ValueError) as error:
        raise EvidenceValidationError("release evidence JSON is invalid") from error


def _mapping(value: object, subject: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise EvidenceValidationError(f"{subject} must be an object")
    return cast(Mapping[str, object], value)


def _hash(value: object, subject: str) -> str:
    if not isinstance(value, str) or _HASH_PATTERN.fullmatch(value) is None:
        raise EvidenceValidationError(f"{subject} must be a lowercase sha256 hash")
    return value


def _is_absolute_path(value: str) -> bool:
    return (
        PureWindowsPath(value).is_absolute()
        or PurePosixPath(value).is_absolute()
        or value.startswith("\\\\")
    )


def _scan_redacted(value: object, *, field: str | None = None, depth: int = 0) -> None:
    if depth > _MAX_JSON_DEPTH:
        raise EvidenceValidationError("evidence nesting depth exceeds limit")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise EvidenceValidationError("evidence object key must be text")
            if _SECRET_KEY_PATTERN.search(key):
                raise EvidenceValidationError("secret-shaped field is forbidden")
            if key.lower() in _UNREDACTED_KEYS:
                raise EvidenceValidationError("unredacted payload field is forbidden")
            _scan_redacted(item, field=key, depth=depth + 1)
    elif isinstance(value, list):
        for item in value:
            _scan_redacted(item, field=field, depth=depth + 1)
    elif isinstance(value, str):
        if _SECRET_VALUE_PATTERN.search(value):
            raise EvidenceValidationError("secret-shaped value is forbidden")
        if field != "json_pointer" and (
            _is_absolute_path(value) or _EMBEDDED_PATH_PATTERN.search(value)
        ):
            raise EvidenceValidationError("absolute path is forbidden in evidence")


def _validate_environment(value: object, platform_name: str) -> Mapping[str, object]:
    environment = _mapping(value, "verification environment")
    if frozenset(environment) != _ENVIRONMENT_KEYS:
        raise EvidenceValidationError("verification environment is not redacted")
    distribution = _mapping(environment["distribution"], "distribution")
    if frozenset(distribution) != {"id", "version"}:
        raise EvidenceValidationError("distribution is not redacted")
    expected_family = "Windows" if platform_name == "windows" else "Linux"
    expected_distribution = "windows" if platform_name == "windows" else "ubuntu"
    if environment["os_family"] != expected_family:
        raise EvidenceValidationError("verification platform is duplicated or missing")
    if str(distribution["id"]).lower() != expected_distribution:
        raise EvidenceValidationError("verification distribution is invalid")
    if environment["uv_version"] != "0.11.28" or not str(
        environment["python_version"]
    ).startswith("3.11."):
        raise EvidenceValidationError("verification toolchain is invalid")
    _hash(environment["lock_sha256"], "lock hash")
    _hash(environment["uv_executable_sha256"], "uv executable hash")
    return environment


def _pointer_value(document: object, pointer: str) -> object:
    current = document
    for raw_token in pointer.removeprefix("/").split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif (
            isinstance(current, list) and token.isdigit() and int(token) < len(current)
        ):
            current = current[int(token)]
        else:
            raise EvidenceValidationError(
                "acceptance evidence pointer does not resolve"
            )
    return current


def _validate_acceptance(report: Mapping[str, object]) -> Mapping[str, object]:
    validate_m1b_acceptance_report(report)
    acceptance = _mapping(report["acceptance_map"], "acceptance map")
    entries = cast(list[object], acceptance["entries"])
    checks = {
        cast(str, check["check_id"]): check
        for value in cast(list[object], report["checks"])
        for check in (_mapping(value, "verification check"),)
    }
    from modeling_harness.verify import _M1B_ACCEPTANCE_REQUIREMENTS

    for requirement, entry_value in zip(_M1B_ACCEPTANCE_REQUIREMENTS, entries):
        entry = _mapping(entry_value, "acceptance entry")
        if entry["status"] != "PASS":
            raise EvidenceValidationError("acceptance entry did not pass")
        expected_nodes = [
            (clause, node)
            for clause in requirement.clauses
            for node in clause.required_nodes
        ]
        actual_nodes = cast(list[object], entry["test_nodes"])
        if len(actual_nodes) != len(expected_nodes):
            raise EvidenceValidationError("acceptance test nodes are incomplete")
        for (clause, expected_node), actual_value in zip(expected_nodes, actual_nodes):
            actual = _mapping(actual_value, "acceptance test node")
            if (
                actual["selector"] != expected_node.selector
                or actual["match"] != expected_node.match
            ):
                raise EvidenceValidationError("acceptance test node policy mismatch")
            observed = actual["observed_nodes"]
            if not isinstance(observed, list) or not observed:
                raise EvidenceValidationError("acceptance test node was not observed")
            prefix = expected_node.selector + "["
            if any(
                not isinstance(item, str)
                or (
                    item != expected_node.selector
                    and not (
                        expected_node.match == "family"
                        and item.startswith(prefix)
                        and item.endswith("]")
                    )
                )
                for item in observed
            ):
                raise EvidenceValidationError("acceptance observed node is invalid")
            owning_nodes = {
                node
                for check_id in clause.check_ids
                for node in cast(list[str] | None, checks[check_id]["test_nodes"]) or []
            }
            if not set(observed) <= owning_nodes:
                raise EvidenceValidationError("acceptance node lacks check evidence")
        expected_evidence = [
            {
                "artifact": reference.artifact,
                "json_pointer": reference.json_pointer,
            }
            for clause in requirement.clauses
            for reference in clause.success_evidence
        ]
        if entry["evidence"] != expected_evidence:
            raise EvidenceValidationError("acceptance evidence pointers are incomplete")
        for evidence in expected_evidence:
            if (
                evidence["artifact"] != "verification-report.json"
                or _pointer_value(report, evidence["json_pointer"]) != "PASS"
            ):
                raise EvidenceValidationError("acceptance evidence is not PASS")
    return acceptance


def _validate_checks(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise EvidenceValidationError("verification checks must be a non-empty array")
    identifiers: list[str] = []
    for check_value in value:
        check = _mapping(check_value, "verification check")
        if frozenset(check) != _CHECK_KEYS:
            raise EvidenceValidationError("verification check keys are invalid")
        check_id = check.get("check_id")
        if not isinstance(check_id, str) or not check_id:
            raise EvidenceValidationError("verification check ID is invalid")
        identifiers.append(check_id)
        if check.get("status") != "PASS":
            raise EvidenceValidationError("verification check did not pass")
        if (
            isinstance(check["duration_ms"], bool)
            or not isinstance(check["duration_ms"], int)
            or check["duration_ms"] < 0
            or check["exit_code"] != 0
            or check["diagnostic_code"] is not None
        ):
            raise EvidenceValidationError("verification check metadata is invalid")
        counts = check.get("test_counts")
        if counts is not None:
            counts = _mapping(counts, "verification test counts")
            if frozenset(counts) != _COUNT_KEYS or any(
                isinstance(count, bool) or not isinstance(count, int) or count < 0
                for count in counts.values()
            ):
                raise EvidenceValidationError("verification test counts are invalid")
            if (
                counts["failed"] != 0
                or counts["errors"] != 0
                or counts["skipped"] != 0
                or counts["total"] != counts["passed"]
            ):
                raise EvidenceValidationError(
                    "verification check contains a required failure or skip"
                )
        nodes = check["test_nodes"]
        if nodes is not None and (
            not isinstance(nodes, list)
            or not all(isinstance(node, str) and node for node in nodes)
            or nodes != sorted(set(nodes), key=lambda node: node.encode("utf-8"))
        ):
            raise EvidenceValidationError("verification test nodes are invalid")
    if len(set(identifiers)) != len(identifiers):
        raise EvidenceValidationError("verification check IDs are duplicated")
    from modeling_harness.verify import M1B_CHECK_IDS

    if tuple(identifiers) != M1B_CHECK_IDS:
        raise EvidenceValidationError("verification check profile is incomplete")
    return tuple(identifiers)


def _validate_report(path: Path, platform_name: str) -> Mapping[str, object]:
    if path.name != "verification-report.json":
        raise EvidenceValidationError("verification report filename is invalid")
    report = _mapping(_read_json(path), "verification report")
    if frozenset(report) != _REPORT_KEYS:
        raise EvidenceValidationError("verification report keys are invalid")
    if (
        report["schema_version"] != _REPORT_SCHEMA_VERSION
        or report["milestone"] != "m1b"
    ):
        raise EvidenceValidationError("verification report version is invalid")
    if report["status"] != "PASSED":
        raise EvidenceValidationError("verification report did not pass")
    _hash(report["source_fingerprint"], "source fingerprint")
    commit = report["commit"]
    if not isinstance(commit, str) or _COMMIT_PATTERN.fullmatch(commit) is None:
        raise EvidenceValidationError("verification commit is invalid")
    if report["required_skips"] != 0:
        raise EvidenceValidationError("verification report contains required skips")
    if report["incomplete_groups"] != []:
        raise EvidenceValidationError("verification report has incomplete groups")
    _validate_environment(report["environment"], platform_name)
    _validate_checks(report["checks"])
    _validate_acceptance(report)
    if report["artifacts"] != _ARTIFACT_MAP:
        raise EvidenceValidationError("verification artifact map is invalid")
    _scan_redacted(report)
    return report


def _validate_verification_directory(
    report_path: Path, expected_fingerprint: str
) -> JsonValue:
    directory = report_path.parent
    if directory.is_symlink() or not directory.is_dir():
        raise EvidenceValidationError("verification evidence directory is unsafe")
    names = tuple(sorted(path.name for path in directory.iterdir()))
    if names != _VERIFICATION_FILES or any(
        not path.is_file() or path.is_symlink() for path in directory.iterdir()
    ):
        raise EvidenceValidationError("verification evidence file set is invalid")
    documents: dict[str, JsonValue] = {}
    for name in _VERIFICATION_FILES:
        path = directory / name
        if path.suffix == ".json":
            documents[name] = _read_json(path)
            _scan_redacted(documents[name])
        else:
            try:
                text = _read_bytes(path).decode("utf-8", errors="strict")
            except UnicodeDecodeError as error:
                raise EvidenceValidationError("evidence text must be UTF-8") from error
            _scan_redacted(text)
    architecture = _mapping(documents["architecture-report.json"], "architecture")
    if (
        frozenset(architecture)
        != {"schema_version", "status", "check_id", "test_counts"}
        or architecture["schema_version"] != "m1b-architecture-report/1.0.0"
        or architecture["status"] != "PASS"
        or architecture["check_id"] != "pytest-architecture"
    ):
        raise EvidenceValidationError("architecture report is invalid")
    counts = _mapping(architecture["test_counts"], "architecture test counts")
    if (
        frozenset(counts) != _COUNT_KEYS
        or counts["failed"] != 0
        or counts["errors"] != 0
        or counts["skipped"] != 0
        or counts["total"] != counts["passed"]
    ):
        raise EvidenceValidationError("architecture test counts are invalid")
    for name in ("source-inventory.json", "package-assets.json"):
        _validate_inventory_document(documents[name], name)
    source_inventory = documents["source-inventory.json"]
    if sha256_json(source_inventory) != expected_fingerprint:
        raise EvidenceValidationError("source inventory fingerprint disagrees")
    transcript = _mapping(documents["stdio-transcript.json"], "STDIO transcript")
    if (
        frozenset(transcript) != {"schema_version", "events"}
        or transcript["schema_version"] != "m1a-stdio-transcript/0.1.0"
    ):
        raise EvidenceValidationError("STDIO transcript is invalid")
    events = transcript["events"]
    if not isinstance(events, list) or _redact_transcript(events) != events:
        raise EvidenceValidationError("STDIO transcript events are invalid")
    golden = _validate_golden_trace(documents["golden-trace.json"])
    report = _mapping(documents["verification-report.json"], "verification report")
    golden_ids = _mapping(report["golden_ids"], "golden IDs")
    if any(golden.get(field) != value for field, value in golden_ids.items()):
        raise EvidenceValidationError("verification golden IDs disagree")
    return source_inventory


def _validate_inventory_document(value: object, subject: str) -> None:
    if not isinstance(value, list) or not value:
        raise EvidenceValidationError(f"{subject} must be a non-empty array")
    paths: list[str] = []
    for item_value in value:
        item = _mapping(item_value, subject)
        if frozenset(item) != {"path", "sha256"}:
            raise EvidenceValidationError(f"{subject} entry keys are invalid")
        path = item["path"]
        if (
            not isinstance(path, str)
            or not path
            or "\\" in path
            or PurePosixPath(path).is_absolute()
            or any(part in {"", ".", ".."} for part in PurePosixPath(path).parts)
        ):
            raise EvidenceValidationError(f"{subject} path is invalid")
        _hash(item["sha256"], f"{subject} hash")
        paths.append(path)
    if paths != sorted(set(paths), key=lambda path: path.encode("utf-8")):
        raise EvidenceValidationError(f"{subject} is unsorted or duplicated")


def _validate_golden_trace(value: object) -> Mapping[str, object]:
    trace = _mapping(value, "golden trace")
    if trace.get("schema_version") != "m1a-golden-trace/0.1.0":
        raise EvidenceValidationError("golden trace version is invalid")
    payload = {key: item for key, item in trace.items() if key != "schema_version"}
    if _redact_trace(payload) != payload:
        raise EvidenceValidationError("golden trace is invalid")
    root = trace.get("root")
    residual = trace.get("residual")
    if root is not None or residual is not None:
        if (
            isinstance(root, bool)
            or not isinstance(root, (int, float))
            or not math.isfinite(float(root))
        ):
            raise EvidenceValidationError("golden root is not finite")
        if (
            isinstance(residual, bool)
            or not isinstance(residual, (int, float))
            or not math.isfinite(float(residual))
            or abs(float(residual)) > 1e-10
        ):
            raise EvidenceValidationError("golden residual is invalid")
    _hash(trace.get("result_hash"), "result artifact hash")
    _hash(trace.get("validation_report_hash"), "validation artifact hash")
    return trace


def _structured_result(value: object) -> Mapping[str, object]:
    if isinstance(value, str):
        try:
            value = strict_json_loads(value.encode("utf-8"))
        except (RecursionError, TypeError, ValueError) as error:
            raise EvidenceValidationError("Codex MCP result is invalid") from error
    result = _mapping(value, "Codex MCP result")
    if "structured_content" in result:
        if "isError" in result and result["isError"] is not False:
            raise EvidenceValidationError("Codex MCP result is an error")
        return _mapping(result["structured_content"], "Codex structured result")
    if result.get("isError") is not False:
        raise EvidenceValidationError("Codex MCP result is an error")
    return _mapping(result.get("structuredContent"), "Codex structured result")


def _finite_number(value: object, subject: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EvidenceValidationError(f"{subject} is not finite")
    result = float(value)
    if not math.isfinite(result):
        raise EvidenceValidationError(f"{subject} is not finite")
    return result


def _artifact_identity(value: object, role: str, payload: JsonValue) -> str:
    artifact = _mapping(value, f"{role} artifact")
    if artifact.get("role") != role:
        raise EvidenceValidationError("Codex artifact role is invalid")
    artifact_id = _hash(artifact.get("artifact_id"), "artifact ID")
    if artifact.get("sha256") != artifact_id:
        raise EvidenceValidationError("Codex artifact identity disagrees")
    if artifact.get("size_bytes") != len(canonical_json_bytes(payload)):
        raise EvidenceValidationError("Codex artifact byte size disagrees")
    return artifact_id


def _golden_result(
    calls: Sequence[tuple[str, Mapping[str, object]]],
) -> dict[str, object]:
    counts = {tool: sum(name == tool for name, _ in calls) for tool in TOOL_NAMES}
    if any(
        count != 1 and not (tool == "get_project_status" and count == 2)
        for tool, count in counts.items()
    ):
        raise EvidenceValidationError("Codex tool call count is ambiguous")
    runs = [
        result
        for tool, result in calls
        if tool == "run_experiment" and result.get("attempt_status") == "SUCCEEDED"
    ]
    validations = [
        result
        for tool, result in calls
        if tool == "validate_experiment"
        and result.get("validation_status") == "SUCCEEDED"
        and result.get("outcome") == "PASSED"
    ]
    traces = [
        result
        for tool, result in calls
        if tool == "get_project_status" and result.get("view") == "experiment"
    ]
    if len(runs) != 1 or len(validations) != 1 or len(traces) != 1:
        raise EvidenceValidationError("Codex golden chain is incomplete or ambiguous")
    run = runs[0]
    validation = validations[0]
    trace_result = traces[0]
    trace = trace_result.get("trace")
    if not isinstance(trace, list):
        raise EvidenceValidationError("Codex experiment trace is invalid")
    attempts = [
        _mapping(item, "attempt trace")
        for item in trace
        if isinstance(item, Mapping)
        and item.get("record_type") == "attempt"
        and item.get("status") == "SUCCEEDED"
    ]
    validation_traces = [
        _mapping(item, "validation trace")
        for item in trace
        if isinstance(item, Mapping)
        and item.get("record_type") == "validation"
        and item.get("status") == "SUCCEEDED"
        and item.get("outcome") == "PASSED"
    ]
    if len(attempts) != 1 or len(validation_traces) != 1:
        raise EvidenceValidationError("Codex persisted golden trace is ambiguous")
    attempt = attempts[0]
    validation_trace = validation_traces[0]
    persisted_result = _mapping(attempt.get("result"), "persisted result")
    result_payload = _mapping(
        persisted_result.get("result_payload"), "persisted result payload"
    )
    report_payload = _mapping(
        validation_trace.get("report_payload"), "persisted validation report"
    )
    recomputed_result_hash = sha256_json(cast(JsonValue, dict(result_payload)))
    recomputed_report_hash = sha256_json(cast(JsonValue, dict(report_payload)))

    experiment = _mapping(trace_result.get("experiment"), "Codex experiment")
    project = _mapping(trace_result.get("project"), "Codex project")
    canonical = _mapping(experiment.get("canonical_payload"), "canonical input")
    expression = _mapping(canonical.get("expression_ast"), "golden expression")
    expected_expression: JsonValue = {
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
    if (
        dict(expression) != expected_expression
        or canonical.get("lower") != 0.0
        or canonical.get("upper") != 2.0
    ):
        raise EvidenceValidationError("Codex golden input is not x*x-2 on [0,2]")
    canonical_value = cast(JsonValue, dict(canonical))
    canonical_hash = sha256_json(canonical_value)
    model_hash = sha256_json({"language": "math-expr-v1", "ast": expected_expression})
    references = experiment.get("data_snapshot_references")
    if not isinstance(references, list):
        raise EvidenceValidationError("Codex data snapshot references are invalid")
    data_hash = sha256_json(cast(JsonValue, references))
    policy = validation_trace.get("policy")
    if not isinstance(policy, dict):
        raise EvidenceValidationError("Codex validation policy is invalid")
    policy_hash = sha256_json(cast(JsonValue, policy))
    named_hashes = {
        "canonical_payload_hash": canonical_hash,
        "model_snapshot_hash": model_hash,
        "data_snapshot_set_hash": data_hash,
    }
    if any(
        experiment.get(field) != expected or report_payload.get(field) != expected
        for field, expected in named_hashes.items()
    ) or any(
        value != policy_hash
        for value in (
            validation.get("policy_hash"),
            validation_trace.get("policy_hash"),
            report_payload.get("policy_hash"),
        )
    ):
        raise EvidenceValidationError("Codex named input or policy hash disagrees")
    data = _mapping(result_payload.get("data"), "result payload data")
    root = _finite_number(data.get("root"), "Codex root")
    lower = _finite_number(canonical.get("lower"), "Codex lower bound")
    upper = _finite_number(canonical.get("upper"), "Codex upper bound")
    tolerance = _finite_number(
        canonical.get("function_tolerance"), "Codex function tolerance"
    )
    reported = _finite_number(data.get("function_value"), "Codex function value")
    recomputed = root * root - 2.0
    delta = abs(recomputed - reported)
    residual = abs(recomputed)
    if not lower <= root <= upper or residual > tolerance or delta > tolerance:
        raise EvidenceValidationError("Codex independently recomputed residual failed")
    summary = _mapping(run.get("result_summary"), "Codex result summary")
    if dict(summary) != dict(data):
        raise EvidenceValidationError("Codex result summary disagrees with payload")
    metrics = _mapping(report_payload.get("metrics"), "validation metrics")
    expected_metrics = {
        "root_within_interval": True,
        "reported_function_value": reported,
        "recomputed_function_value": recomputed,
        "absolute_reported_delta": delta,
        "absolute_residual": residual,
        "function_tolerance": tolerance,
        "failed_checks": [],
    }
    if dict(metrics) != expected_metrics or report_payload.get("outcome") != "PASSED":
        raise EvidenceValidationError("Codex validation metrics disagree")
    if (
        validation.get("metrics") != expected_metrics
        or validation_trace.get("metrics") != expected_metrics
    ):
        raise EvidenceValidationError("Codex validation result metrics disagree")

    create = next(result for tool, result in calls if tool == "create_project")
    register = next(
        result for tool, result in calls if tool == "register_problem_assets"
    )
    put = next(result for tool, result in calls if tool == "put_subproblem_mmir")
    confirm = next(
        result for tool, result in calls if tool == "confirm_subproblem_mmir"
    )
    exported = next(result for tool, result in calls if tool == "export_subproblem")
    project_id = create.get("project_id")
    experiment_id = run.get("experiment_id")
    attempt_id = run.get("attempt_id")
    validation_id = validation.get("validation_id")
    if (
        any(
            value != project_id
            for value in (
                project.get("project_id"),
                experiment.get("project_id"),
                register.get("project_id"),
                put.get("project_id"),
                confirm.get("project_id"),
                exported.get("project_id"),
            )
        )
        or any(
            value != experiment_id
            for value in (experiment.get("experiment_id"), attempt.get("experiment_id"))
        )
        or any(
            value != attempt_id
            for value in (
                attempt.get("attempt_id"),
                validation.get("attempt_id"),
                validation_trace.get("attempt_id"),
            )
        )
        or validation_trace.get("validation_id") != validation_id
    ):
        raise EvidenceValidationError("Codex golden entity chain disagrees")
    subproblem_id = put.get("subproblem_id")
    mmir_revision = put.get("mmir_revision")
    exports = exported.get("exports")
    if (
        not isinstance(register.get("snapshots"), list)
        or not register["snapshots"]
        or confirm.get("subproblem_id") != subproblem_id
        or confirm.get("mmir_revision") != mmir_revision
        or confirm.get("status") != "CONFIRMED"
        or exported.get("subproblem_id") != subproblem_id
        or not isinstance(exports, list)
        or not any(
            isinstance(item, Mapping)
            and item.get("kind") == "mmir"
            and item.get("sha256") == mmir_revision
            for item in exports
        )
    ):
        raise EvidenceValidationError("Codex MMIR chain disagrees")

    run_hash = _hash(run.get("result_hash"), "Codex run result hash")
    run_artifacts = run.get("artifacts")
    if not isinstance(run_artifacts, list) or len(run_artifacts) != 1:
        raise EvidenceValidationError("Codex result artifact is missing")
    result_artifact_id = _artifact_identity(
        run_artifacts[0], "result", cast(JsonValue, dict(result_payload))
    )
    expected_result_hash = _hash(
        validation_trace.get("expected_result_hash"), "expected result hash"
    )
    result_hashes = {
        recomputed_result_hash,
        run_hash,
        result_artifact_id,
        _hash(persisted_result.get("result_hash"), "persisted result hash"),
        _hash(validation.get("result_hash"), "validation result hash"),
        _hash(validation_trace.get("result_hash"), "trace result hash"),
        expected_result_hash,
        _hash(report_payload.get("result_hash"), "report result hash"),
    }
    if len(result_hashes) != 1:
        raise EvidenceValidationError("Codex result four-way hash check failed")

    report_hash = _hash(
        validation.get("validation_report_hash"), "validation report hash"
    )
    report_artifact_id = _artifact_identity(
        validation.get("report_artifact"),
        "validation_report",
        cast(JsonValue, dict(report_payload)),
    )
    report_hashes = {
        recomputed_report_hash,
        report_hash,
        report_artifact_id,
        _hash(
            validation_trace.get("validation_report_hash"),
            "trace validation report hash",
        ),
    }
    if len(report_hashes) != 1:
        raise EvidenceValidationError("Codex report artifact hash check failed")
    return {
        "type": "result",
        "status": "PASS",
        "root": root,
        "residual": residual,
        "function_tolerance": tolerance,
        "validation_outcome": "PASSED",
        "result_hash": run_hash,
        "result_artifact_id": result_artifact_id,
        "recomputed_result_hash": recomputed_result_hash,
        "expected_result_hash": expected_result_hash,
        "validation_report_hash": report_hash,
        "report_artifact_id": report_artifact_id,
        "recomputed_validation_report_hash": recomputed_report_hash,
        "canonical_payload_hash": canonical_hash,
        "model_snapshot_hash": model_hash,
        "data_snapshot_set_hash": data_hash,
        "policy_hash": policy_hash,
        "project_id": project_id,
        "experiment_id": experiment_id,
        "attempt_id": attempt_id,
        "validation_id": validation_id,
        "subproblem_id": subproblem_id,
        "mmir_revision": mmir_revision,
    }


def _normalize_codex_cli(
    events: Sequence[Mapping[str, object]],
    *,
    raw_hash: str,
    commit: str,
    source_fingerprint: str,
) -> tuple[list[JsonValue], Mapping[str, object]]:
    thread_ids = [
        event.get("thread_id")
        for event in events
        if event.get("type") == "thread.started"
    ]
    completed_turns = [
        event for event in events if event.get("type") == "turn.completed"
    ]
    failed_turns = [
        event for event in events if event.get("type") in {"turn.failed", "error"}
    ]
    if (
        len(thread_ids) != 1
        or not isinstance(thread_ids[0], str)
        or not thread_ids[0]
        or len(completed_turns) != 1
        or failed_turns
    ):
        raise EvidenceValidationError("Codex CLI turn did not complete successfully")
    all_call_ids: set[str] = set()
    completed_ids: set[str] = set()
    calls: list[tuple[str, Mapping[str, object]]] = []
    catalog = SchemaCatalog.load_packaged("1.0.0")
    allowed_non_mcp_items = {"agent_message", "reasoning"}
    for event in events:
        if not str(event.get("type", "")).startswith("item."):
            continue
        item = _mapping(event.get("item"), "Codex item")
        item_type = item.get("type")
        if item_type != "mcp_tool_call":
            if item_type not in allowed_non_mcp_items:
                raise EvidenceValidationError(
                    "Codex shell or non-MCP item is forbidden"
                )
            continue
        call_id = item.get("id")
        if not isinstance(call_id, str) or not call_id:
            raise EvidenceValidationError("Codex MCP call ID is invalid")
        all_call_ids.add(call_id)
        if event.get("type") != "item.completed":
            continue
        if call_id in completed_ids:
            raise EvidenceValidationError("Codex MCP completion is duplicated")
        if (
            item.get("status") not in {"completed", "succeeded"}
            or item.get("error") is not None
        ):
            raise EvidenceValidationError("Codex MCP call did not pass")
        server = item.get("server")
        tool = item.get("tool")
        if server != "modeling" or tool not in TOOL_NAMES:
            raise EvidenceValidationError("Codex used a tool outside the allowlist")
        completed_ids.add(call_id)
        structured = _structured_result(item.get("result"))
        if next(catalog.validator(tool, "result").iter_errors(dict(structured)), None):
            raise EvidenceValidationError("Codex MCP result violates its 1.0 schema")
        calls.append((tool, structured))
    if all_call_ids != completed_ids:
        raise EvidenceValidationError("Codex MCP call is incomplete")
    tools = [tool for tool, _ in calls]
    if set(tools) != set(TOOL_NAMES):
        raise EvidenceValidationError("Codex tool coverage is incomplete")
    result = _golden_result(calls)
    documents: list[JsonValue] = [
        {
            "type": "session",
            "status": "PASS",
            "server": "modeling",
            "raw_evidence_sha256": raw_hash,
            "commit": commit,
            "source_fingerprint": source_fingerprint,
        }
    ]
    documents.extend(
        {
            "type": "mcp_tool_call",
            "server": "modeling",
            "tool": tool,
            "status": "PASS",
        }
        for tool in tools
    )
    documents.append(cast(JsonValue, result))
    return documents, result


def _jsonl(
    path: Path, *, require_redacted: bool = False
) -> tuple[bytes, list[Mapping[str, object]]]:
    payload = _read_bytes(path)
    lines = payload.splitlines()
    if not lines or len(lines) > 2000:
        raise EvidenceValidationError("Codex transcript event count is invalid")
    parsed: list[Mapping[str, object]] = []
    for raw_line in lines:
        try:
            value = strict_json_loads(raw_line)
            if require_redacted:
                _scan_redacted(value)
            parsed.append(_mapping(value, "Codex transcript event"))
        except (RecursionError, TypeError, ValueError) as error:
            raise EvidenceValidationError(
                "Codex transcript JSONL is invalid"
            ) from error
    return payload, parsed


def _normalize_codex_transcript(
    path: Path, *, commit: str, source_fingerprint: str
) -> tuple[list[JsonValue], Mapping[str, object]]:
    payload, events = _jsonl(path)
    if events[0].get("type") != "thread.started":
        raise EvidenceValidationError("official Codex CLI transcript is required")
    return _normalize_codex_cli(
        events,
        raw_hash=_hash_bytes(payload),
        commit=commit,
        source_fingerprint=source_fingerprint,
    )


def _validate_normalized_result(result: Mapping[str, object]) -> None:
    if frozenset(result) != {
        "type",
        "status",
        "root",
        "residual",
        "validation_outcome",
        "result_hash",
        "result_artifact_id",
        "recomputed_result_hash",
        "expected_result_hash",
        "validation_report_hash",
        "report_artifact_id",
        "recomputed_validation_report_hash",
        "canonical_payload_hash",
        "model_snapshot_hash",
        "data_snapshot_set_hash",
        "policy_hash",
        "function_tolerance",
        "project_id",
        "experiment_id",
        "attempt_id",
        "validation_id",
        "subproblem_id",
        "mmir_revision",
    }:
        raise EvidenceValidationError("normalized Codex result keys are invalid")
    root = _finite_number(result["root"], "normalized Codex root")
    residual = _finite_number(result["residual"], "normalized Codex residual")
    tolerance = _finite_number(
        result["function_tolerance"], "normalized Codex tolerance"
    )
    if (
        result["status"] != "PASS"
        or result["validation_outcome"] != "PASSED"
        or residual != abs(root * root - 2.0)
        or residual > tolerance
    ):
        raise EvidenceValidationError("normalized Codex mathematics is invalid")
    if (
        len(
            {
                _hash(result[field], field)
                for field in (
                    "result_hash",
                    "result_artifact_id",
                    "recomputed_result_hash",
                    "expected_result_hash",
                )
            }
        )
        != 1
        or len(
            {
                _hash(result[field], field)
                for field in (
                    "validation_report_hash",
                    "report_artifact_id",
                    "recomputed_validation_report_hash",
                )
            }
        )
        != 1
    ):
        raise EvidenceValidationError("normalized Codex artifact hashes disagree")
    for field in (
        "canonical_payload_hash",
        "model_snapshot_hash",
        "data_snapshot_set_hash",
        "policy_hash",
        "mmir_revision",
    ):
        _hash(result[field], field)
    for field in (
        "project_id",
        "experiment_id",
        "attempt_id",
        "validation_id",
        "subproblem_id",
    ):
        if not isinstance(result[field], str) or not result[field]:
            raise EvidenceValidationError("normalized Codex entity ID is invalid")


def _validate_normalized_codex(
    path: Path, *, commit: str, source_fingerprint: str
) -> tuple[list[JsonValue], Mapping[str, object]]:
    _, events = _jsonl(path, require_redacted=True)
    documents: list[JsonValue] = []
    tools: list[str] = []
    result: Mapping[str, object] | None = None
    sessions = 0
    for event in events:
        event_type = event.get("type")
        if event_type == "session":
            sessions += 1
            if frozenset(event) != {
                "type",
                "status",
                "server",
                "raw_evidence_sha256",
                "commit",
                "source_fingerprint",
            }:
                raise EvidenceValidationError("normalized Codex session is invalid")
            if (
                event["status"] != "PASS"
                or event["server"] != "modeling"
                or event["commit"] != commit
                or event["source_fingerprint"] != source_fingerprint
            ):
                raise EvidenceValidationError("normalized Codex session binding failed")
            _hash(event["raw_evidence_sha256"], "raw Codex evidence hash")
        elif event_type == "mcp_tool_call":
            if frozenset(event) != {"type", "server", "tool", "status"}:
                raise EvidenceValidationError("normalized Codex tool event is invalid")
            tool = event["tool"]
            if (
                event["server"] != "modeling"
                or tool not in TOOL_NAMES
                or event["status"] != "PASS"
            ):
                raise EvidenceValidationError("normalized Codex tool event failed")
            tools.append(tool)
        elif event_type == "result":
            if result is not None:
                raise EvidenceValidationError("normalized Codex result is duplicated")
            result = event
            _validate_normalized_result(result)
        else:
            raise EvidenceValidationError("normalized Codex event type is invalid")
        documents.append(cast(JsonValue, dict(event)))
    if sessions != 1 or set(tools) != set(TOOL_NAMES) or result is None:
        raise EvidenceValidationError("normalized Codex evidence is incomplete")
    return documents, result


def _write_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())


def _copy_verification_directory(source: Path, destination: Path) -> None:
    for name in _VERIFICATION_FILES:
        source_path = source / name
        payload = _read_bytes(source_path)
        if source_path.suffix == ".json":
            payload = _json_bytes(_read_json(source_path))
        _write_file(destination / name, payload)


def _check_report(check_ids: Sequence[str]) -> JsonValue:
    return {
        "schema_version": "m1-release-check-report/1.0.0",
        "status": "PASS",
        "check_ids": list(check_ids),
    }


def _inventory(root: Path) -> tuple[ReleaseFile, ...]:
    files: list[ReleaseFile] = []
    total_bytes = 0
    root_manifest = root / "release-manifest.json"
    for path in root.rglob("*"):
        if path.is_symlink():
            raise EvidenceValidationError("release bundle cannot contain symlinks")
        if not path.is_file() or path == root_manifest:
            continue
        relative = path.relative_to(root).as_posix()
        payload = _read_bytes(path)
        total_bytes += len(payload)
        if len(payload) > _MAX_FILE_BYTES or total_bytes > _MAX_BUNDLE_BYTES:
            raise EvidenceValidationError("release bundle size exceeds limit")
        files.append(
            ReleaseFile(
                path=relative,
                sha256=_hash_bytes(payload),
                byte_size=len(payload),
            )
        )
    return tuple(sorted(files, key=lambda item: item.path.encode("utf-8")))


def _manifest_document(manifest: ReleaseBundleManifest) -> JsonValue:
    return {
        "schema_version": RELEASE_MANIFEST_SCHEMA_VERSION,
        "source_fingerprint": manifest.source_fingerprint,
        "commit": manifest.commit,
        "platforms": ["ubuntu", "windows"],
        "tool_names": list(TOOL_NAMES),
        "acceptance_ids": list(_ACCEPTANCE_IDS),
        "files": [
            {"path": item.path, "sha256": item.sha256, "byte_size": item.byte_size}
            for item in manifest.files
        ],
    }


def assemble_release_bundle(
    inputs: ReleaseEvidenceInputs, destination: Path
) -> ReleaseBundleManifest:
    """Validate operator inputs and atomically publish one canonical bundle."""
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("release bundle destination already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    windows = _validate_report(inputs.windows_report, "windows")
    ubuntu = _validate_report(inputs.ubuntu_report, "ubuntu")
    windows_inventory = _validate_verification_directory(
        inputs.windows_report, cast(str, windows["source_fingerprint"])
    )
    ubuntu_inventory = _validate_verification_directory(
        inputs.ubuntu_report, cast(str, ubuntu["source_fingerprint"])
    )
    for field in ("source_fingerprint", "commit"):
        if windows[field] != ubuntu[field]:
            raise EvidenceValidationError(f"platform {field} mismatch")
    if windows["acceptance_map"] != ubuntu["acceptance_map"]:
        raise EvidenceValidationError("platform acceptance maps disagree")
    if windows_inventory != ubuntu_inventory:
        raise EvidenceValidationError("platform source inventories disagree")
    windows_environment = _mapping(windows["environment"], "Windows environment")
    ubuntu_environment = _mapping(ubuntu["environment"], "Ubuntu environment")
    if windows_environment["lock_sha256"] != ubuntu_environment["lock_sha256"]:
        raise EvidenceValidationError("platform lock hash mismatch")
    if tuple(
        _mapping(item, "Windows check")["check_id"]
        for item in cast(list[object], windows["checks"])
    ) != tuple(
        _mapping(item, "Ubuntu check")["check_id"]
        for item in cast(list[object], ubuntu["checks"])
    ):
        raise EvidenceValidationError("platform check profile mismatch")

    codex_documents, codex_result = _normalize_codex_transcript(
        inputs.codex_transcript,
        commit=cast(str, windows["commit"]),
        source_fingerprint=cast(str, windows["source_fingerprint"]),
    )
    golden = _validate_golden_trace(
        _read_json(inputs.windows_report.parent / "golden-trace.json")
    )
    ubuntu_golden = _validate_golden_trace(
        _read_json(inputs.ubuntu_report.parent / "golden-trace.json")
    )
    for field in ("result_hash", "validation_report_hash"):
        if len({golden[field], ubuntu_golden[field], codex_result[field]}) != 1:
            raise EvidenceValidationError("platform and Codex artifact hashes disagree")

    staging = Path(
        tempfile.mkdtemp(prefix=f".{destination.name}.", dir=destination.parent)
    )
    try:
        _copy_verification_directory(
            inputs.windows_report.parent, staging / "verification/windows"
        )
        _copy_verification_directory(
            inputs.ubuntu_report.parent, staging / "verification/ubuntu"
        )
        acceptance = cast(JsonValue, windows["acceptance_map"])
        generic = _read_json(inputs.windows_report.parent / "stdio-transcript.json")
        golden_value = cast(JsonValue, dict(golden))
        _write_file(staging / "acceptance/coverage-map.json", _json_bytes(acceptance))
        _write_file(staging / "stdio/generic-mcp-transcript.json", _json_bytes(generic))
        _write_file(staging / "trace/golden-trace.json", _json_bytes(golden_value))
        codex_payload = b"".join(_json_bytes(document) for document in codex_documents)
        _write_file(staging / "hosts/codex-transcript.jsonl", codex_payload)

        checks = tuple(
            cast(str, _mapping(item, "check")["check_id"])
            for item in cast(list[object], windows["checks"])
        )
        for relative, required in _REPORT_GROUPS.items():
            if any(check not in checks for check in required):
                raise EvidenceValidationError(
                    "release report check coverage is incomplete"
                )
            _write_file(staging / relative, _json_bytes(_check_report(required)))

        generic_payload = _json_bytes(generic)
        golden_payload = _json_bytes(golden_value)
        artifact_hashes: JsonValue = {
            "schema_version": "m1-artifact-hashes/1.0.0",
            **{
                field: codex_result[field]
                for field in (
                    "result_hash",
                    "result_artifact_id",
                    "recomputed_result_hash",
                    "expected_result_hash",
                    "validation_report_hash",
                    "report_artifact_id",
                    "recomputed_validation_report_hash",
                    "canonical_payload_hash",
                    "model_snapshot_hash",
                    "data_snapshot_set_hash",
                    "policy_hash",
                )
            },
            "golden_trace_sha256": _hash_bytes(golden_payload),
            "generic_transcript_sha256": _hash_bytes(generic_payload),
        }
        _write_file(
            staging / "trace/artifact-hashes.json", _json_bytes(artifact_hashes)
        )
        summary = (
            "# M1 release evidence\n\n"
            f"Status: PASSED\nCommit: {windows['commit']}\n"
            f"Source fingerprint: {windows['source_fingerprint']}\n"
            "Platforms: Ubuntu, Windows\n"
        ).encode("utf-8")
        _write_file(staging / "SUMMARY.md", summary)

        files = _inventory(staging)
        manifest = ReleaseBundleManifest(
            source_fingerprint=cast(str, windows["source_fingerprint"]),
            commit=cast(str, windows["commit"]),
            files=files,
        )
        _write_file(
            staging / "release-manifest.json", _json_bytes(_manifest_document(manifest))
        )
        validate_release_bundle(staging, manifest.source_fingerprint)
        from modeling_harness.verify import _atomic_publish_directory

        _atomic_publish_directory(staging, destination)
        return manifest
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _load_manifest(bundle: Path) -> ReleaseBundleManifest:
    document = _mapping(
        _read_json(bundle / "release-manifest.json"), "release manifest"
    )
    if frozenset(document) != {
        "schema_version",
        "source_fingerprint",
        "commit",
        "platforms",
        "tool_names",
        "acceptance_ids",
        "files",
    }:
        raise EvidenceValidationError("release manifest keys are invalid")
    if document["schema_version"] != RELEASE_MANIFEST_SCHEMA_VERSION:
        raise EvidenceValidationError("release manifest version is invalid")
    fingerprint = _hash(document["source_fingerprint"], "manifest fingerprint")
    commit = document["commit"]
    if not isinstance(commit, str) or _COMMIT_PATTERN.fullmatch(commit) is None:
        raise EvidenceValidationError("manifest commit is invalid")
    if document["platforms"] != ["ubuntu", "windows"]:
        raise EvidenceValidationError("manifest platforms are invalid")
    if document["tool_names"] != list(TOOL_NAMES):
        raise EvidenceValidationError("manifest tool names are invalid")
    if document["acceptance_ids"] != list(_ACCEPTANCE_IDS):
        raise EvidenceValidationError("manifest acceptance IDs are invalid")
    values = document["files"]
    if not isinstance(values, list):
        raise EvidenceValidationError("manifest files must be an array")
    files: list[ReleaseFile] = []
    for value in values:
        item = _mapping(value, "manifest file")
        if frozenset(item) != {"path", "sha256", "byte_size"}:
            raise EvidenceValidationError("manifest file keys are invalid")
        path = item["path"]
        byte_size = item["byte_size"]
        if (
            not isinstance(path, str)
            or PurePosixPath(path).is_absolute()
            or ".." in PurePosixPath(path).parts
            or isinstance(byte_size, bool)
            or not isinstance(byte_size, int)
            or byte_size < 0
        ):
            raise EvidenceValidationError("manifest file path or size is invalid")
        files.append(
            ReleaseFile(
                path=path,
                sha256=_hash(item["sha256"], "manifest file hash"),
                byte_size=byte_size,
            )
        )
    ordered = tuple(sorted(files, key=lambda item: item.path.encode("utf-8")))
    if tuple(files) != ordered or len({item.path for item in files}) != len(files):
        raise EvidenceValidationError("manifest files are unsorted or duplicated")
    if frozenset(item.path for item in files) != _expected_payload_paths():
        raise EvidenceValidationError("release bundle file set is invalid")
    return ReleaseBundleManifest(fingerprint, commit, tuple(files))


def validate_release_bundle(
    path: Path, expected_source_fingerprint: str
) -> ReleaseValidationReport:
    """Recompute every payload hash and validate all cross-file relationships."""
    expected = _hash(expected_source_fingerprint, "expected source fingerprint")
    if not path.is_dir() or path.is_symlink():
        raise EvidenceValidationError("release bundle is missing or unsafe")
    manifest = _load_manifest(path)
    if manifest.source_fingerprint != expected:
        raise EvidenceValidationError("release bundle fingerprint is stale")
    actual = _inventory(path)
    if actual != manifest.files:
        raise EvidenceValidationError("release bundle file inventory or hash mismatch")
    windows_path = path / "verification/windows/verification-report.json"
    ubuntu_path = path / "verification/ubuntu/verification-report.json"
    windows = _validate_report(windows_path, "windows")
    ubuntu = _validate_report(ubuntu_path, "ubuntu")
    windows_inventory = _validate_verification_directory(
        windows_path, cast(str, windows["source_fingerprint"])
    )
    ubuntu_inventory = _validate_verification_directory(
        ubuntu_path, cast(str, ubuntu["source_fingerprint"])
    )
    if windows_inventory != ubuntu_inventory:
        raise EvidenceValidationError("platform source inventories disagree")
    if any(
        report["source_fingerprint"] != expected or report["commit"] != manifest.commit
        for report in (windows, ubuntu)
    ):
        raise EvidenceValidationError(
            "release manifest does not match platform reports"
        )
    coverage = _read_json(path / "acceptance/coverage-map.json")
    generic = _read_json(path / "stdio/generic-mcp-transcript.json")
    golden_value = _read_json(path / "trace/golden-trace.json")
    if coverage != windows["acceptance_map"]:
        raise EvidenceValidationError("release acceptance coverage disagrees")
    if generic != _read_json(
        path / "verification/windows/stdio-transcript.json"
    ) or golden_value != _read_json(path / "verification/windows/golden-trace.json"):
        raise EvidenceValidationError("release trace evidence disagrees")
    codex_documents, codex_result = _validate_normalized_codex(
        path / "hosts/codex-transcript.jsonl",
        commit=manifest.commit,
        source_fingerprint=manifest.source_fingerprint,
    )
    if not codex_documents or not codex_result:
        raise EvidenceValidationError("Codex evidence is incomplete")
    golden = _validate_golden_trace(golden_value)
    ubuntu_golden = _validate_golden_trace(
        _read_json(path / "verification/ubuntu/golden-trace.json")
    )
    hashes = _mapping(
        _read_json(path / "trace/artifact-hashes.json"), "artifact hashes"
    )
    if (
        frozenset(hashes)
        != {
            "schema_version",
            "result_hash",
            "result_artifact_id",
            "recomputed_result_hash",
            "expected_result_hash",
            "validation_report_hash",
            "report_artifact_id",
            "recomputed_validation_report_hash",
            "canonical_payload_hash",
            "model_snapshot_hash",
            "data_snapshot_set_hash",
            "policy_hash",
            "golden_trace_sha256",
            "generic_transcript_sha256",
        }
        or hashes["schema_version"] != "m1-artifact-hashes/1.0.0"
    ):
        raise EvidenceValidationError("artifact hash report is invalid")
    for field in (
        "result_hash",
        "result_artifact_id",
        "recomputed_result_hash",
        "expected_result_hash",
        "validation_report_hash",
        "report_artifact_id",
        "recomputed_validation_report_hash",
        "canonical_payload_hash",
        "model_snapshot_hash",
        "data_snapshot_set_hash",
        "policy_hash",
    ):
        if hashes.get(field) != codex_result[field]:
            raise EvidenceValidationError("release artifact hashes disagree")
    for field in ("result_hash", "validation_report_hash"):
        if len({golden[field], ubuntu_golden[field], codex_result[field]}) != 1:
            raise EvidenceValidationError("platform and Codex artifact hashes disagree")
    if hashes["golden_trace_sha256"] != _hash_bytes(
        _json_bytes(golden_value)
    ) or hashes["generic_transcript_sha256"] != _hash_bytes(_json_bytes(generic)):
        raise EvidenceValidationError("release evidence hashes disagree")
    for relative, check_ids in _REPORT_GROUPS.items():
        if _read_json(path / relative) != _check_report(check_ids):
            raise EvidenceValidationError("derived release report disagrees")
    return ReleaseValidationReport(
        valid=True,
        source_fingerprint=manifest.source_fingerprint,
        commit=manifest.commit,
        file_count=len(manifest.files),
    )


__all__ = [
    "RELEASE_MANIFEST_SCHEMA_VERSION",
    "ReleaseBundleManifest",
    "ReleaseEvidenceInputs",
    "ReleaseFile",
    "ReleaseValidationReport",
    "assemble_release_bundle",
    "validate_release_bundle",
]
