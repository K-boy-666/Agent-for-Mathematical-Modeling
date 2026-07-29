"""Fixed registration descriptor for the built-in bisection capability."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import cast

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

_VALIDATOR_SUMMARY = (
    "Independently recompute the reported root residual."
)


def _packaged_schema(name: str, schema_version: str) -> SchemaReference:
    asset = files("modeling_capabilities.root_finding").joinpath(
        "schemas", "0.1.0", name
    )
    schema = cast(
        JsonObject, json.loads(asset.read_text(encoding="utf-8"))
    )
    return SchemaReference(
        schema_version=schema_version,
        schema=schema,
        schema_hash=sha256_json(schema),
    )


def build_root_finding_descriptor() -> CapabilityDescriptor:
    """Build the immutable descriptor from the packaged Schema assets."""

    return CapabilityDescriptor(
        kind="built_in",
        capability_api_version="modeling-capability/0.1.0",
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        implementation_id="builtin.numerical.root_finding.bisection",
        implementation_version="0.1.0",
        title="Bisection root finding",
        summary="Find a scalar root in a finite sign-changing bracket.",
        category="numerical",
        tags=("bisection", "deterministic", "root-finding"),
        determinism="deterministic",
        randomness="not_used",
        input_schema=_packaged_schema(
            "input.schema.json",
            "numerical.root_finding.input/0.1.0",
        ),
        canonical_input_schema=_packaged_schema(
            "canonical-input.schema.json",
            "numerical.root_finding.canonical-input/0.1.0",
        ),
        success_schema=_packaged_schema(
            "success-data.schema.json",
            "numerical.root_finding.success-data/0.1.0",
        ),
        failure_schema=_packaged_schema(
            "failure-data.schema.json",
            "numerical.root_finding.failure-data/0.1.0",
        ),
        default_limits=CapabilityLimits(
            timeout_ms=10_000,
            max_iterations=100,
            max_evaluations=20_000,
        ),
        maximum_limits=CapabilityLimits(
            timeout_ms=60_000,
            max_iterations=10_000,
            max_evaluations=20_000,
        ),
        artifact_roles=(),
        validators=cast(
            tuple[bytes, ...],
            (build_residual_validator_summary(),),
        ),
        context_ref="modeling://capabilities/numerical.root_finding/context",
    )


def build_residual_validator_descriptor() -> ValidatorDescriptor:
    """Build the independent residual validator's immutable descriptor."""

    return ValidatorDescriptor(
        kind="built_in",
        validator_id="numerical.root_finding.residual",
        supported_capabilities=(
            SupportedCapabilityRange(
                capability_id="numerical.root_finding",
                minimum_contract_version="0.1.0",
                maximum_contract_version="0.1.0",
            ),
        ),
        implementation_id="builtin.numerical.root_finding.residual",
        implementation_version="0.1.0",
        policy_version="0.1.0",
        policy_schema=_packaged_schema(
            "policy.schema.json",
            "0.1.0",
        ),
        report_schema=_packaged_schema(
            "report.schema.json",
            "modeling-validation-report/0.1.0",
        ),
        summary=_VALIDATOR_SUMMARY,
    )


def build_residual_validator_summary() -> ValidatorSummary:
    """Project the descriptor contract advertised by the capability."""

    descriptor = build_residual_validator_descriptor()
    return ValidatorSummary(
        validator_id=descriptor.validator_id,
        policies=(
            PolicyContract(
                policy_version=descriptor.policy_version,
                policy_schema=descriptor.policy_schema.schema,
                policy_schema_hash=descriptor.policy_schema.schema_hash,
            ),
        ),
        report_schema_version=descriptor.report_schema.schema_version,
        report_schema=descriptor.report_schema.schema,
        report_schema_hash=descriptor.report_schema.schema_hash,
        summary=descriptor.summary,
    )


__all__ = [
    "build_residual_validator_descriptor",
    "build_residual_validator_summary",
    "build_root_finding_descriptor",
]
