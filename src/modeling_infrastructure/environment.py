"""Allowlisted environment evidence for M1a summaries and M1b snapshots."""

from __future__ import annotations

import hashlib
import locale
import platform
from pathlib import Path
from typing import Literal, cast

from modeling_core.contracts.capability import (
    CapabilityDescriptor,
    ValidatorDescriptor,
)
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.tools import EnvironmentSummary

_UV_VERSION = "0.11.28"
_APPLICATION_VERSIONS = frozenset({"0.1.0", "0.2.0"})


def _locale_name() -> str:
    try:
        detected = locale.getlocale()
    except ValueError:
        return "und"
    parts = [item for item in detected if item]
    return "_".join(parts) if parts else "und"


def _capability_versions(
    descriptor: CapabilityDescriptor,
) -> list[dict[str, object]]:
    return [
        {
            "capability_id": descriptor.capability_id,
            "contract_version": descriptor.contract_version,
            "implementation_id": descriptor.implementation_id,
            "implementation_version": descriptor.implementation_version,
            "canonical_input_schema_hash": (
                descriptor.canonical_input_schema.schema_hash
            ),
            "input_schema_hash": descriptor.input_schema.schema_hash,
            "success_schema_hash": descriptor.success_schema.schema_hash,
            "failure_schema_hash": descriptor.failure_schema.schema_hash,
        }
    ]


def _validator_versions(
    descriptor: ValidatorDescriptor,
) -> list[dict[str, object]]:
    return [
        {
            "validator_id": descriptor.validator_id,
            "policy_version": descriptor.policy_version,
            "implementation_id": descriptor.implementation_id,
            "implementation_version": descriptor.implementation_version,
        }
    ]


def _numerical_libraries() -> list[dict[str, object]]:
    libraries: list[dict[str, object]] = [
        {"name": "python-math", "version": platform.python_version()}
    ]
    return sorted(libraries, key=lambda item: str(item["name"]))


def capture_environment_summary(
    *, lock_file: Path, application_version: str = "0.1.0"
) -> EnvironmentSummary:
    if application_version not in _APPLICATION_VERSIONS:
        raise ValueError("application_version is unsupported")
    raw_lock = lock_file.read_bytes()
    return EnvironmentSummary(
        python_version=platform.python_version(),
        application_version=cast(Literal["0.1.0", "0.2.0"], application_version),
        lock_hash="sha256:" + hashlib.sha256(raw_lock).hexdigest(),
    )


def capture_environment_snapshot(
    *,
    lock_file: Path,
    capability_descriptor: CapabilityDescriptor,
    validator_descriptor: ValidatorDescriptor,
    application_version: str = "0.1.0",
    uv_version: str = _UV_VERSION,
) -> JsonObject:
    """Build the section 12.4 allowlisted environment snapshot document.

    Records only reproduction-relevant facts. Never records the username,
    hostname, absolute paths, secrets or the full process environment.
    """
    if application_version not in _APPLICATION_VERSIONS:
        raise ValueError("application_version is unsupported")
    raw_lock = lock_file.read_bytes()
    return {
        "python_version": platform.python_version(),
        "uv_version": uv_version,
        "os_name": platform.system(),
        "os_version": platform.release(),
        "architecture": platform.machine(),
        "application_version": application_version,
        "lock_hash": "sha256:" + hashlib.sha256(raw_lock).hexdigest(),
        "capability_versions": _capability_versions(capability_descriptor),
        "validator_versions": _validator_versions(validator_descriptor),
        "numerical_libraries": _numerical_libraries(),
        "locale": _locale_name(),
    }


__all__ = ["capture_environment_snapshot", "capture_environment_summary"]
