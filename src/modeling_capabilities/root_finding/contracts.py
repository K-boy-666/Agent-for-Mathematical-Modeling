"""Root-finding input normalization and bounded evaluation contracts."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from modeling_capabilities.root_finding.expression.syntax import (
    ExpressionLimitError,
    ExpressionLimits,
    ExpressionSyntaxError,
    ast_to_canonical_json,
    parse_expression,
)
from modeling_core.contracts.canonical_json import sha256_json
from modeling_core.contracts.capability import (
    CancellationSignal,
    CanonicalInputRecord,
)
from modeling_core.contracts.common import JsonObject, JsonValue
from modeling_core.ports.clock import Clock

CANONICAL_INPUT_SCHEMA_VERSION = (
    "numerical.root_finding.canonical-input/0.1.0"
)
MAX_FUNCTION_EVALUATIONS = 20_000
MAX_AST_NODES_PER_EVALUATION = 256


class InputValidationError(ValueError):
    """A strict root-finding payload contract violation."""

    def __init__(self, field_path: str, reason: str) -> None:
        self.field_path = field_path
        self.reason = reason
        super().__init__(f"{field_path}: {reason}")


class EvaluationBudgetExceeded(RuntimeError):
    """A function-evaluation or node-visit safety budget was exhausted."""

    def __init__(self, resource: str, limit: int) -> None:
        self.resource = resource
        self.limit = limit
        super().__init__(f"{resource} limit exceeded: {limit}")


class EvaluationCancelled(RuntimeError):
    """Evaluation stopped because its cancellation signal was set."""


class EvaluationDeadlineExceeded(RuntimeError):
    """Evaluation stopped at its monotonic deadline."""


class EvaluationDomainError(ArithmeticError):
    """A divide, domain, or invalid-power operation is undefined."""


class EvaluationNonFiniteError(ArithmeticError):
    """An overflow or non-finite intermediate made evaluation unusable."""


@dataclass(slots=True)
class EvaluationBudget:
    """Mutable attempt-local counters with immutable authority references."""

    deadline: float
    clock: Clock
    cancellation: CancellationSignal
    max_evaluations: int = MAX_FUNCTION_EVALUATIONS
    _evaluations_used: int = field(default=0, init=False, repr=False)
    _nodes_visited: int = field(default=0, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.deadline, float) or not math.isfinite(
            self.deadline
        ):
            raise ValueError("deadline must be a finite float")
        if (
            isinstance(self.max_evaluations, bool)
            or not isinstance(self.max_evaluations, int)
            or not 1 <= self.max_evaluations <= MAX_FUNCTION_EVALUATIONS
        ):
            raise ValueError(
                "max_evaluations must be an integer from 1 through 20000"
            )

    @property
    def evaluations_used(self) -> int:
        return self._evaluations_used

    def begin_evaluation(self) -> None:
        if self._evaluations_used >= self.max_evaluations:
            raise EvaluationBudgetExceeded(
                "function_evaluations", self.max_evaluations
            )
        self._evaluations_used += 1
        self._nodes_visited = 0

    def check_node(self) -> None:
        if self.cancellation.is_cancelled():
            raise EvaluationCancelled("evaluation cancelled")
        if self.clock.monotonic() >= self.deadline:
            raise EvaluationDeadlineExceeded("evaluation deadline exceeded")
        self._nodes_visited += 1
        if self._nodes_visited > MAX_AST_NODES_PER_EVALUATION:
            raise EvaluationBudgetExceeded(
                "ast_nodes", MAX_AST_NODES_PER_EVALUATION
            )


_RAW_FIELDS = frozenset(
    {
        "expression",
        "lower",
        "upper",
        "absolute_tolerance",
        "relative_tolerance",
        "function_tolerance",
        "max_iterations",
    }
)
_REQUIRED_RAW_FIELDS = frozenset({"expression", "lower", "upper"})
_NUMBER_FIELDS = (
    "lower",
    "upper",
    "absolute_tolerance",
    "relative_tolerance",
    "function_tolerance",
)
_DEFAULTS: dict[str, JsonValue] = {
    "absolute_tolerance": 1e-10,
    "relative_tolerance": 1e-10,
    "function_tolerance": 1e-10,
    "max_iterations": 100,
}


def _validate_raw_shape(raw_payload: JsonObject) -> None:
    if type(raw_payload) is not dict:
        raise InputValidationError("$", "payload must be an object")
    unknown = sorted(set(raw_payload) - _RAW_FIELDS)
    if unknown:
        raise InputValidationError(
            "$", f"unknown field: {', '.join(unknown)}"
        )
    missing = sorted(_REQUIRED_RAW_FIELDS - set(raw_payload))
    if missing:
        raise InputValidationError(
            "$", f"missing required field: {', '.join(missing)}"
        )
    if type(raw_payload["expression"]) is not str:
        raise InputValidationError("expression", "must be a string")
    for field_name in _NUMBER_FIELDS:
        if field_name not in raw_payload:
            continue
        value = raw_payload[field_name]
        if isinstance(value, bool) or type(value) not in {int, float}:
            raise InputValidationError(field_name, "must be a number")
    if "max_iterations" in raw_payload:
        value = raw_payload["max_iterations"]
        if isinstance(value, bool) or type(value) is not int:
            raise InputValidationError(
                "max_iterations", "must be an integer"
            )


def _to_finite_binary64(field_name: str, value: JsonValue) -> float:
    try:
        result = float(value)  # type: ignore[arg-type]
    except (OverflowError, TypeError, ValueError) as error:
        raise InputValidationError(
            field_name, "must be a finite binary64 number"
        ) from error
    if not math.isfinite(result):
        raise InputValidationError(
            field_name, "must be a finite binary64 number"
        )
    return 0.0 if result == 0.0 else result


def _validate_tolerance(field_name: str, value: float) -> None:
    if not 0.0 < value <= 1.0:
        raise InputValidationError(
            field_name, "must be greater than 0 and at most 1"
        )


def normalize_root_finding_input(
    raw_payload: JsonObject,
) -> CanonicalInputRecord:
    """Validate raw input and replace its expression text with canonical AST."""

    _validate_raw_shape(raw_payload)
    materialized: JsonObject = dict(_DEFAULTS)
    materialized.update(raw_payload)

    expression = materialized["expression"]
    assert isinstance(expression, str)
    try:
        expression_ast = parse_expression(expression, ExpressionLimits())
    except ExpressionLimitError:
        raise
    except ExpressionSyntaxError as error:
        raise InputValidationError(
            "expression", f"expression parse error: {error}"
        ) from error

    numbers = {
        field_name: _to_finite_binary64(
            field_name, materialized[field_name]
        )
        for field_name in _NUMBER_FIELDS
    }
    if numbers["upper"] <= numbers["lower"]:
        raise InputValidationError("upper", "must be greater than lower")
    for field_name in (
        "absolute_tolerance",
        "relative_tolerance",
        "function_tolerance",
    ):
        _validate_tolerance(field_name, numbers[field_name])

    max_iterations = materialized["max_iterations"]
    assert isinstance(max_iterations, int) and not isinstance(
        max_iterations, bool
    )
    if not 1 <= max_iterations <= 10_000:
        raise InputValidationError(
            "max_iterations", "must be from 1 through 10000"
        )

    canonical_payload: JsonObject = {
        "canonical_input_schema_version": CANONICAL_INPUT_SCHEMA_VERSION,
        "expression_ast": ast_to_canonical_json(expression_ast),
        "lower": numbers["lower"],
        "upper": numbers["upper"],
        "absolute_tolerance": numbers["absolute_tolerance"],
        "relative_tolerance": numbers["relative_tolerance"],
        "function_tolerance": numbers["function_tolerance"],
        "max_iterations": max_iterations,
    }
    model_snapshot: JsonObject = {
        "language": "math-expr-v1",
        "ast": canonical_payload["expression_ast"],
    }
    return CanonicalInputRecord(
        canonical_input_schema_version=CANONICAL_INPUT_SCHEMA_VERSION,
        canonical_payload=canonical_payload,
        canonical_payload_hash=sha256_json(canonical_payload),
        model_snapshot_hash=sha256_json(model_snapshot),
        data_snapshot_references=(),
        data_snapshot_set_hash=sha256_json([]),
    )


__all__ = [
    "CANONICAL_INPUT_SCHEMA_VERSION",
    "EvaluationBudget",
    "EvaluationBudgetExceeded",
    "EvaluationCancelled",
    "EvaluationDeadlineExceeded",
    "EvaluationDomainError",
    "EvaluationNonFiniteError",
    "InputValidationError",
    "normalize_root_finding_input",
]
