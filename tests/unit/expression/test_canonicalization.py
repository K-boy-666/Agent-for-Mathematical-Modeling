from __future__ import annotations

import json
import math
from importlib.resources import files
from typing import cast

import pytest
from jsonschema import Draft202012Validator  # type: ignore[import-untyped]
from pydantic import ValidationError

from modeling_capabilities.root_finding.contracts import (
    InputValidationError,
    normalize_root_finding_input,
)
from modeling_core.contracts.canonical_json import canonical_json_bytes, sha256_json
from modeling_core.contracts.common import JsonObject


_CANONICAL_FIELDS = {
    "canonical_input_schema_version",
    "expression_ast",
    "lower",
    "upper",
    "absolute_tolerance",
    "relative_tolerance",
    "function_tolerance",
    "max_iterations",
}


def _raw_payload(expression: str = "x*x-2") -> JsonObject:
    return {
        "expression": expression,
        "lower": 0,
        "upper": 2,
    }


def _load_schema(name: str) -> JsonObject:
    asset = files("modeling_capabilities.root_finding").joinpath(
        "schemas", "0.1.0", name
    )
    return cast(JsonObject, json.loads(asset.read_text(encoding="utf-8")))


def test_expression_whitespace_produces_identical_ast_bytes_and_hashes() -> None:
    spaced = normalize_root_finding_input(_raw_payload(" x * x - 2 "))
    compact = normalize_root_finding_input(_raw_payload("x*x-2"))

    assert canonical_json_bytes(
        spaced.canonical_payload["expression_ast"]
    ) == canonical_json_bytes(compact.canonical_payload["expression_ast"])
    assert spaced.canonical_payload_hash == compact.canonical_payload_hash
    assert spaced.model_snapshot_hash == compact.model_snapshot_hash


def test_omitted_defaults_equal_the_fully_explicit_input() -> None:
    omitted = normalize_root_finding_input(_raw_payload())
    explicit_payload = _raw_payload()
    explicit_payload.update(
        {
            "absolute_tolerance": 1e-10,
            "relative_tolerance": 1e-10,
            "function_tolerance": 1e-10,
            "max_iterations": 100,
        }
    )
    explicit = normalize_root_finding_input(explicit_payload)

    assert omitted == explicit
    assert omitted.canonical_payload == {
        "canonical_input_schema_version": (
            "numerical.root_finding.canonical-input/0.1.0"
        ),
        "expression_ast": {
            "kind": "binary",
            "op": "subtract",
            "left": {
                "kind": "binary",
                "op": "multiply",
                "left": {"kind": "variable", "name": "x"},
                "right": {"kind": "variable", "name": "x"},
            },
            "right": {"kind": "number", "value": 2.0},
        },
        "lower": 0.0,
        "upper": 2.0,
        "absolute_tolerance": 1e-10,
        "relative_tolerance": 1e-10,
        "function_tolerance": 1e-10,
        "max_iterations": 100,
    }


def test_canonical_root_has_exactly_eight_fields_and_no_raw_expression() -> None:
    raw = _raw_payload(" x ")
    record = normalize_root_finding_input(raw)

    assert set(record.canonical_payload) == _CANONICAL_FIELDS
    assert "expression" not in record.canonical_payload
    assert b'" x "' not in canonical_json_bytes(record.model_dump(mode="json"))


def test_negative_zero_is_numeric_zero_everywhere() -> None:
    record = normalize_root_finding_input(
        {
            "expression": "-0.0 + x",
            "lower": -0.0,
            "upper": 2.0,
        }
    )
    expression_ast = cast(JsonObject, record.canonical_payload["expression_ast"])
    left = cast(JsonObject, expression_ast["left"])

    assert left == {"kind": "number", "value": 0.0}
    assert record.canonical_payload["lower"] == 0.0
    assert math.copysign(1.0, cast(float, left["value"])) == 1.0
    assert math.copysign(
        1.0, cast(float, record.canonical_payload["lower"])
    ) == 1.0


def test_nfc_equivalent_strings_hash_identically() -> None:
    assert sha256_json({"label": "\u00e9"}) == sha256_json(
        {"label": "e\u0301"}
    )


def test_schema_integer_stays_integer_and_schema_numbers_become_binary64() -> None:
    record = normalize_root_finding_input(
        {
            "expression": "1 + x",
            "lower": -1,
            "upper": 2,
            "max_iterations": 7,
        }
    )
    payload = record.canonical_payload
    expression_ast = cast(JsonObject, payload["expression_ast"])
    left = cast(JsonObject, expression_ast["left"])

    assert type(payload["max_iterations"]) is int
    assert type(payload["lower"]) is float
    assert type(payload["upper"]) is float
    assert type(left["value"]) is float
    assert all(
        math.isfinite(cast(float, payload[name]))
        for name in (
            "lower",
            "upper",
            "absolute_tolerance",
            "relative_tolerance",
            "function_tolerance",
        )
    )


def test_normalization_computes_the_three_fixed_snapshot_hashes() -> None:
    record = normalize_root_finding_input(_raw_payload("x"))

    assert record.canonical_payload_hash == sha256_json(record.canonical_payload)
    assert record.model_snapshot_hash == sha256_json(
        {
            "language": "math-expr-v1",
            "ast": record.canonical_payload["expression_ast"],
        }
    )
    assert record.data_snapshot_references == ()
    assert (
        record.data_snapshot_set_hash
        == "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
    )


def test_normalization_returns_a_frozen_canonical_input_record() -> None:
    record = normalize_root_finding_input(_raw_payload())

    with pytest.raises(ValidationError):
        record.canonical_payload_hash = "sha256:" + "0" * 64


@pytest.mark.parametrize(
    "raw_payload",
    [
        {"expression": "x", "lower": 0},
        {"expression": "x", "upper": 1},
        {"lower": 0, "upper": 1},
        {"expression": "x", "lower": 0, "upper": 1, "unexpected": True},
        {"expression": 1, "lower": 0, "upper": 1},
        {"expression": "x", "lower": False, "upper": 1},
        {"expression": "x", "lower": 0, "upper": "1"},
    ],
)
def test_raw_shape_is_strictly_validated(raw_payload: JsonObject) -> None:
    with pytest.raises(InputValidationError):
        normalize_root_finding_input(raw_payload)


def test_raw_shape_validation_precedes_expression_parsing() -> None:
    with pytest.raises(InputValidationError, match="unknown field"):
        normalize_root_finding_input(
            {
                "expression": "this is not an expression",
                "lower": 0,
                "upper": 1,
                "unexpected": True,
            }
        )


@pytest.mark.parametrize(
    "raw_payload",
    [
        {"expression": "x", "lower": 1, "upper": 1},
        {"expression": "x", "lower": 2, "upper": 1},
        {"expression": "x", "lower": float("nan"), "upper": 1},
        {"expression": "x", "lower": 0, "upper": float("inf")},
        {"expression": "x", "lower": 10**400, "upper": 10**401},
        {
            "expression": "x",
            "lower": 0,
            "upper": 1,
            "absolute_tolerance": 0,
        },
        {
            "expression": "x",
            "lower": 0,
            "upper": 1,
            "relative_tolerance": -1e-10,
        },
        {
            "expression": "x",
            "lower": 0,
            "upper": 1,
            "function_tolerance": 1.0000001,
        },
        {
            "expression": "x",
            "lower": 0,
            "upper": 1,
            "max_iterations": 0,
        },
        {
            "expression": "x",
            "lower": 0,
            "upper": 1,
            "max_iterations": 10_001,
        },
        {
            "expression": "x",
            "lower": 0,
            "upper": 1,
            "max_iterations": 1.0,
        },
    ],
)
def test_normalization_rejects_invalid_ranges_and_non_binary64_values(
    raw_payload: JsonObject,
) -> None:
    with pytest.raises(InputValidationError):
        normalize_root_finding_input(raw_payload)


def test_expression_failures_are_reported_as_input_validation_errors() -> None:
    with pytest.raises(InputValidationError, match="expression"):
        normalize_root_finding_input(_raw_payload("x.__class__"))


def test_input_and_canonical_schemas_are_strict_draft_2020_12_contracts() -> None:
    input_schema = _load_schema("input.schema.json")
    canonical_schema = _load_schema("canonical-input.schema.json")
    Draft202012Validator.check_schema(input_schema)
    Draft202012Validator.check_schema(canonical_schema)

    assert input_schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert input_schema["type"] == "object"
    assert input_schema["additionalProperties"] is False
    assert canonical_schema["$schema"] == (
        "https://json-schema.org/draft/2020-12/schema"
    )
    assert canonical_schema["type"] == "object"
    assert canonical_schema["additionalProperties"] is False
    assert set(cast(list[str], canonical_schema["required"])) == _CANONICAL_FIELDS

    raw = _raw_payload()
    canonical = normalize_root_finding_input(raw).canonical_payload
    Draft202012Validator(input_schema).validate(raw)
    Draft202012Validator(canonical_schema).validate(canonical)

    invalid_canonical = dict(canonical)
    invalid_canonical["expression"] = "x*x-2"
    assert list(
        Draft202012Validator(canonical_schema).iter_errors(invalid_canonical)
    )
