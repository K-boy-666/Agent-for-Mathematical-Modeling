"""Built-in independent C1 validators."""

from __future__ import annotations

from typing import Literal

import numpy as np

from modeling_core.contracts.canonical_json import sha256_json
from modeling_core.contracts.capability import (
    CanonicalInputRecord,
    ResultSnapshotView,
    ValidationContext,
    ValidatorDescriptor,
)
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.tools import (
    CoupledHeaveResultData,
    CoupledHeaveSuccessResultPayload,
    CoupledHeaveValidationMetrics,
    CoupledHeaveValidationReportPayload,
)
from modeling_core.contracts.versions import VersionSet

from .descriptor import build_coupled_heave_validator_descriptor
from .validators import (
    ENERGY_CLOSURE_LIMIT,
    REFERENCE_ATOL,
    REFERENCE_RTOL,
    validate_linear,
    validate_power_law,
)


class CoupledHeaveValidator:
    def __init__(
        self,
        mode: Literal["linear", "power_law"],
        versions: VersionSet | None = None,
    ) -> None:
        if mode not in {"linear", "power_law"}:
            raise ValueError("unknown coupled-heave validation mode")
        self._mode = mode
        self._versions = versions or VersionSet.m1a()
        self._descriptor = build_coupled_heave_validator_descriptor(
            self._versions, mode
        )

    @property
    def descriptor(self) -> ValidatorDescriptor:
        return self._descriptor

    def validate(
        self,
        canonical_input: CanonicalInputRecord,
        result_snapshot: ResultSnapshotView,
        policy: JsonObject,
        context: ValidationContext,
    ) -> CoupledHeaveValidationReportPayload:
        if policy:
            raise ValueError("C1 validation policy must be empty")
        payload = CoupledHeaveSuccessResultPayload.model_validate(
            result_snapshot.result_payload
        )
        data = CoupledHeaveResultData.model_validate(payload.data)
        if data.damping_mode != self._mode:
            raise ValueError("validator mode does not match result mode")
        production = {
            name: np.asarray(getattr(data, name), dtype=np.float64)
            for name in ("t", "x_f", "v_f", "x_o", "v_o")
        }
        observed = (validate_linear if self._mode == "linear" else validate_power_law)(
            production, object()
        )
        failed: list[Literal["x_f_tolerance", "x_o_tolerance", "energy_closure"]] = []
        if (
            observed["x_f_rtol"] > REFERENCE_RTOL
            or observed["x_f_atol"] > REFERENCE_ATOL
        ):
            failed.append("x_f_tolerance")
        if (
            observed["x_o_rtol"] > REFERENCE_RTOL
            or observed["x_o_atol"] > REFERENCE_ATOL
        ):
            failed.append("x_o_tolerance")
        if observed["energy_closure"] > ENERGY_CLOSURE_LIMIT:
            failed.append("energy_closure")
        metrics = CoupledHeaveValidationMetrics(**observed, failed_checks=tuple(failed))
        return CoupledHeaveValidationReportPayload(
            report_schema_version=self._versions.validation_report_schema_version,
            validator_id=(
                "dynamics.coupled_heave.linear"
                if self._mode == "linear"
                else "dynamics.coupled_heave.power_law"
            ),
            validator_implementation_id=self._descriptor.implementation_id,
            validator_implementation_version=self._descriptor.implementation_version,
            policy_version="0.1.0",
            policy={},
            policy_hash=sha256_json({}),
            capability_id="dynamics.coupled_heave",
            contract_version="0.1.0",
            canonical_payload_hash=canonical_input.canonical_payload_hash,
            model_snapshot_hash=canonical_input.model_snapshot_hash,
            data_snapshot_set_hash=canonical_input.data_snapshot_set_hash,
            result_hash=result_snapshot.result_hash,
            outcome="PASSED" if not failed else "FAILED",
            metrics=metrics,
        )


__all__ = ["CoupledHeaveValidator"]
