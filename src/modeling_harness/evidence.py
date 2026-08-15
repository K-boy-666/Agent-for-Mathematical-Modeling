"""Redacted M1a golden-run evidence written into a caller-owned staging dir."""

from __future__ import annotations

import json
import os
import re
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal, cast


TRANSCRIPT_SCHEMA_VERSION: Final = "m1a-stdio-transcript/0.1.0"
TRACE_SCHEMA_VERSION: Final = "m1a-golden-trace/0.1.0"
TRANSCRIPT_FILENAME: Final = "stdio-transcript.json"
TRACE_FILENAME: Final = "golden-trace.json"
ACCEPTANCE_MAP_SCHEMA_VERSION: Final = "m1a-acceptance-map/0.1.0"
VERIFICATION_REPORT_SCHEMA_VERSION: Final = "m1a-verification-report/0.2.0"

JsonObject = dict[str, object]

_ACCEPTANCE_ARTIFACTS: Final = frozenset(
    {
        "verification-report.json",
        "architecture-report.json",
        "source-inventory.json",
        "package-assets.json",
        "stdio-transcript.json",
        "golden-trace.json",
    }
)
_BARE_ARRAY_ARTIFACTS: Final = frozenset(
    {"source-inventory.json", "package-assets.json"}
)
_BASE_REPORT_KEYS: Final = frozenset(
    {
        "schema_version",
        "milestone",
        "status",
        "source_fingerprint",
        "required_skips",
        "environment",
        "checks",
        "artifacts",
        "golden_ids",
        "incomplete_groups",
    }
)
_ACCEPTANCE_IDS: Final = (
    "A-01",
    "A-02",
    "A-03",
    "A-04",
    "A-05",
    "A-06",
    "A-07",
    "A-08",
    "A-09",
    "A-10",
)
_OUTCOMES: Final = frozenset({"PASSED", "FAILED", "SKIPPED"})
_SELECTOR_PATTERN: Final = re.compile(
    r"tests/(?:[A-Za-z0-9_.\-]+/)*[A-Za-z0-9_\-.]+\.py::"
    r"[A-Za-z0-9_\-.]+(?:\[[^\[\]:{}*]*\])?\Z"
)
_POINTER_LIMIT: Final = 256

_TOOLS: Final = frozenset(
    {
        "health_check",
        "create_project",
        "get_project_status",
        "list_capabilities",
        "run_experiment",
        "validate_experiment",
    }
)
_EVENT_KEYS: Final = frozenset(
    {
        "direction",
        "kind",
        "tool",
        "is_error",
        "status",
        "entity_ids",
        "versions",
        "hashes",
    }
)
_DIRECTIONS: Final = frozenset({"client_to_server", "server_to_client"})
_KINDS: Final = frozenset({"initialize", "tools_list", "tool_call", "tool_result"})
_STATUSES: Final = frozenset(
    {
        "OK",
        "DEGRADED",
        "UNINITIALIZED",
        "STORAGE_READY",
        "READY",
        "PENDING",
        "RUNNING",
        "SUCCEEDED",
        "NUMERICAL_FAILURE",
        "ERRORED",
        "TIMED_OUT",
        "ABANDONED",
        "PASSED",
        "FAILED",
        "INCONCLUSIVE",
        "INVALID_REQUEST",
        "NOT_FOUND",
        "UNSUPPORTED_VERSION",
        "CONFLICT",
        "PRECONDITION_FAILED",
        "SECURITY_VIOLATION",
        "RESOURCE_LIMIT_EXCEEDED",
        "INTEGRITY_FAILURE",
        "INTERNAL_ERROR",
    }
)
_INITIALIZE_VERSIONS: Final = {
    "mcp_protocol": "2025-11-25",
    "application": "0.1.0",
}
_TRACE_KEYS: Final = frozenset(
    {
        "project_id",
        "experiment_id",
        "attempt_id",
        "validation_id",
        "capability_id",
        "contract_version",
        "attempt_status",
        "validation_status",
        "validation_outcome",
        "result_hash",
        "validation_report_hash",
    }
)
_HASH_PATTERN: Final = re.compile(r"sha256:[0-9a-f]{64}\Z")


class EvidenceValidationError(ValueError):
    """Raised when evidence contains fields outside the redacted contract."""


@dataclass(frozen=True)
class GoldenEvidencePaths:
    """Relative artifact paths safe to embed in a verification report."""

    transcript: Path
    trace: Path


def _require_exact_keys(
    value: Mapping[str, object],
    *,
    allowed: frozenset[str],
    required: frozenset[str],
    subject: str,
) -> None:
    keys = frozenset(value)
    unknown = keys - allowed
    missing = required - keys
    if unknown:
        raise EvidenceValidationError(
            f"{subject} contains non-redacted fields: {', '.join(sorted(unknown))}"
        )
    if missing:
        raise EvidenceValidationError(
            f"{subject} is missing fields: {', '.join(sorted(missing))}"
        )


def _require_uuid(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise EvidenceValidationError(f"{field} must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise EvidenceValidationError(f"{field} must be a UUID string") from error
    if str(parsed) != value.lower() or parsed.version != 4:
        raise EvidenceValidationError(f"{field} must be a canonical UUIDv4")
    return value


def _require_hash(value: object, field: str) -> str:
    if not isinstance(value, str) or _HASH_PATTERN.fullmatch(value) is None:
        raise EvidenceValidationError(f"{field} must be a lowercase sha256 hash")
    return value


def _require_short_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 128:
        raise EvidenceValidationError(f"{field} must be non-empty bounded text")
    return value


def _redacted_string_map(
    value: object,
    *,
    field: str,
    value_kind: Literal["uuid", "hash"],
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        raise EvidenceValidationError(f"{field} must be an object")
    redacted: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key or len(key) > 64:
            raise EvidenceValidationError(f"{field} contains an invalid key")
        if value_kind == "uuid":
            redacted[key] = _require_uuid(item, f"{field}.{key}")
        else:
            redacted[key] = _require_hash(item, f"{field}.{key}")
    return redacted


def _redact_transcript(
    transcript: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    if isinstance(transcript, (str, bytes)) or not transcript:
        raise EvidenceValidationError("transcript must contain parsed events")
    redacted: list[dict[str, object]] = []
    for index, event in enumerate(transcript):
        if not isinstance(event, Mapping):
            raise EvidenceValidationError(f"transcript event {index} must be an object")
        _require_exact_keys(
            event,
            allowed=_EVENT_KEYS,
            required=frozenset({"direction", "kind", "is_error", "status"}),
            subject=f"transcript event {index}",
        )
        direction = event["direction"]
        kind = event["kind"]
        is_error = event["is_error"]
        status = event["status"]
        if direction not in _DIRECTIONS:
            raise EvidenceValidationError("transcript direction is invalid")
        if kind not in _KINDS:
            raise EvidenceValidationError("transcript kind is invalid")
        tool = event.get("tool")
        if kind in {"tool_call", "tool_result"}:
            if tool not in _TOOLS:
                raise EvidenceValidationError("transcript tool is invalid")
        elif tool is not None:
            raise EvidenceValidationError(
                "non-tool transcript event cannot name a tool"
            )
        if not isinstance(is_error, bool):
            raise EvidenceValidationError("transcript is_error must be boolean")
        if status is not None and status not in _STATUSES:
            raise EvidenceValidationError("transcript status is invalid")
        normalized: dict[str, object] = {
            "direction": direction,
            "kind": kind,
            "is_error": is_error,
            "status": status,
        }
        if tool is not None:
            normalized["tool"] = tool
        if "entity_ids" in event:
            normalized["entity_ids"] = _redacted_string_map(
                event["entity_ids"], field="entity_ids", value_kind="uuid"
            )
        if kind == "initialize":
            if event.get("versions") != _INITIALIZE_VERSIONS:
                raise EvidenceValidationError(
                    "initialize versions must match the finite M1a allowlist"
                )
            normalized["versions"] = dict(_INITIALIZE_VERSIONS)
        elif "versions" in event:
            raise EvidenceValidationError(
                "versions are allowed only on the initialize event"
            )
        if "hashes" in event:
            normalized["hashes"] = _redacted_string_map(
                event["hashes"], field="hashes", value_kind="hash"
            )
        redacted.append(normalized)
    return redacted


def _redact_trace(trace: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(trace, Mapping):
        raise EvidenceValidationError("trace must be an object")
    _require_exact_keys(
        trace,
        allowed=_TRACE_KEYS,
        required=_TRACE_KEYS,
        subject="trace",
    )
    redacted: dict[str, object] = {}
    for field in ("project_id", "experiment_id", "attempt_id", "validation_id"):
        redacted[field] = _require_uuid(trace[field], field)
    capability_id = _require_short_text(trace["capability_id"], "capability_id")
    if capability_id != "numerical.root_finding":
        raise EvidenceValidationError(
            "capability_id is outside the M1a golden contract"
        )
    redacted["capability_id"] = capability_id
    contract_version = _require_short_text(
        trace["contract_version"], "contract_version"
    )
    if contract_version != "0.1.0":
        raise EvidenceValidationError(
            "contract_version is outside the M1a golden contract"
        )
    redacted["contract_version"] = contract_version
    expected_values = {
        "attempt_status": "SUCCEEDED",
        "validation_status": "SUCCEEDED",
        "validation_outcome": "PASSED",
    }
    for field, expected in expected_values.items():
        if trace[field] != expected:
            raise EvidenceValidationError(f"{field} must be {expected}")
        redacted[field] = expected
    for field in ("result_hash", "validation_report_hash"):
        redacted[field] = _require_hash(trace[field], field)
    return redacted


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        # Both paths share one caller-owned staging directory.  A hard-link
        # publication is atomic and fails if a race winner already exists;
        # unlike os.replace(), it cannot clobber that winner.
        os.link(temporary, path)
        temporary.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()


def write_redacted_golden_evidence(
    staging_dir: Path,
    *,
    transcript: Sequence[Mapping[str, object]],
    trace: Mapping[str, object],
) -> GoldenEvidencePaths:
    """Validate and atomically write two redacted golden artifacts to staging."""
    if not staging_dir.exists():
        raise FileNotFoundError("evidence staging directory does not exist")
    if not staging_dir.is_dir():
        raise NotADirectoryError("evidence staging path is not a directory")
    if staging_dir.is_symlink():
        raise EvidenceValidationError("evidence staging directory cannot be a symlink")

    transcript_path = staging_dir / TRANSCRIPT_FILENAME
    trace_path = staging_dir / TRACE_FILENAME
    if transcript_path.exists() or trace_path.exists():
        raise FileExistsError("golden evidence already exists in staging")

    transcript_document = {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "events": _redact_transcript(transcript),
    }
    trace_document = {
        "schema_version": TRACE_SCHEMA_VERSION,
        **_redact_trace(trace),
    }
    _atomic_write(transcript_path, _json_bytes(transcript_document))
    _atomic_write(trace_path, _json_bytes(trace_document))
    return GoldenEvidencePaths(
        transcript=Path(TRANSCRIPT_FILENAME),
        trace=Path(TRACE_FILENAME),
    )


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    """A redacted pointer into one published evidence artifact."""

    artifact: Literal[
        "verification-report.json",
        "architecture-report.json",
        "source-inventory.json",
        "package-assets.json",
        "stdio-transcript.json",
        "golden-trace.json",
    ]
    json_pointer: str


@dataclass(frozen=True, slots=True)
class RequiredTestNode:
    """One literal pytest node selector required by an acceptance clause."""

    selector: str
    match: Literal["exact", "family"]


@dataclass(frozen=True, slots=True)
class AcceptanceClause:
    """A conjunction of owned nodes and resolving success evidence."""

    clause_id: str
    required_nodes: tuple[RequiredTestNode, ...]
    check_ids: tuple[str, ...]
    success_evidence: tuple[EvidenceReference, ...]


@dataclass(frozen=True, slots=True)
class AcceptanceRequirement:
    """One A-01..A-10 acceptance requirement with its clauses."""

    acceptance_id: Literal[
        "A-01",
        "A-02",
        "A-03",
        "A-04",
        "A-05",
        "A-06",
        "A-07",
        "A-08",
        "A-09",
        "A-10",
    ]
    clauses: tuple[AcceptanceClause, ...]


def _utf8(value: str) -> bytes:
    return value.encode("utf-8")


def _validate_evidence_reference(reference: EvidenceReference) -> None:
    if reference.artifact not in _ACCEPTANCE_ARTIFACTS:
        raise EvidenceValidationError(
            "acceptance evidence artifact is outside the published set"
        )
    pointer = reference.json_pointer
    if not isinstance(pointer, str) or not pointer or len(pointer) > _POINTER_LIMIT:
        if pointer == "" and reference.artifact in _BARE_ARRAY_ARTIFACTS:
            return
        raise EvidenceValidationError(
            "acceptance evidence pointer must be non-empty bounded text"
        )
    if reference.artifact == "verification-report.json" and pointer.startswith(
        "/acceptance_map"
    ):
        raise EvidenceValidationError(
            "acceptance evidence cannot point into the acceptance map"
        )
    if not pointer.startswith("/") or any(
        token == "" for token in pointer[1:].split("/")
    ):
        raise EvidenceValidationError("acceptance evidence pointer is malformed")


def validate_m1a_acceptance_policy(
    *,
    requirements: Sequence[AcceptanceRequirement],
    allowed_check_ids: Sequence[str],
) -> None:
    """Phase 1: validate acceptance policy shape and syntax only."""
    allowed = tuple(allowed_check_ids)
    if not allowed or len(set(allowed)) != len(allowed):
        raise EvidenceValidationError("allowed check ids must be non-empty and unique")
    identifiers = [requirement.acceptance_id for requirement in requirements]
    if (
        len(identifiers) != len(_ACCEPTANCE_IDS)
        or tuple(identifiers) != _ACCEPTANCE_IDS
    ):
        raise EvidenceValidationError(
            "acceptance policy must declare exactly A-01 through A-10 in order"
        )
    seen_clauses: set[str] = set()
    for requirement in requirements:
        if not requirement.clauses:
            raise EvidenceValidationError("acceptance clauses are incomplete")
        for clause in requirement.clauses:
            if not clause.clause_id:
                raise EvidenceValidationError("acceptance clause id is empty")
            if clause.clause_id in seen_clauses:
                raise EvidenceValidationError("acceptance clause id is duplicated")
            seen_clauses.add(clause.clause_id)
            selectors = [node.selector for node in clause.required_nodes]
            if not selectors:
                raise EvidenceValidationError("acceptance clause has no nodes")
            if len(set(selectors)) != len(selectors):
                raise EvidenceValidationError("acceptance nodes are duplicated")
            if selectors != sorted(selectors, key=_utf8):
                raise EvidenceValidationError("acceptance nodes are unsorted")
            for node in clause.required_nodes:
                if node.match not in ("exact", "family"):
                    raise EvidenceValidationError("acceptance node match is invalid")
                if _SELECTOR_PATTERN.fullmatch(node.selector) is None:
                    raise EvidenceValidationError(
                        "acceptance node selector is not a literal tests/ node"
                    )
            if not clause.check_ids:
                raise EvidenceValidationError("acceptance clause owns no checks")
            if len(set(clause.check_ids)) != len(clause.check_ids):
                raise EvidenceValidationError("acceptance clause checks are duplicated")
            if list(clause.check_ids) != sorted(clause.check_ids, key=_utf8):
                raise EvidenceValidationError("acceptance clause checks are unsorted")
            if any(check not in allowed for check in clause.check_ids):
                raise EvidenceValidationError(
                    "acceptance clause declares an unknown check"
                )
            if not clause.success_evidence:
                raise EvidenceValidationError("acceptance clause has no evidence")
            pairs = [
                (item.artifact, item.json_pointer) for item in clause.success_evidence
            ]
            if len(set(pairs)) != len(pairs):
                raise EvidenceValidationError("acceptance evidence is duplicated")
            if pairs != sorted(
                pairs, key=lambda pair: (_utf8(pair[0]), _utf8(pair[1]))
            ):
                raise EvidenceValidationError("acceptance evidence is unsorted")
            for reference in clause.success_evidence:
                _validate_evidence_reference(reference)


def _validate_phase_two_inputs(
    base_report: Mapping[str, object],
    artifact_documents: Mapping[str, object],
) -> None:
    if not isinstance(base_report, Mapping):
        raise EvidenceValidationError("base report must be an object")
    keys = frozenset(base_report)
    if keys != _BASE_REPORT_KEYS:
        raise EvidenceValidationError(
            "base report must contain exactly the ten legacy keys"
        )
    if not isinstance(artifact_documents, Mapping):
        raise EvidenceValidationError("artifact documents must be an object")
    if frozenset(artifact_documents) != _ACCEPTANCE_ARTIFACTS:
        raise EvidenceValidationError(
            "artifact documents must contain exactly the six evidence artifacts"
        )
    if artifact_documents["verification-report.json"] is not base_report:
        raise EvidenceValidationError(
            "verification-report evidence must resolve against the base report"
        )
    checks = base_report["checks"]
    if not isinstance(checks, list):
        raise EvidenceValidationError("base report checks must be an array")


def _resolve_pointer(document: object, pointer: str) -> bool:
    if pointer == "":
        return True
    current: object = document
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, Mapping) and token in current:
            current = current[token]
        elif isinstance(current, list) and token.isdigit():
            index = int(token)
            if index >= len(current):
                return False
            current = current[index]
        else:
            return False
    return True


def materialize_m1a_acceptance_map(
    *,
    requirements: Sequence[AcceptanceRequirement],
    base_report: Mapping[str, object],
    artifact_documents: Mapping[str, object],
    observed_test_outcomes: Mapping[
        str, Mapping[str, Literal["PASSED", "FAILED", "SKIPPED"]]
    ],
) -> JsonObject:
    """Phase 2: materialize the acceptance map from current-run evidence."""
    _validate_phase_two_inputs(base_report, artifact_documents)
    outcomes_by_check: dict[str, dict[str, str]] = {}
    for observed_check, observed_nodes in observed_test_outcomes.items():
        if not isinstance(observed_check, str) or not isinstance(
            observed_nodes, Mapping
        ):
            raise EvidenceValidationError("observed test outcomes are malformed")
        mapping: dict[str, str] = {}
        for node_id, outcome in observed_nodes.items():
            if outcome not in _OUTCOMES:
                raise EvidenceValidationError("observed test outcome is invalid")
            mapping[node_id] = outcome
        outcomes_by_check[observed_check] = mapping

    check_positions: dict[str, int] = {}
    check_status: dict[str, str] = {}
    reconciled: dict[str, bool] = {}
    checks = cast(list[object], base_report["checks"])
    for position, entry in enumerate(checks):
        if not isinstance(entry, Mapping):
            raise EvidenceValidationError("base report check must be an object")
        entry_check_id = entry.get("check_id")
        entry_check_status = entry.get("status")
        entry_nodes = entry.get("test_nodes")
        if not isinstance(entry_check_id, str) or not isinstance(
            entry_check_status, str
        ):
            raise EvidenceValidationError("base report check is malformed")
        if entry_nodes is not None and not isinstance(entry_nodes, list):
            raise EvidenceValidationError("base report test nodes are malformed")
        check_positions[entry_check_id] = position
        check_status[entry_check_id] = entry_check_status
        reconciled[entry_check_id] = entry_nodes is None or set(
            outcomes_by_check.get(entry_check_id, {})
        ) == set(entry_nodes)

    entries: list[JsonObject] = []
    entry_status: dict[str, str] = {}
    for requirement in requirements:
        node_documents: list[JsonObject] = []
        failure_pointers: set[tuple[str, str]] = set()
        satisfied = True
        for clause in requirement.clauses:
            for check_id in clause.check_ids:
                if check_id not in check_positions:
                    satisfied = False
                    continue
                position = check_positions[check_id]
                if check_status[check_id] != "PASS" or not reconciled[check_id]:
                    satisfied = False
                    failure_pointers.add(
                        ("verification-report.json", f"/checks/{position}/status")
                    )
                    failure_pointers.add(
                        ("verification-report.json", f"/checks/{position}/test_nodes")
                    )
                    diagnostic = cast(Mapping[str, object], checks[position]).get(
                        "diagnostic_code"
                    )
                    if diagnostic is not None:
                        failure_pointers.add(
                            (
                                "verification-report.json",
                                f"/checks/{position}/diagnostic_code",
                            )
                        )
                    if check_id == "stdio-golden":
                        failure_pointers.add(("stdio-transcript.json", "/status"))
                        failure_pointers.add(
                            ("stdio-transcript.json", "/diagnostic_code")
                        )
                        failure_pointers.add(("golden-trace.json", "/status"))
                        failure_pointers.add(("golden-trace.json", "/diagnostic_code"))
            for node in clause.required_nodes:
                observations: list[str] = []
                matched_nodes: set[str] = set()
                if node.match == "exact":
                    for check_id in clause.check_ids:
                        observed_outcome = outcomes_by_check.get(check_id, {}).get(
                            node.selector
                        )
                        if observed_outcome is not None:
                            observations.append(observed_outcome)
                            matched_nodes.add(node.selector)
                else:
                    prefix = node.selector + "["
                    for check_id in clause.check_ids:
                        for candidate in outcomes_by_check.get(check_id, {}):
                            if candidate == node.selector or (
                                candidate.startswith(prefix) and candidate.endswith("]")
                            ):
                                matched_nodes.add(candidate)
                                observations.append(
                                    outcomes_by_check[check_id][candidate]
                                )
                if not observations or any(
                    outcome != "PASSED" for outcome in observations
                ):
                    satisfied = False
                    for check_id in clause.check_ids:
                        if check_id not in check_positions:
                            continue
                        position = check_positions[check_id]
                        failure_pointers.add(
                            ("verification-report.json", f"/checks/{position}/status")
                        )
                        failure_pointers.add(
                            (
                                "verification-report.json",
                                f"/checks/{position}/test_nodes",
                            )
                        )
                node_documents.append(
                    {
                        "selector": node.selector,
                        "match": node.match,
                        "observed_nodes": sorted(matched_nodes, key=_utf8),
                    }
                )
            for reference in clause.success_evidence:
                document = artifact_documents[reference.artifact]
                if not _resolve_pointer(document, reference.json_pointer):
                    satisfied = False
        evidence: list[JsonObject] = [
            {"artifact": item.artifact, "json_pointer": item.json_pointer}
            for clause in requirement.clauses
            for item in clause.success_evidence
        ]
        if not satisfied:
            extra: list[JsonObject] = [
                {"artifact": artifact, "json_pointer": pointer}
                for artifact, pointer in sorted(
                    failure_pointers, key=lambda pair: (_utf8(pair[0]), _utf8(pair[1]))
                )
            ]
            evidence.extend(item for item in extra if item not in evidence)
        status = "PASS" if satisfied else "FAIL"
        entry_status[requirement.acceptance_id] = status
        entries.append(
            {
                "acceptance_id": requirement.acceptance_id,
                "status": status,
                "test_nodes": node_documents,
                "evidence": evidence,
            }
        )

    if base_report.get("status") == "FAILED" and entry_status.get("A-10") == "PASS":
        for entry in entries:
            if entry["acceptance_id"] == "A-10":
                entry["status"] = "FAIL"
                for pointer in ("/status", "/source_fingerprint"):
                    item: JsonObject = {
                        "artifact": "verification-report.json",
                        "json_pointer": pointer,
                    }
                    if item not in cast(list[object], entry["evidence"]):
                        cast(list[object], entry["evidence"]).append(item)

    return {
        "schema_version": ACCEPTANCE_MAP_SCHEMA_VERSION,
        "source_fingerprint": base_report["source_fingerprint"],
        "entries": entries,
    }


def validate_m1a_acceptance_report(report: Mapping[str, object]) -> None:
    """Validate the exact eleven-key report with an embedded acceptance map."""
    if not isinstance(report, Mapping):
        raise EvidenceValidationError("verification report must be an object")
    if frozenset(report) != _BASE_REPORT_KEYS | {"acceptance_map"}:
        raise EvidenceValidationError(
            "verification report must contain exactly eleven keys"
        )
    if report["schema_version"] != VERIFICATION_REPORT_SCHEMA_VERSION:
        raise EvidenceValidationError("verification report version is invalid")
    acceptance_map = report["acceptance_map"]
    if not isinstance(acceptance_map, Mapping):
        raise EvidenceValidationError("acceptance map must be an object")
    if frozenset(acceptance_map) != {
        "schema_version",
        "source_fingerprint",
        "entries",
    }:
        raise EvidenceValidationError("acceptance map must contain exactly three keys")
    if acceptance_map["schema_version"] != ACCEPTANCE_MAP_SCHEMA_VERSION:
        raise EvidenceValidationError("acceptance map version is invalid")
    if acceptance_map["source_fingerprint"] != report["source_fingerprint"]:
        raise EvidenceValidationError("acceptance map fingerprint mismatch")
    entries = acceptance_map["entries"]
    if not isinstance(entries, list) or len(entries) != len(_ACCEPTANCE_IDS):
        raise EvidenceValidationError("acceptance map must declare ten entries")
    for position, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise EvidenceValidationError("acceptance entry must be an object")
        if frozenset(entry) != {
            "acceptance_id",
            "status",
            "test_nodes",
            "evidence",
        }:
            raise EvidenceValidationError("acceptance entry keys are invalid")
        if entry["acceptance_id"] != _ACCEPTANCE_IDS[position]:
            raise EvidenceValidationError("acceptance entries are out of order")
        if entry["status"] not in ("PASS", "FAIL"):
            raise EvidenceValidationError("acceptance entry status is invalid")
        nodes = entry["test_nodes"]
        if not isinstance(nodes, list):
            raise EvidenceValidationError("acceptance entry nodes are invalid")
        for node in nodes:
            if not isinstance(node, Mapping) or frozenset(node) != {
                "selector",
                "match",
                "observed_nodes",
            }:
                raise EvidenceValidationError("acceptance node keys are invalid")
            observed = node["observed_nodes"]
            if not isinstance(observed, list) or observed != sorted(
                observed, key=_utf8
            ):
                raise EvidenceValidationError("observed nodes must be sorted")
        evidence = entry["evidence"]
        if not isinstance(evidence, list):
            raise EvidenceValidationError("acceptance entry evidence is invalid")
        for item in evidence:
            if not isinstance(item, Mapping) or frozenset(item) != {
                "artifact",
                "json_pointer",
            }:
                raise EvidenceValidationError("acceptance evidence keys are invalid")
            if item["artifact"] not in _ACCEPTANCE_ARTIFACTS:
                raise EvidenceValidationError(
                    "acceptance evidence artifact is outside the published set"
                )


__all__ = [
    "ACCEPTANCE_MAP_SCHEMA_VERSION",
    "AcceptanceClause",
    "AcceptanceRequirement",
    "EvidenceReference",
    "EvidenceValidationError",
    "GoldenEvidencePaths",
    "JsonObject",
    "RequiredTestNode",
    "TRACE_SCHEMA_VERSION",
    "TRANSCRIPT_SCHEMA_VERSION",
    "VERIFICATION_REPORT_SCHEMA_VERSION",
    "materialize_m1a_acceptance_map",
    "validate_m1a_acceptance_policy",
    "validate_m1a_acceptance_report",
    "write_redacted_golden_evidence",
]
