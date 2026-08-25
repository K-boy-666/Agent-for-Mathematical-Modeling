"""Hand-built root-finding validation fixtures that never call the solver."""

from __future__ import annotations

from typing import cast

from modeling_core.contracts.capability import (
    CanonicalInputRecord,
    ResultSnapshotView,
)
from modeling_core.contracts.canonical_json import sha256_json
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.tools import (
    FailureResultPayload,
    NumericalFailureData,
    ResultSuccessData,
    SuccessResultPayload,
)

RESULT_SNAPSHOT_ID = "22222222-2222-4222-8222-222222222222"
EMPTY_DATA_HASH = (
    "sha256:4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945"
)


def expression_ast(expression: str) -> JsonObject:
    """Return a small independently specified canonical AST fixture."""

    fixtures: dict[str, JsonObject] = {
        "x": {"kind": "variable", "name": "x"},
        "x-1": {
            "kind": "binary",
            "op": "subtract",
            "left": {"kind": "variable", "name": "x"},
            "right": {"kind": "number", "value": 1.0},
        },
        "x*x-2": {
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
        "1/x": {
            "kind": "binary",
            "op": "divide",
            "left": {"kind": "number", "value": 1.0},
            "right": {"kind": "variable", "name": "x"},
        },
        "exp(x)": {
            "kind": "call",
            "name": "exp",
            "argument": {"kind": "variable", "name": "x"},
        },
    }
    return cast(JsonObject, fixtures[expression])


def canonical_input(
    expression: str = "x*x-2",
    *,
    lower: float = 0.0,
    upper: float = 2.0,
    function_tolerance: float = 1e-10,
    outer_schema_version: str = ("numerical.root_finding.canonical-input/0.1.0"),
    inner_schema_version: str = ("numerical.root_finding.canonical-input/0.1.0"),
) -> CanonicalInputRecord:
    payload: JsonObject = {
        "canonical_input_schema_version": inner_schema_version,
        "expression_ast": expression_ast(expression),
        "lower": lower,
        "upper": upper,
        "absolute_tolerance": 1e-10,
        "relative_tolerance": 1e-10,
        "function_tolerance": function_tolerance,
        "max_iterations": 100,
    }
    model_snapshot: JsonObject = {
        "language": "math-expr-v1",
        "ast": payload["expression_ast"],
    }
    return CanonicalInputRecord(
        canonical_input_schema_version=outer_schema_version,
        canonical_payload=payload,
        canonical_payload_hash=sha256_json(payload),
        model_snapshot_hash=sha256_json(model_snapshot),
        data_snapshot_references=(),
        data_snapshot_set_hash=EMPTY_DATA_HASH,
    )


def success_snapshot(
    *,
    root: float = 1.4142135623730951,
    function_value: float = 4.440892098500626e-16,
    termination_reason: str = "residual_tolerance",
    outer_capability_id: str = "numerical.root_finding",
    outer_contract_version: str = "0.1.0",
    outer_result_schema_version: str = "modeling-result/0.1.0",
    inner_capability_id: str = "numerical.root_finding",
    inner_contract_version: str = "0.1.0",
    inner_result_schema_version: str = "modeling-result/0.1.0",
    inner_result_kind: str = "success",
) -> ResultSnapshotView:
    data = ResultSuccessData(
        root=root,
        function_value=function_value,
        iterations=38,
        evaluations=40,
        termination_reason=termination_reason,
    )
    payload = SuccessResultPayload.model_construct(
        result_schema_version=inner_result_schema_version,
        capability_id=inner_capability_id,
        contract_version=inner_contract_version,
        result_kind=inner_result_kind,
        data=data,
    )
    payload_json = cast(JsonObject, payload.model_dump(mode="json"))
    snapshot_fields = {
        "result_snapshot_id": RESULT_SNAPSHOT_ID,
        "capability_id": outer_capability_id,
        "contract_version": outer_contract_version,
        "result_schema_version": outer_result_schema_version,
        "result_hash": sha256_json(payload_json),
        "result_payload": payload,
    }
    if inner_result_kind != "success":
        return ResultSnapshotView.model_construct(**snapshot_fields)
    return ResultSnapshotView(**snapshot_fields)


def numerical_failure_snapshot() -> ResultSnapshotView:
    payload = FailureResultPayload(
        result_schema_version="modeling-result/0.1.0",
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        result_kind="numerical_failure",
        data=NumericalFailureData(
            failure_code="no_sign_change",
            iterations=0,
            evaluations=2,
        ),
    )
    return ResultSnapshotView(
        result_snapshot_id=RESULT_SNAPSHOT_ID,
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        result_schema_version="modeling-result/0.1.0",
        result_hash=sha256_json(cast(JsonObject, payload.model_dump(mode="json"))),
        result_payload=payload,
    )


__all__ = [
    "EMPTY_DATA_HASH",
    "canonical_input",
    "expression_ast",
    "numerical_failure_snapshot",
    "success_snapshot",
]
