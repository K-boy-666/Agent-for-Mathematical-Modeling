from __future__ import annotations

import ast as python_ast
import importlib
import math
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import ModuleType

import pytest

from modeling_capabilities.root_finding.contracts import (
    EvaluationBudget,
    EvaluationBudgetExceeded,
    EvaluationCancelled,
    EvaluationDeadlineExceeded,
    EvaluationDomainError,
    EvaluationNonFiniteError,
)
from modeling_capabilities.root_finding.expression.solver_evaluator import (
    SolverEvaluator,
)
from modeling_capabilities.root_finding.expression.syntax import (
    BinaryNode,
    CallNode,
    ExpressionAst,
    ExpressionForbiddenSyntaxError,
    ExpressionLimitError,
    ExpressionLimits,
    ExpressionSyntaxError,
    NumberNode,
    UnaryNode,
    VariableNode,
    ast_from_canonical_json,
    ast_to_canonical_json,
    parse_expression,
)
from modeling_capabilities.root_finding.expression.validator_evaluator import (
    ValidatorEvaluator,
)


class _Clock:
    def __init__(self, now: float = 0.0) -> None:
        self.now = now

    def monotonic(self) -> float:
        return self.now


class _Cancellation:
    def __init__(self, cancel_on_check: int | None = None) -> None:
        self.cancel_on_check = cancel_on_check
        self.checks = 0

    def is_cancelled(self) -> bool:
        self.checks += 1
        return (
            self.cancel_on_check is not None
            and self.checks >= self.cancel_on_check
        )


def _budget(
    *,
    deadline: float = 10.0,
    clock: _Clock | None = None,
    cancellation: _Cancellation | None = None,
    max_evaluations: int = 20_000,
) -> EvaluationBudget:
    return EvaluationBudget(
        deadline=deadline,
        clock=clock or _Clock(),
        cancellation=cancellation or _Cancellation(),
        max_evaluations=max_evaluations,
    )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("x", {"kind": "variable", "name": "x"}),
        ("0", {"kind": "number", "value": 0.0}),
        (".5", {"kind": "number", "value": 0.5}),
        ("5.", {"kind": "number", "value": 5.0}),
        ("1.25e+2", {"kind": "number", "value": 125.0}),
        ("pi", {"kind": "constant", "name": "pi"}),
        ("e", {"kind": "constant", "name": "e"}),
        (
            "-x",
            {
                "kind": "unary",
                "op": "negative",
                "operand": {"kind": "variable", "name": "x"},
            },
        ),
        (
            "+x",
            {
                "kind": "unary",
                "op": "positive",
                "operand": {"kind": "variable", "name": "x"},
            },
        ),
        ("-2.5", {"kind": "number", "value": -2.5}),
        ("+2.5", {"kind": "number", "value": 2.5}),
        ("-0.0", {"kind": "number", "value": 0.0}),
    ],
)
def test_parser_emits_the_fixed_canonical_leaf_and_unary_shapes(
    source: str, expected: dict[str, object]
) -> None:
    ast = parse_expression(source, ExpressionLimits())

    assert ast_to_canonical_json(ast) == expected


def test_parser_applies_fixed_precedence_and_right_associative_power() -> None:
    ast = parse_expression("1 + 2 * x ** 3 - 4 / x", ExpressionLimits())

    assert ast_to_canonical_json(ast) == {
        "kind": "binary",
        "op": "subtract",
        "left": {
            "kind": "binary",
            "op": "add",
            "left": {"kind": "number", "value": 1.0},
            "right": {
                "kind": "binary",
                "op": "multiply",
                "left": {"kind": "number", "value": 2.0},
                "right": {
                    "kind": "binary",
                    "op": "power",
                    "left": {"kind": "variable", "name": "x"},
                    "right": {"kind": "number", "value": 3.0},
                },
            },
        },
        "right": {
            "kind": "binary",
            "op": "divide",
            "left": {"kind": "number", "value": 4.0},
            "right": {"kind": "variable", "name": "x"},
        },
    }


def test_power_is_right_associative_and_tighter_than_a_leading_unary_sign() -> None:
    with pytest.raises(ExpressionSyntaxError):
        parse_expression("2 ** 3 ** 2", ExpressionLimits())

    ast = parse_expression("-2**2", ExpressionLimits())
    assert ast_to_canonical_json(ast) == {
        "kind": "unary",
        "op": "negative",
        "operand": {
            "kind": "binary",
            "op": "power",
            "left": {"kind": "number", "value": 2.0},
            "right": {"kind": "number", "value": 2.0},
        },
    }


def test_only_a_sign_directly_targeting_a_literal_is_folded() -> None:
    parenthesized = parse_expression("-(2)", ExpressionLimits())
    sign_chain = parse_expression("--2", ExpressionLimits())

    assert ast_to_canonical_json(parenthesized) == {
        "kind": "unary",
        "op": "negative",
        "operand": {"kind": "number", "value": 2.0},
    }
    assert ast_to_canonical_json(sign_chain) == {
        "kind": "unary",
        "op": "negative",
        "operand": {"kind": "number", "value": -2.0},
    }


@pytest.mark.parametrize("name", ["abs", "sqrt", "exp", "log", "sin", "cos", "tan"])
def test_parser_accepts_exactly_the_allowed_one_argument_functions(name: str) -> None:
    ast = parse_expression(f"{name}(x)", ExpressionLimits())

    assert ast_to_canonical_json(ast) == {
        "kind": "call",
        "name": name,
        "argument": {"kind": "variable", "name": "x"},
    }


@pytest.mark.parametrize(
    "source",
    [
        "2x",
        "2(x)",
        "(x)(x)",
        "x sin(x)",
    ],
)
def test_parser_rejects_implicit_multiplication(source: str) -> None:
    with pytest.raises(ExpressionSyntaxError):
        parse_expression(source, ExpressionLimits())


@pytest.mark.parametrize(
    "source",
    [
        "x.real",
        "x[0]",
        "import os",
        "__import__('os')",
        "lambda x: x",
        "[x for x in x]",
        "x = 1",
        "x, x",
        "sin(x, x)",
        "'x'",
        '"x"',
        "y",
        "asin(x)",
        "x % 2",
        "x // 2",
        "x ^ 2",
        "x and x",
        "x\u00a0+\u00a01",
        "\u03c0",
    ],
)
def test_parser_rejects_every_non_language_syntax_class(source: str) -> None:
    with pytest.raises(ExpressionSyntaxError):
        parse_expression(source, ExpressionLimits())


@pytest.mark.parametrize("source", ["\u0661", "\uff11", "x\u0661", "x\uff11"])
def test_parser_rejects_unicode_digits_standalone_and_in_names(
    source: str,
) -> None:
    with pytest.raises(ExpressionSyntaxError):
        parse_expression(source, ExpressionLimits())


@pytest.mark.parametrize(
    "source",
    [
        "",
        "()",
        "(x",
        "x)",
        "x +",
        "* x",
        "sin x",
        "sin()",
    ],
)
def test_parser_rejects_malformed_expressions(source: str) -> None:
    with pytest.raises(ExpressionSyntaxError):
        parse_expression(source, ExpressionLimits())


@pytest.mark.parametrize("source", ["x+(", "(x"])
def test_malformed_expressions_are_not_classified_as_forbidden(
    source: str,
) -> None:
    with pytest.raises(ExpressionSyntaxError) as caught:
        parse_expression(source, ExpressionLimits())

    assert not isinstance(caught.value, ExpressionForbiddenSyntaxError)


@pytest.mark.parametrize(
    "source",
    ["x.__class__", "y", "x**x", "%", "x//2", "x***2", "x**/2"],
)
def test_security_sensitive_syntax_has_a_distinct_parser_subtype(
    source: str,
) -> None:
    with pytest.raises(ExpressionForbiddenSyntaxError):
        parse_expression(source, ExpressionLimits())


@pytest.mark.parametrize(
    "source",
    [
        "x ** x",
        "x ** (1 + 1)",
        "x ** sin(1)",
        "x ** 1025",
        "x ** -1025",
    ],
)
def test_power_rejects_variable_compound_and_out_of_range_exponents(
    source: str,
) -> None:
    with pytest.raises(ExpressionSyntaxError):
        parse_expression(source, ExpressionLimits())


@pytest.mark.parametrize("source", ["x ** -1024", "x ** 0", "x ** +1024"])
def test_power_accepts_direct_numeric_exponents_at_the_inclusive_bounds(
    source: str,
) -> None:
    ast = parse_expression(source, ExpressionLimits())

    canonical = ast_to_canonical_json(ast)
    assert canonical["kind"] == "binary"
    assert canonical["op"] == "power"


@pytest.mark.parametrize("source", ["1e309", "-1e309", "9e999999"])
def test_parser_rejects_non_finite_binary64_literals(source: str) -> None:
    with pytest.raises(ExpressionSyntaxError):
        parse_expression(source, ExpressionLimits())


def test_expression_utf8_byte_limit_accepts_4096_and_rejects_4097() -> None:
    assert ast_to_canonical_json(
        parse_expression(" " * 4095 + "x", ExpressionLimits())
    ) == {"kind": "variable", "name": "x"}

    with pytest.raises(ExpressionLimitError, match="expression_bytes"):
        parse_expression(" " * 4096 + "x", ExpressionLimits())


@pytest.mark.parametrize(
    "overrides",
    [
        {"max_utf8_bytes": 4097},
        {"max_numeric_literal_chars": 65},
        {"max_ast_nodes": 257},
        {"max_ast_depth": 33},
    ],
)
def test_expression_limits_cannot_weaken_the_fixed_security_caps(
    overrides: dict[str, int],
) -> None:
    with pytest.raises(ValueError):
        ExpressionLimits(**overrides)


def test_numeric_literal_limit_accepts_64_and_rejects_65_before_conversion() -> None:
    accepted = "9" * 64
    assert math.isfinite(
        ast_to_canonical_json(
            parse_expression(accepted, ExpressionLimits())
        )["value"]
    )

    with pytest.raises(ExpressionLimitError, match="numeric_literal_chars"):
        parse_expression("9" * 65, ExpressionLimits())


def _balanced_sum(leaf_count: int) -> str:
    if leaf_count == 1:
        return "x"
    left_count = leaf_count // 2
    return (
        f"({_balanced_sum(left_count)}"
        f"+{_balanced_sum(leaf_count - left_count)})"
    )


def test_ast_node_limit_accepts_exactly_256_and_rejects_257() -> None:
    parse_expression(f"-({_balanced_sum(128)})", ExpressionLimits())

    with pytest.raises(ExpressionLimitError, match="ast_nodes"):
        parse_expression(_balanced_sum(129), ExpressionLimits())


def test_ast_depth_limit_accepts_32_and_rejects_33() -> None:
    parse_expression("-" * 31 + "x", ExpressionLimits())

    with pytest.raises(ExpressionLimitError, match="ast_depth"):
        parse_expression("-" * 32 + "x", ExpressionLimits())


def test_parentheses_do_not_consume_canonical_ast_depth() -> None:
    source = "(" * 1000 + "x" + ")" * 1000

    assert ast_to_canonical_json(
        parse_expression(source, ExpressionLimits())
    ) == {"kind": "variable", "name": "x"}


def test_parser_returns_immutable_ast_nodes() -> None:
    ast = parse_expression("x", ExpressionLimits())

    with pytest.raises((FrozenInstanceError, AttributeError)):
        setattr(ast, "name", "y")


@pytest.mark.parametrize(
    "source",
    ["2.5", "x", "pi", "-x", "x + 2", "sin(x)"],
)
def test_canonical_ast_decoder_round_trips_all_six_node_kinds(
    source: str,
) -> None:
    canonical = ast_to_canonical_json(
        parse_expression(source, ExpressionLimits())
    )

    assert ast_to_canonical_json(
        ast_from_canonical_json(canonical)
    ) == canonical


@pytest.mark.parametrize(
    "value",
    [
        None,
        True,
        [],
        {},
        {"kind": "unknown"},
        {"kind": "number"},
        {"kind": "number", "value": True},
        {"kind": "number", "value": float("nan")},
        {"kind": "number", "value": float("inf")},
        {"kind": "number", "value": 9_007_199_254_740_993},
        {"kind": "number", "value": 10**400},
        {"kind": "number", "value": 1.0, "extra": False},
        {"kind": "variable", "name": "y"},
        {"kind": "constant", "name": "tau"},
        {
            "kind": "unary",
            "op": "invert",
            "operand": {"kind": "variable", "name": "x"},
        },
        {
            "kind": "binary",
            "op": "modulo",
            "left": {"kind": "variable", "name": "x"},
            "right": {"kind": "number", "value": 2.0},
        },
        {
            "kind": "call",
            "name": "asin",
            "argument": {"kind": "variable", "name": "x"},
        },
    ],
)
def test_canonical_ast_decoder_rejects_forged_shapes_and_values(
    value: object,
) -> None:
    with pytest.raises(ExpressionSyntaxError):
        ast_from_canonical_json(value)  # type: ignore[arg-type]


def test_canonical_ast_decoder_normalizes_numbers_to_binary64_and_zero() -> None:
    integer = ast_from_canonical_json({"kind": "number", "value": 2})
    negative_zero = ast_from_canonical_json(
        {"kind": "number", "value": -0.0}
    )

    assert ast_to_canonical_json(integer) == {
        "kind": "number",
        "value": 2.0,
    }
    assert ast_to_canonical_json(negative_zero) == {
        "kind": "number",
        "value": 0.0,
    }
    assert math.copysign(
        1.0, ast_to_canonical_json(negative_zero)["value"]
    ) == 1.0


def _balanced_ast_json(leaf_count: int) -> dict[str, object]:
    if leaf_count == 1:
        return {"kind": "variable", "name": "x"}
    left_count = leaf_count // 2
    return {
        "kind": "binary",
        "op": "add",
        "left": _balanced_ast_json(left_count),
        "right": _balanced_ast_json(leaf_count - left_count),
    }


def test_canonical_ast_decoder_enforces_exact_node_and_depth_limits() -> None:
    exact_256 = {
        "kind": "unary",
        "op": "positive",
        "operand": _balanced_ast_json(128),
    }
    ast_from_canonical_json(exact_256)

    with pytest.raises(ExpressionLimitError, match="ast_nodes"):
        ast_from_canonical_json(_balanced_ast_json(129))

    depth_32: dict[str, object] = {"kind": "variable", "name": "x"}
    for _ in range(31):
        depth_32 = {
            "kind": "unary",
            "op": "positive",
            "operand": depth_32,
        }
    ast_from_canonical_json(depth_32)

    depth_33 = {
        "kind": "unary",
        "op": "positive",
        "operand": depth_32,
    }
    with pytest.raises(ExpressionLimitError, match="ast_depth"):
        ast_from_canonical_json(depth_33)


@pytest.mark.parametrize(
    "right",
    [
        {
            "kind": "binary",
            "op": "power",
            "left": {"kind": "number", "value": 2.0},
            "right": {"kind": "number", "value": 3.0},
        },
        {"kind": "number", "value": -1025.0},
        {"kind": "number", "value": 1025.0},
    ],
)
def test_canonical_ast_decoder_rejects_nested_or_out_of_range_power(
    right: dict[str, object],
) -> None:
    with pytest.raises(ExpressionSyntaxError):
        ast_from_canonical_json(
            {
                "kind": "binary",
                "op": "power",
                "left": {"kind": "variable", "name": "x"},
                "right": right,
            }
        )


@pytest.mark.parametrize("evaluator_type", [SolverEvaluator, ValidatorEvaluator])
def test_evaluators_traverse_the_shared_ast_in_operand_order(
    evaluator_type: type[SolverEvaluator] | type[ValidatorEvaluator],
) -> None:
    ast = parse_expression(
        "sqrt(abs(x)) + exp(0) + log(e) + sin(pi / 2) + cos(0) + tan(0)",
        ExpressionLimits(),
    )

    result = evaluator_type().evaluate(ast, -4.0, _budget())

    assert result == pytest.approx(6.0)


@pytest.mark.parametrize("evaluator_type", [SolverEvaluator, ValidatorEvaluator])
def test_evaluators_construct_constants_from_the_fixed_binary64_values(
    evaluator_type: type[SolverEvaluator] | type[ValidatorEvaluator],
) -> None:
    evaluator = evaluator_type()

    assert evaluator.evaluate(
        parse_expression("pi", ExpressionLimits()), 0.0, _budget()
    ) == float.fromhex("0x1.921fb54442d18p+1")
    assert evaluator.evaluate(
        parse_expression("e", ExpressionLimits()), 0.0, _budget()
    ) == float.fromhex("0x1.5bf0a8b145769p+1")


@pytest.mark.parametrize("evaluator_type", [SolverEvaluator, ValidatorEvaluator])
def test_evaluation_budget_counts_each_top_level_evaluation(
    evaluator_type: type[SolverEvaluator] | type[ValidatorEvaluator],
) -> None:
    evaluator = evaluator_type()
    ast = parse_expression("x + 1", ExpressionLimits())
    budget = _budget(max_evaluations=1)

    assert evaluator.evaluate(ast, 1.0, budget) == 2.0
    with pytest.raises(EvaluationBudgetExceeded):
        evaluator.evaluate(ast, 2.0, budget)
    assert budget.evaluations_used == 1


def test_evaluation_budget_never_allows_more_than_20000_evaluations() -> None:
    with pytest.raises(ValueError):
        _budget(max_evaluations=20_001)


@pytest.mark.parametrize("evaluator_type", [SolverEvaluator, ValidatorEvaluator])
@pytest.mark.parametrize("x", [float("nan"), float("inf"), float("-inf")])
def test_evaluators_reject_nonfinite_variable_values(
    evaluator_type: type[SolverEvaluator] | type[ValidatorEvaluator],
    x: float,
) -> None:
    with pytest.raises(EvaluationNonFiniteError):
        evaluator_type().evaluate(
            parse_expression("x", ExpressionLimits()), x, _budget()
        )


@pytest.mark.parametrize("evaluator_type", [SolverEvaluator, ValidatorEvaluator])
def test_evaluators_enforce_node_limit_on_ast_that_bypasses_parser(
    evaluator_type: type[SolverEvaluator] | type[ValidatorEvaluator],
) -> None:
    ast = _balanced_ast(128)
    exact_256 = UnaryNode(op="positive", operand=ast)
    assert evaluator_type().evaluate(exact_256, 1.0, _budget()) == 128.0

    oversized_ast = UnaryNode(op="positive", operand=exact_256)
    with pytest.raises(EvaluationBudgetExceeded):
        evaluator_type().evaluate(oversized_ast, 1.0, _budget())


def _balanced_ast(leaf_count: int) -> ExpressionAst:
    if leaf_count == 1:
        return VariableNode()
    left_count = leaf_count // 2
    return BinaryNode(
        op="add",
        left=_balanced_ast(left_count),
        right=_balanced_ast(leaf_count - left_count),
    )


@pytest.mark.parametrize("evaluator_type", [SolverEvaluator, ValidatorEvaluator])
def test_evaluators_enforce_depth_limit_on_ast_that_bypasses_parser(
    evaluator_type: type[SolverEvaluator] | type[ValidatorEvaluator],
) -> None:
    depth_32: ExpressionAst = VariableNode()
    for _ in range(31):
        depth_32 = UnaryNode(op="positive", operand=depth_32)
    assert evaluator_type().evaluate(depth_32, 1.0, _budget()) == 1.0

    depth_33 = UnaryNode(op="positive", operand=depth_32)
    with pytest.raises(EvaluationBudgetExceeded) as error:
        evaluator_type().evaluate(depth_33, 1.0, _budget())
    assert error.value.resource == "ast_depth"


@pytest.mark.parametrize("evaluator_type", [SolverEvaluator, ValidatorEvaluator])
def test_evaluators_check_cancellation_during_node_traversal(
    evaluator_type: type[SolverEvaluator] | type[ValidatorEvaluator],
) -> None:
    cancellation = _Cancellation(cancel_on_check=3)
    budget = _budget(cancellation=cancellation)

    with pytest.raises(EvaluationCancelled):
        evaluator_type().evaluate(
            parse_expression("x + x", ExpressionLimits()), 1.0, budget
        )
    assert cancellation.checks == 3


@pytest.mark.parametrize("evaluator_type", [SolverEvaluator, ValidatorEvaluator])
def test_evaluators_check_deadline_before_visiting_a_node(
    evaluator_type: type[SolverEvaluator] | type[ValidatorEvaluator],
) -> None:
    budget = _budget(deadline=1.0, clock=_Clock(now=1.0))

    with pytest.raises(EvaluationDeadlineExceeded):
        evaluator_type().evaluate(
            parse_expression("x", ExpressionLimits()), 1.0, budget
        )


@pytest.mark.parametrize(
    ("source", "x", "expected_error"),
    [
        ("1 / 0", 0.0, EvaluationDomainError),
        ("sqrt(x)", -1.0, EvaluationDomainError),
        ("log(x)", 0.0, EvaluationDomainError),
        ("exp(1000)", 0.0, EvaluationNonFiniteError),
        ("1e308 * 1e308", 0.0, EvaluationNonFiniteError),
    ],
)
@pytest.mark.parametrize("evaluator_type", [SolverEvaluator, ValidatorEvaluator])
def test_evaluators_expose_distinct_domain_and_nonfinite_failures(
    evaluator_type: type[SolverEvaluator] | type[ValidatorEvaluator],
    source: str,
    x: float,
    expected_error: type[ArithmeticError],
) -> None:
    with pytest.raises(expected_error):
        evaluator_type().evaluate(
            parse_expression(source, ExpressionLimits()), x, _budget()
        )


@pytest.mark.parametrize("evaluator_type", [SolverEvaluator, ValidatorEvaluator])
def test_evaluators_type_invalid_direct_ast_power_as_a_domain_failure(
    evaluator_type: type[SolverEvaluator] | type[ValidatorEvaluator],
) -> None:
    unsafe_ast = BinaryNode(
        op="power",
        left=NumberNode(-1.0),
        right=VariableNode(),
    )

    with pytest.raises(EvaluationDomainError):
        evaluator_type().evaluate(unsafe_ast, 0.5, _budget())


@pytest.mark.parametrize("evaluator_type", [SolverEvaluator, ValidatorEvaluator])
def test_invalid_power_shape_is_rejected_before_exponent_evaluation(
    evaluator_type: type[SolverEvaluator] | type[ValidatorEvaluator],
) -> None:
    unsafe_ast = BinaryNode(
        op="power",
        left=NumberNode(2.0),
        right=CallNode(name="exp", argument=NumberNode(1000.0)),
    )

    with pytest.raises(EvaluationDomainError):
        evaluator_type().evaluate(unsafe_ast, 0.0, _budget())


def _module_source(module: ModuleType) -> str:
    assert module.__file__ is not None
    return Path(module.__file__).read_text(encoding="utf-8")


def test_evaluator_modules_do_not_import_each_other_or_shared_numeric_helpers() -> None:
    solver = importlib.import_module(
        "modeling_capabilities.root_finding.expression.solver_evaluator"
    )
    validator = importlib.import_module(
        "modeling_capabilities.root_finding.expression.validator_evaluator"
    )
    solver_source = _module_source(solver)
    validator_source = _module_source(validator)

    assert "validator_evaluator" not in solver_source
    assert "solver_evaluator" not in validator_source
    assert "numeric_helpers" not in solver_source
    assert "numeric_helpers" not in validator_source


def test_expression_implementation_contains_no_dynamic_python_evaluation() -> None:
    package = importlib.import_module(
        "modeling_capabilities.root_finding.expression"
    )
    assert package.__file__ is not None
    source_root = Path(package.__file__).parent
    forbidden_calls = {"eval", "exec", "compile"}
    observed_calls: set[str] = set()
    observed_imports: set[str] = set()

    for source_path in source_root.glob("*.py"):
        tree = python_ast.parse(source_path.read_text(encoding="utf-8"))
        for node in python_ast.walk(tree):
            if isinstance(node, python_ast.Call) and isinstance(
                node.func, python_ast.Name
            ):
                observed_calls.add(node.func.id)
            elif isinstance(node, python_ast.Import):
                observed_imports.update(alias.name for alias in node.names)
            elif isinstance(node, python_ast.ImportFrom) and node.module is not None:
                observed_imports.add(node.module)

    assert forbidden_calls.isdisjoint(observed_calls)
    assert "ast" not in observed_imports
