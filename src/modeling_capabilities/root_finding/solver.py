"""Deterministic binary64 bisection Built-in Capability."""

from __future__ import annotations

import math
from typing import Literal, cast

from modeling_capabilities.root_finding.contracts import (
    CANONICAL_INPUT_SCHEMA_VERSION,
    EvaluationBudget,
    EvaluationCancelled,
    EvaluationDeadlineExceeded,
    EvaluationDomainError,
    EvaluationNonFiniteError,
    InputValidationError,
    normalize_root_finding_input,
)
from modeling_capabilities.root_finding.descriptor import (
    build_root_finding_descriptor,
)
from modeling_capabilities.root_finding.expression import (
    ast_from_canonical_json,
)
from modeling_capabilities.root_finding.expression.solver_evaluator import (
    SolverEvaluator,
)
from modeling_core.contracts.capability import (
    CanonicalInputRecord,
    CapabilityDescriptor,
    ExecutionContext,
    ExecutionOutcome,
)
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.tools import (
    CanonicalRootFindingInput,
    FailureResultPayload,
    NumericalFailureData,
    ResultSuccessData,
    SuccessResultPayload,
)


def _check_control(context: ExecutionContext) -> None:
    if context.cancellation.is_cancelled():
        raise EvaluationCancelled("root-finding execution cancelled")
    if context.clock.monotonic() >= context.deadline:
        raise EvaluationDeadlineExceeded(
            "root-finding execution deadline exceeded"
        )


def _success(
    context: ExecutionContext,
    *,
    root: float,
    function_value: float,
    iterations: int,
    evaluations: int,
    termination_reason: Literal[
        "endpoint_root", "residual_tolerance", "interval_tolerance"
    ],
) -> ExecutionOutcome:
    _check_control(context)
    payload = SuccessResultPayload(
        result_schema_version="modeling-result/0.1.0",
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        result_kind="success",
        data=ResultSuccessData(
            root=root,
            function_value=function_value,
            iterations=iterations,
            evaluations=evaluations,
            termination_reason=termination_reason,
        ),
    )
    return ExecutionOutcome.success(payload)


def _failure(
    context: ExecutionContext,
    *,
    failure_code: Literal[
        "no_sign_change",
        "non_convergence",
        "domain_error",
        "non_finite_evaluation",
    ],
    iterations: int,
    evaluations: int,
) -> ExecutionOutcome:
    _check_control(context)
    payload = FailureResultPayload(
        result_schema_version="modeling-result/0.1.0",
        capability_id="numerical.root_finding",
        contract_version="0.1.0",
        result_kind="numerical_failure",
        data=NumericalFailureData(
            failure_code=failure_code,
            iterations=iterations,
            evaluations=evaluations,
        ),
    )
    return ExecutionOutcome.numerical_failure(payload)


def _different_signs(left: float, right: float) -> bool:
    return math.copysign(1.0, left) != math.copysign(1.0, right)


def _midpoint_and_half_width(
    lower: float, upper: float
) -> tuple[float, float]:
    if _different_signs(lower, upper):
        return lower / 2.0 + upper / 2.0, upper / 2.0 - lower / 2.0
    difference = upper - lower
    return lower + difference / 2.0, difference / 2.0


class BisectionRootFindingCapability:
    """Find a bracketed scalar root with deterministic binary64 bisection."""

    def __init__(self) -> None:
        self._descriptor = build_root_finding_descriptor()
        self._evaluator = SolverEvaluator()

    @property
    def descriptor(self) -> CapabilityDescriptor:
        return self._descriptor

    def normalize_and_validate(
        self, raw_payload: JsonObject
    ) -> CanonicalInputRecord:
        return normalize_root_finding_input(raw_payload)

    def execute(
        self,
        canonical_input: CanonicalInputRecord,
        context: ExecutionContext,
    ) -> ExecutionOutcome:
        if (
            canonical_input.canonical_input_schema_version
            != CANONICAL_INPUT_SCHEMA_VERSION
        ):
            raise InputValidationError(
                "/canonical_input_schema_version",
                "capability_payload_violation",
                f"must equal {CANONICAL_INPUT_SCHEMA_VERSION}",
            )
        typed = CanonicalRootFindingInput.model_validate(
            canonical_input.canonical_payload
        )
        ast_document = cast(
            JsonObject, typed.expression_ast.model_dump(mode="json")
        )
        ast = ast_from_canonical_json(ast_document)
        budget = EvaluationBudget(
            deadline=context.deadline,
            clock=context.clock,
            cancellation=context.cancellation,
        )

        lower = typed.lower
        upper = typed.upper
        iterations = 0

        _check_control(context)
        try:
            lower_value = self._evaluator.evaluate(ast, lower, budget)
        except EvaluationDomainError:
            return _failure(
                context,
                failure_code="domain_error",
                iterations=iterations,
                evaluations=budget.evaluations_used,
            )
        except EvaluationNonFiniteError:
            return _failure(
                context,
                failure_code="non_finite_evaluation",
                iterations=iterations,
                evaluations=budget.evaluations_used,
            )
        if abs(lower_value) <= typed.function_tolerance:
            return _success(
                context,
                root=lower,
                function_value=lower_value,
                iterations=iterations,
                evaluations=budget.evaluations_used,
                termination_reason="endpoint_root",
            )

        _check_control(context)
        try:
            upper_value = self._evaluator.evaluate(ast, upper, budget)
        except EvaluationDomainError:
            return _failure(
                context,
                failure_code="domain_error",
                iterations=iterations,
                evaluations=budget.evaluations_used,
            )
        except EvaluationNonFiniteError:
            return _failure(
                context,
                failure_code="non_finite_evaluation",
                iterations=iterations,
                evaluations=budget.evaluations_used,
            )
        if abs(upper_value) <= typed.function_tolerance:
            return _success(
                context,
                root=upper,
                function_value=upper_value,
                iterations=iterations,
                evaluations=budget.evaluations_used,
                termination_reason="endpoint_root",
            )
        if not _different_signs(lower_value, upper_value):
            return _failure(
                context,
                failure_code="no_sign_change",
                iterations=iterations,
                evaluations=budget.evaluations_used,
            )

        for _ in range(typed.max_iterations):
            _check_control(context)
            midpoint, half_width = _midpoint_and_half_width(lower, upper)
            collapsed = midpoint == lower or midpoint == upper

            _check_control(context)
            iterations += 1
            try:
                midpoint_value = self._evaluator.evaluate(
                    ast, midpoint, budget
                )
            except EvaluationDomainError:
                return _failure(
                    context,
                    failure_code="domain_error",
                    iterations=iterations,
                    evaluations=budget.evaluations_used,
                )
            except EvaluationNonFiniteError:
                return _failure(
                    context,
                    failure_code="non_finite_evaluation",
                    iterations=iterations,
                    evaluations=budget.evaluations_used,
                )

            if abs(midpoint_value) <= typed.function_tolerance:
                return _success(
                    context,
                    root=midpoint,
                    function_value=midpoint_value,
                    iterations=iterations,
                    evaluations=budget.evaluations_used,
                    termination_reason="residual_tolerance",
                )

            if _different_signs(lower_value, midpoint_value):
                upper = midpoint
                upper_value = midpoint_value
            else:
                lower = midpoint
                lower_value = midpoint_value

            tolerance = typed.absolute_tolerance + (
                typed.relative_tolerance * abs(midpoint)
            )
            if half_width <= tolerance:
                return _success(
                    context,
                    root=midpoint,
                    function_value=midpoint_value,
                    iterations=iterations,
                    evaluations=budget.evaluations_used,
                    termination_reason="interval_tolerance",
                )
            if collapsed:
                return _failure(
                    context,
                    failure_code="non_convergence",
                    iterations=iterations,
                    evaluations=budget.evaluations_used,
                )

        return _failure(
            context,
            failure_code="non_convergence",
            iterations=iterations,
            evaluations=budget.evaluations_used,
        )


__all__ = ["BisectionRootFindingCapability"]
