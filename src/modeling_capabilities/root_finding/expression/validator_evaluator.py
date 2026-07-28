"""Validator-owned numerical traversal for immutable math-expr-v1 AST."""

from __future__ import annotations

import math

from modeling_capabilities.root_finding.contracts import (
    EvaluationBudget,
    EvaluationDomainError,
    EvaluationNonFiniteError,
)
from modeling_capabilities.root_finding.expression.syntax import (
    BinaryNode,
    CallNode,
    ConstantNode,
    ExpressionAst,
    NumberNode,
    UnaryNode,
    VariableNode,
)

_PI = float.fromhex("0x1.921fb54442d18p+1")
_E = float.fromhex("0x1.5bf0a8b145769p+1")


def _validator_finite(value: float) -> float:
    if not math.isfinite(value):
        raise EvaluationNonFiniteError(
            "validator evaluator produced a non-finite value"
        )
    return 0.0 if value == 0.0 else value


def _validator_unary(op: str, operand: float) -> float:
    if op == "positive":
        return _validator_finite(+operand)
    if op == "negative":
        return _validator_finite(-operand)
    raise EvaluationDomainError(
        "validator evaluator received an unknown unary operator"
    )


def _validator_binary(op: str, left: float, right: float) -> float:
    try:
        if op == "add":
            result = left + right
        elif op == "subtract":
            result = left - right
        elif op == "multiply":
            result = left * right
        elif op == "divide":
            result = left / right
        elif op == "power":
            result = math.pow(left, right)
        else:
            raise EvaluationDomainError(
                "validator evaluator received an unknown binary operator"
            )
    except (ValueError, ZeroDivisionError) as error:
        raise EvaluationDomainError(
            "validator evaluator encountered an undefined arithmetic operation"
        ) from error
    except OverflowError as error:
        raise EvaluationNonFiniteError(
            "validator evaluator overflowed"
        ) from error
    return _validator_finite(result)


def _validator_call(name: str, argument: float) -> float:
    try:
        if name == "abs":
            result = math.fabs(argument)
        elif name == "sqrt":
            result = math.sqrt(argument)
        elif name == "exp":
            result = math.exp(argument)
        elif name == "log":
            result = math.log(argument)
        elif name == "sin":
            result = math.sin(argument)
        elif name == "cos":
            result = math.cos(argument)
        elif name == "tan":
            result = math.tan(argument)
        else:
            raise EvaluationDomainError(
                "validator evaluator received an unknown function"
            )
    except ValueError as error:
        raise EvaluationDomainError(
            "validator evaluator function domain error"
        ) from error
    except OverflowError as error:
        raise EvaluationNonFiniteError(
            "validator evaluator function overflow"
        ) from error
    return _validator_finite(result)


def _validator_node(
    ast: ExpressionAst, x: float, budget: EvaluationBudget
) -> float:
    budget.check_node()
    if isinstance(ast, NumberNode):
        return ast.value
    if isinstance(ast, VariableNode):
        return x
    if isinstance(ast, ConstantNode):
        return _PI if ast.name == "pi" else _E
    if isinstance(ast, UnaryNode):
        return _validator_unary(
            ast.op, _validator_node(ast.operand, x, budget)
        )
    if isinstance(ast, BinaryNode):
        if ast.op == "power" and (
            not isinstance(ast.right, NumberNode)
            or not -1024.0 <= ast.right.value <= 1024.0
        ):
            raise EvaluationDomainError(
                "validator evaluator rejected an unsafe exponent"
            )
        left = _validator_node(ast.left, x, budget)
        right = _validator_node(ast.right, x, budget)
        return _validator_binary(ast.op, left, right)
    if isinstance(ast, CallNode):
        return _validator_call(
            ast.name, _validator_node(ast.argument, x, budget)
        )
    raise EvaluationDomainError(
        "validator evaluator received an unknown AST node"
    )


class ValidatorEvaluator:
    """Evaluate one AST independently for residual validation."""

    def evaluate(
        self, ast: ExpressionAst, x: float, budget: EvaluationBudget
    ) -> float:
        budget.begin_evaluation()
        if (
            isinstance(x, bool)
            or not isinstance(x, (int, float))
            or not math.isfinite(float(x))
        ):
            raise EvaluationNonFiniteError(
                "validator x must be finite binary64"
            )
        return _validator_node(ast, float(x), budget)


__all__ = ["ValidatorEvaluator"]
