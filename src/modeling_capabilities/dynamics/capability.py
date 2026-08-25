"""Built-in C1 coupled-heave capability."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal, cast

from pydantic import ValidationError

from modeling_core.contracts.canonical_json import canonical_json_bytes, sha256_json
from modeling_core.contracts.capability import (
    CanonicalInputRecord,
    CapabilityDescriptor,
    CapabilityInputRejected,
    ExecutionCancelled,
    ExecutionContext,
    ExecutionOutcome,
)
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.tools import (
    CanonicalCoupledHeaveInput,
    CoupledHeaveInput,
    CoupledHeaveResultData,
    CoupledHeaveSuccessResultPayload,
)
from modeling_core.contracts.versions import VersionSet

from .descriptor import build_coupled_heave_descriptor
from .solver import CoupledHeaveParams, DampingMode, solve_coupled_heave

_CANONICAL_INPUT_VERSION: Literal["dynamics.coupled_heave.canonical-input/0.1.0"] = (
    "dynamics.coupled_heave.canonical-input/0.1.0"
)


def _model_document() -> JsonObject:
    return {
        "assumption": "coordinates are deviations from static equilibrium",
        "equations": [
            "(m_f+m_a)x_f''+Bx_f'+K_hx_f+k(x_f-x_o)+D(x_f'-x_o')=Fcos(omega*t)",
            "m_ox_o''+k(x_o-x_f)+D(x_o'-x_f')=0",
        ],
        "parameters": cast(JsonObject, asdict(CoupledHeaveParams())),
    }


class CoupledHeaveCapability:
    def __init__(self, versions: VersionSet | None = None) -> None:
        self._versions = versions or VersionSet.m1a()
        self._descriptor = build_coupled_heave_descriptor(self._versions)

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return self._descriptor

    def normalize_and_validate(self, raw_payload: JsonObject) -> CanonicalInputRecord:
        try:
            request = CoupledHeaveInput.model_validate_json(
                canonical_json_bytes(raw_payload)
            )
        except ValidationError as error:
            raise CapabilityInputRejected(
                "",
                "capability_payload_violation",
                "invalid coupled-heave payload",
            ) from error
        assets = tuple(sorted(request.asset_snapshots, key=lambda item: item.label))
        model = _model_document()
        canonical = CanonicalCoupledHeaveInput(
            canonical_input_schema_version=_CANONICAL_INPUT_VERSION,
            subproblem_id=request.subproblem_id,
            mmir_revision=request.mmir_revision,
            damping_mode=request.damping_mode,
            asset_snapshots=assets,
            model=model,
        )
        payload = cast(JsonObject, canonical.model_dump(mode="json"))
        references: tuple[JsonObject, ...] = tuple(
            cast(JsonObject, {"snapshot_id": item.snapshot_id, "sha256": item.sha256})
            for item in assets
        )
        return CanonicalInputRecord(
            canonical_input_schema_version=_CANONICAL_INPUT_VERSION,
            canonical_payload=payload,
            canonical_payload_hash=sha256_json(payload),
            model_snapshot_hash=sha256_json(model),
            data_snapshot_references=references,
            data_snapshot_set_hash=sha256_json(list(references)),
        )

    def execute(
        self,
        canonical_input: CanonicalInputRecord,
        context: ExecutionContext,
    ) -> ExecutionOutcome:
        if context.cancellation.is_cancelled():
            raise ExecutionCancelled()
        typed = CanonicalCoupledHeaveInput.model_validate_json(
            canonical_json_bytes(canonical_input.canonical_payload)
        )
        mode = (
            DampingMode.LINEAR
            if typed.damping_mode == "linear"
            else DampingMode.POWER_LAW
        )
        result = solve_coupled_heave(CoupledHeaveParams(), mode)
        if context.cancellation.is_cancelled():
            raise ExecutionCancelled()
        data = CoupledHeaveResultData(
            damping_mode=typed.damping_mode,
            **{
                name: tuple(float(value) for value in result[name])
                for name in ("t", "x_f", "v_f", "x_o", "v_o")
            },
        )
        return ExecutionOutcome.success(
            CoupledHeaveSuccessResultPayload(
                result_schema_version=self._versions.result_schema_version,
                capability_id="dynamics.coupled_heave",
                contract_version="0.1.0",
                result_kind="success",
                data=data,
            )
        )


__all__ = ["CoupledHeaveCapability"]
