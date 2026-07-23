from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from math import inf, nan

import pytest
from pydantic import TypeAdapter, ValidationError

from modeling_core.contracts.canonical_json import (
    canonical_json_bytes,
    sha256_json,
    strict_json_loads,
)
from modeling_core.contracts.common import (
    EntityId,
    Hash,
    StrictModel,
    Timestamp,
)
from modeling_core.contracts.versions import VersionSet


class _StrictProbe(StrictModel):
    count: int
    ratio: float


@pytest.mark.parametrize(
    "value",
    [
        "123e4567-e89b-42d3-a456-426614174000",
        "00000000-0000-4000-8000-000000000000",
    ],
)
def test_entity_ids_accept_lowercase_uuid_v4(value: str) -> None:
    assert TypeAdapter(EntityId).validate_python(value, strict=True) == value


@pytest.mark.parametrize(
    "value",
    [
        "123E4567-E89B-42D3-A456-426614174000",
        "123e4567-e89b-12d3-a456-426614174000",
        "not-a-uuid",
    ],
)
def test_entity_ids_reject_noncanonical_values(value: str) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(EntityId).validate_python(value, strict=True)


@pytest.mark.parametrize(
    ("adapter_type", "valid", "invalid"),
    [
        (
            Hash,
            "sha256:" + "a" * 64,
            "sha256:" + "A" * 64,
        ),
        (
            Timestamp,
            "2026-07-23T12:34:56.789Z",
            "2026-07-23T12:34:56Z",
        ),
    ],
)
def test_hash_and_timestamp_formats(
    adapter_type: object, valid: str, invalid: str
) -> None:
    adapter = TypeAdapter(adapter_type)
    assert adapter.validate_python(valid, strict=True) == valid
    with pytest.raises(ValidationError):
        adapter.validate_python(invalid, strict=True)


@pytest.mark.parametrize(
    "value",
    [
        "2026-07-23T12:34:56.789+00:00",
        "2026-07-23T20:34:56.789+08:00",
        datetime(2026, 7, 23, 12, 34, 56, 789000),
    ],
)
def test_timestamps_require_millisecond_z_strings(value: object) -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(Timestamp).validate_python(value, strict=True)


def test_strict_models_forbid_extras_coercion_nonfinite_and_mutation() -> None:
    probe = _StrictProbe(count=1, ratio=1.5)
    with pytest.raises(ValidationError):
        _StrictProbe.model_validate({"count": "1", "ratio": 1.5})
    with pytest.raises(ValidationError):
        _StrictProbe.model_validate({"count": 1, "ratio": nan})
    with pytest.raises(ValidationError):
        _StrictProbe.model_validate({"count": 1, "ratio": inf})
    with pytest.raises(ValidationError):
        _StrictProbe.model_validate({"count": 1, "ratio": 1.5, "extra": True})
    with pytest.raises(ValidationError):
        probe.count = 2


@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b'{"value":NaN}',
        b'{"value":Infinity}',
        b'{"value":"\\ud800"}',
        b"\xff",
    ],
)
def test_strict_json_rejects_ambiguous_or_invalid_input(payload: bytes) -> None:
    with pytest.raises(ValueError):
        strict_json_loads(payload)


def test_fixed_hash_vectors() -> None:
    assert (
        sha256_json([])
        == "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    )
    assert (
        sha256_json({})
        == "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )
    assert canonical_json_bytes({"b": 1.0, "a": -0.0}) == b'{"a":0,"b":1}'
    assert (
        sha256_json({"b": 1.0, "a": -0.0})
        == "sha256:f4c1d8bd90d7ccd720aa5a69a67185fb9caf4f35926a4eacf53a86d0e70bdf88"
    )


def test_canonicalization_is_repeatable_in_a_fresh_process() -> None:
    code = (
        "import json;"
        "from modeling_core.contracts.canonical_json import canonical_json_bytes,sha256_json;"
        "v={'e\\u0301':'e\\u0301','n':-0.0};"
        "print(json.dumps([canonical_json_bytes(v).decode(),sha256_json(v)]))"
    )
    expected = subprocess.check_output(
        [sys.executable, "-c", code], text=True, encoding="utf-8"
    ).strip()
    assert expected == subprocess.check_output(
        [sys.executable, "-c", code], text=True, encoding="utf-8"
    ).strip()
    assert json.loads(expected)[0] == '{"n":0,"é":"é"}'


def test_m1a_version_axes_are_exact() -> None:
    versions = VersionSet.m1a()
    assert versions.model_dump() == {
        "application_release": "0.1.0",
        "mcp_protocol_version": "2025-11-25",
        "tool_contract_version": "modeling-tools/0.1.0",
        "project_format_version": "modeling-project/0.1.0",
        "database_schema_version": 1,
        "capability_api_version": "modeling-capability/0.1.0",
        "error_schema_version": "modeling-error/0.1.0",
        "result_schema_version": "modeling-result/0.1.0",
        "validation_report_schema_version": "modeling-validation-report/0.1.0",
        "canonicalization_version": "canonical-json/0.1.0",
        "root_finding_contract_version": "numerical.root_finding/0.1.0",
        "root_finding_canonical_input_version": (
            "numerical.root_finding.canonical-input/0.1.0"
        ),
        "residual_policy_version": "numerical.root_finding.residual/0.1.0",
    }
