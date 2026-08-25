"""Descriptors and strict in-memory schemas for the C1 capability."""

from __future__ import annotations

from typing import Literal, cast

from modeling_core.contracts.canonical_json import sha256_json
from modeling_core.contracts.capability import (
    CapabilityDescriptor,
    SchemaReference,
    SupportedCapabilityRange,
    ValidatorDescriptor,
)
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.tools import (
    CapabilityLimits,
    PolicyContract,
    ValidatorSummary,
)
from modeling_core.contracts.versions import VersionSet

_DRAFT = "https://json-schema.org/draft/2020-12/schema"
_HASH = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
_ASSET = {
    "type": "object",
    "additionalProperties": False,
    "required": ["snapshot_id", "label", "sha256", "official_match"],
    "properties": {
        "snapshot_id": {"type": "string"},
        "label": {"type": "string", "minLength": 1},
        "sha256": _HASH,
        "official_match": {"type": "boolean"},
    },
}


def _schema(version: str, properties: JsonObject, required: list[str]) -> JsonObject:
    return {
        "$schema": _DRAFT,
        "$id": f"https://schemas.math-modeling-mcp.local/capabilities/dynamics/{version}",
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


def _reference(version: str, schema: JsonObject) -> SchemaReference:
    return SchemaReference(
        schema_version=version,
        schema=schema,
        schema_hash=sha256_json(schema),
    )


def _input_schema() -> JsonObject:
    return _schema(
        "input/0.1.0",
        {
            "subproblem_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "mmir_revision": _HASH,
            "damping_mode": {"enum": ["linear", "power_law"]},
            "asset_snapshots": {
                "type": "array",
                "minItems": 1,
                "maxItems": 20,
                "items": _ASSET,
            },
        },
        ["subproblem_id", "mmir_revision", "damping_mode", "asset_snapshots"],
    )


def _canonical_schema() -> JsonObject:
    properties = cast(JsonObject, _input_schema()["properties"]).copy()
    properties["canonical_input_schema_version"] = {
        "const": "dynamics.coupled_heave.canonical-input/0.1.0"
    }
    properties["model"] = {"type": "object"}
    return _schema(
        "canonical-input/0.1.0",
        properties,
        [
            "canonical_input_schema_version",
            "subproblem_id",
            "mmir_revision",
            "damping_mode",
            "asset_snapshots",
            "model",
        ],
    )


def _success_schema() -> JsonObject:
    series = {
        "type": "array",
        "minItems": 898,
        "maxItems": 898,
        "items": {"type": "number"},
    }
    return _schema(
        "success-data/0.1.0",
        {
            "damping_mode": {"enum": ["linear", "power_law"]},
            "t": series,
            "x_f": series,
            "v_f": series,
            "x_o": series,
            "v_o": series,
        },
        ["damping_mode", "t", "x_f", "v_f", "x_o", "v_o"],
    )


def _empty_schema(version: str) -> JsonObject:
    return _schema(version, {}, [])


def _metrics_schema() -> JsonObject:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "x_f_rtol",
            "x_f_atol",
            "x_o_rtol",
            "x_o_atol",
            "energy_closure",
            "failed_checks",
        ],
        "properties": {
            **{
                name: {"type": "number", "minimum": 0}
                for name in (
                    "x_f_rtol",
                    "x_f_atol",
                    "x_o_rtol",
                    "x_o_atol",
                    "energy_closure",
                )
            },
            "failed_checks": {
                "type": "array",
                "uniqueItems": True,
                "items": {"enum": ["x_f_tolerance", "x_o_tolerance", "energy_closure"]},
            },
        },
    }


def _report_schema(validator_id: str) -> JsonObject:
    properties: JsonObject = {
        "report_schema_version": {
            "enum": [
                "modeling-validation-report/0.1.0",
                "modeling-validation-report/1.0.0",
            ]
        },
        "validator_id": {"const": validator_id},
        "validator_implementation_id": {"type": "string", "minLength": 1},
        "validator_implementation_version": {"type": "string", "minLength": 1},
        "policy_version": {"const": "0.1.0"},
        "policy": {"type": "object", "additionalProperties": False},
        "policy_hash": _HASH,
        "capability_id": {"const": "dynamics.coupled_heave"},
        "contract_version": {"const": "0.1.0"},
        "canonical_payload_hash": _HASH,
        "model_snapshot_hash": _HASH,
        "data_snapshot_set_hash": _HASH,
        "result_hash": _HASH,
        "outcome": {"enum": ["PASSED", "FAILED", "INCONCLUSIVE"]},
        "metrics": _metrics_schema(),
    }
    return _schema("report/0.1.0", properties, list(properties))


def _validator_descriptor(
    versions: VersionSet, mode: Literal["linear", "power_law"]
) -> ValidatorDescriptor:
    validator_id = f"dynamics.coupled_heave.{mode}"
    return ValidatorDescriptor(
        kind="built_in",
        validator_id=validator_id,
        supported_capabilities=(
            SupportedCapabilityRange(
                capability_id="dynamics.coupled_heave",
                minimum_contract_version="0.1.0",
                maximum_contract_version="0.1.0",
            ),
        ),
        implementation_id=f"builtin.{validator_id}",
        implementation_version="0.1.0",
        policy_version="0.1.0",
        policy_schema=_reference("0.1.0", _empty_schema(f"{mode}-policy/0.1.0")),
        report_schema=_reference(
            versions.validation_report_schema_version, _report_schema(validator_id)
        ),
        summary=f"Independent {mode} coupled-heave validation.",
    )


def _validator_summary(
    versions: VersionSet, mode: Literal["linear", "power_law"]
) -> ValidatorSummary:
    descriptor = _validator_descriptor(versions, mode)
    return ValidatorSummary(
        validator_id=descriptor.validator_id,
        policies=(
            PolicyContract(
                policy_version="0.1.0",
                policy_schema=descriptor.policy_schema.schema,
                policy_schema_hash=descriptor.policy_schema.schema_hash,
            ),
        ),
        report_schema_version=descriptor.report_schema.schema_version,
        report_schema=descriptor.report_schema.schema,
        report_schema_hash=descriptor.report_schema.schema_hash,
        summary=descriptor.summary,
    )


def build_coupled_heave_descriptor(versions: VersionSet) -> CapabilityDescriptor:
    return CapabilityDescriptor(
        kind="built_in",
        capability_api_version=versions.capability_api_version,
        capability_id="dynamics.coupled_heave",
        contract_version="0.1.0",
        implementation_id="builtin.dynamics.coupled_heave.dop853",
        implementation_version="0.1.0",
        title="CUMCM coupled heave",
        summary="Solve the two approved CUMCM 2022 A Q1 damping cases.",
        category="dynamics",
        tags=("coupled-heave", "deterministic", "dynamics"),
        determinism="deterministic",
        randomness="not_used",
        input_schema=_reference("dynamics.coupled_heave.input/0.1.0", _input_schema()),
        canonical_input_schema=_reference(
            "dynamics.coupled_heave.canonical-input/0.1.0", _canonical_schema()
        ),
        success_schema=_reference(
            "dynamics.coupled_heave.success-data/0.1.0", _success_schema()
        ),
        failure_schema=_reference(
            "dynamics.coupled_heave.failure-data/0.1.0",
            _empty_schema("failure-data/0.1.0"),
        ),
        default_limits=CapabilityLimits(
            timeout_ms=60_000, max_iterations=0, max_evaluations=0
        ),
        maximum_limits=CapabilityLimits(
            timeout_ms=60_000, max_iterations=0, max_evaluations=0
        ),
        artifact_roles=(),
        validators=cast(
            tuple[bytes, ...],
            (
                _validator_summary(versions, "linear"),
                _validator_summary(versions, "power_law"),
            ),
        ),
        context_ref="modeling://capabilities/dynamics.coupled_heave/context",
    )


def build_coupled_heave_validator_descriptor(
    versions: VersionSet, mode: Literal["linear", "power_law"]
) -> ValidatorDescriptor:
    return _validator_descriptor(versions, mode)


__all__ = ["build_coupled_heave_descriptor", "build_coupled_heave_validator_descriptor"]
