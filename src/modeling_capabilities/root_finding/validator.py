"""Independent residual validation for committed root-finding results."""

from __future__ import annotations

import math
from typing import Literal, TypeAlias, cast

from pydantic import ValidationError

from modeling_capabilities.root_finding.contracts import (
    CANONICAL_INPUT_SCHEMA_VERSION,
    EvaluationBudget,
    EvaluationCancelled,
    EvaluationDeadlineExceeded,
    EvaluationDomainError,
    EvaluationNonFiniteError,
)
from modeling_capabilities.root_finding.descriptor import (
    build_residual_validator_descriptor,
)
from modeling_capabilities.root_finding.expression import (
    ast_from_canonical_json,
)
from modeling_capabilities.root_finding.expression.validator_evaluator import (
    ValidatorEvaluator,
)
from modeling_core.contracts.capability import (
    CanonicalInputRecord,
    ResultSnapshotView,
    ValidationContext,
    ValidationReport,
    ValidatorDescriptor,
)
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.tools import (
    CanonicalRootFindingInput,
    SuccessResultPayload,
    ValidationMetrics,
    ValidationReportPayload,
)

EMPTY_POLICY_HASH = (
    "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
)
_CAPABILITY_ID: Literal["numerical.root_finding"] = "numerical.root_finding"
_CONTRACT_VERSION: Literal["0.1.0"] = "0.1.0"
_RESULT_SCHEMA_VERSION = "modeling-result/0.1.0"
_FailedCheck: TypeAlias = Literal[
    "root_out_of_interval",
    "expression_undefined",
    "non_finite_recomputed_value",
    "reported_value_mismatch",
    "residual_exceeds_tolerance",
]


class ValidationInputError(ValueError):
    """A validator precondition or policy contract violation."""

    def __init__(self, field_path: str, reason: str) -> None:
        self.field_path = field_path
        self.reason = reason
        super().__init__(f"{field_path}: {reason}")


def _check_control(context: ValidationContext) -> None:
    if context.cancellation.is_cancelled():
        raise EvaluationCancelled("root-finding validation cancelled")
    if context.clock.monotonic() >= context.deadline:
        raise EvaluationDeadlineExceeded("root-finding validation deadline exceeded")


def _require_identity(actual: object, expected: str, field_path: str) -> None:
    if actual != expected:
        raise ValidationInputError(field_path, "identity mismatch")


def _validated_input(
    canonical_input: CanonicalInputRecord,
) -> CanonicalRootFindingInput:
    _require_identity(
        canonical_input.canonical_input_schema_version,
        CANONICAL_INPUT_SCHEMA_VERSION,
        "canonical_input_schema_version",
    )
    payload = canonical_input.canonical_payload
    _require_identity(
        payload.get("canonical_input_schema_version"),
        CANONICAL_INPUT_SCHEMA_VERSION,
        "canonical_payload.canonical_input_schema_version",
    )
    try:
        return CanonicalRootFindingInput.model_validate(payload)
    except ValidationError as error:
        raise ValidationInputError(
            "canonical_payload", "does not match the canonical input contract"
        ) from error


def _validated_success_result(
    result_snapshot: ResultSnapshotView,
) -> SuccessResultPayload:
    _require_identity(
        result_snapshot.capability_id,
        _CAPABILITY_ID,
        "result_snapshot.capability_id",
    )
    _require_identity(
        result_snapshot.contract_version,
        _CONTRACT_VERSION,
        "result_snapshot.contract_version",
    )
    _require_identity(
        result_snapshot.result_schema_version,
        _RESULT_SCHEMA_VERSION,
        "result_snapshot.result_schema_version",
    )
    payload = result_snapshot.result_payload
    _require_identity(
        payload.result_schema_version,
        _RESULT_SCHEMA_VERSION,
        "result_payload.result_schema_version",
    )
    _require_identity(
        payload.capability_id,
        _CAPABILITY_ID,
        "result_payload.capability_id",
    )
    _require_identity(
        payload.contract_version,
        _CONTRACT_VERSION,
        "result_payload.contract_version",
    )
    _require_identity(
        payload.result_kind,
        "success",
        "result_payload.result_kind",
    )
    if not isinstance(payload, SuccessResultPayload):
        raise ValidationInputError(
            "result_payload.result_kind",
            "validation requires a success result",
        )
    return payload


class ResidualRootFindingValidator:
    """Recompute a root result without solver search or termination code."""

    @property
    def descriptor(self) -> ValidatorDescriptor:
        return build_residual_validator_descriptor()

    def validate(
        self,
        canonical_input: CanonicalInputRecord,
        result_snapshot: ResultSnapshotView,
        policy: JsonObject,
        context: ValidationContext,
    ) -> ValidationReport:
        _check_control(context)
        if type(policy) is not dict or policy:
            raise ValidationInputError("policy", "must be exactly an empty object")
        typed_input = _validated_input(canonical_input)
        result_payload = _validated_success_result(result_snapshot)
        ast = ast_from_canonical_json(
            cast(
                JsonObject,
                typed_input.expression_ast.model_dump(mode="json"),
            )
        )

        root = result_payload.data.root
        reported = result_payload.data.function_value
        tolerance = typed_input.function_tolerance
        root_within_interval = typed_input.lower <= root <= typed_input.upper
        failed_checks: list[_FailedCheck] = []
        if not root_within_interval:
            failed_checks.append("root_out_of_interval")

        recomputed: float | None
        absolute_delta: float | None
        absolute_residual: float | None
        budget = EvaluationBudget(
            deadline=context.deadline,
            clock=context.clock,
            cancellation=context.cancellation,
        )
        try:
            recomputed = ValidatorEvaluator().evaluate(ast, root, budget)
        except EvaluationDomainError:
            recomputed = None
            absolute_delta = None
            absolute_residual = None
            failed_checks.append("expression_undefined")
        except EvaluationNonFiniteError:
            recomputed = None
            absolute_delta = None
            absolute_residual = None
            failed_checks.append("non_finite_recomputed_value")
        else:
            raw_delta = abs(recomputed - reported)
            if math.isfinite(raw_delta):
                absolute_delta = raw_delta
                if absolute_delta > tolerance:
                    failed_checks.append("reported_value_mismatch")
            else:
                absolute_delta = None
                failed_checks.append("reported_value_mismatch")
            absolute_residual = abs(recomputed)
            if absolute_residual > tolerance:
                failed_checks.append("residual_exceeds_tolerance")

        _check_control(context)
        metrics = ValidationMetrics(
            root_within_interval=root_within_interval,
            reported_function_value=reported,
            recomputed_function_value=recomputed,
            absolute_reported_delta=absolute_delta,
            absolute_residual=absolute_residual,
            function_tolerance=tolerance,
            failed_checks=tuple(failed_checks),
        )
        return ValidationReportPayload(
            report_schema_version="modeling-validation-report/0.1.0",
            validator_id="numerical.root_finding.residual",
            validator_implementation_id=("builtin.numerical.root_finding.residual"),
            validator_implementation_version="0.1.0",
            policy_version="0.1.0",
            policy={},
            policy_hash=EMPTY_POLICY_HASH,
            capability_id=_CAPABILITY_ID,
            contract_version=_CONTRACT_VERSION,
            canonical_payload_hash=canonical_input.canonical_payload_hash,
            model_snapshot_hash=canonical_input.model_snapshot_hash,
            data_snapshot_set_hash=canonical_input.data_snapshot_set_hash,
            result_hash=result_snapshot.result_hash,
            outcome="PASSED" if not failed_checks else "FAILED",
            metrics=metrics,
        )


__all__ = [
    "EMPTY_POLICY_HASH",
    "ResidualRootFindingValidator",
    "ValidationInputError",
]
