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
from typing import Final, Literal


TRANSCRIPT_SCHEMA_VERSION: Final = "m1a-stdio-transcript/0.1.0"
TRACE_SCHEMA_VERSION: Final = "m1a-golden-trace/0.1.0"
TRANSCRIPT_FILENAME: Final = "stdio-transcript.json"
TRACE_FILENAME: Final = "golden-trace.json"

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


__all__ = [
    "EvidenceValidationError",
    "GoldenEvidencePaths",
    "TRACE_SCHEMA_VERSION",
    "TRANSCRIPT_SCHEMA_VERSION",
    "write_redacted_golden_evidence",
]
