from __future__ import annotations

import json
import math
from collections.abc import Iterator
from importlib.resources import files
from typing import cast

import pytest

from modeling_capabilities.root_finding.contracts import (
    EvaluationBudget,
    EvaluationBudgetExceeded,
    EvaluationCancelled,
    EvaluationDeadlineExceeded,
    InputValidationError,
)
from modeling_capabilities.root_finding.expression.solver_evaluator import (
    SolverEvaluator,
)
from modeling_capabilities.root_finding.solver import (
    BisectionRootFindingCapability,
)
from modeling_capabilities.root_finding.validator import (
    ResidualRootFindingValidator,
)
from modeling_core.contracts.capability import (
    BuiltInCapability,
    CancellationSignal,
    CanonicalInputRecord,
    ExecutionContext,
    ExecutionOutcome,
)
from modeling_core.contracts.canonical_json import sha256_json
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.versions import VersionSet
from modeling_core.registry import CapabilityRegistry, RegistryError

_ATTEMPT_ID = "11111111-1111-4111-8111-111111111111"


class _Clock:
    def __init__(self, values: Iterator[float] | None = None) -> None:
        self._values = values
        self._last = 0.0

    def utc_now(self) -> object:
        raise AssertionError("the solver must not read wall-clock time")

    def monotonic(self) -> float:
        if self._values is not None:
            self._last = next(self._values, self._last)
        return self._last

    def set(self, value: float) -> None:
        self._last = value


class _Cancellation:
    def __init__(
        self,
        cancelled: bool = False,
        *,
        cancel_on_check: int | None = None,
    ) -> None:
        self.cancelled = cancelled
        self.cancel_on_check = cancel_on_check
        self.checks = 0

    def is_cancelled(self) -> bool:
        self.checks += 1
        return self.cancelled or (
            self.cancel_on_check is not None and self.checks >= self.cancel_on_check
        )


def _context(
    *,
    clock: _Clock | None = None,
    cancellation: _Cancellation | None = None,
    deadline: float = 10.0,
) -> ExecutionContext:
    return ExecutionContext(
        attempt_id=_ATTEMPT_ID,
        randomness="not_used",
        seed=None,
        deadline=deadline,
        clock=clock or _Clock(),
        cancellation=cast(CancellationSignal, cancellation or _Cancellation()),
    )


def _raw(
    expression: str,
    lower: float,
    upper: float,
    *,
    absolute_tolerance: float = 1e-10,
    relative_tolerance: float = 1e-10,
    function_tolerance: float = 1e-10,
    max_iterations: int = 100,
) -> JsonObject:
    return {
        "expression": expression,
        "lower": lower,
        "upper": upper,
        "absolute_tolerance": absolute_tolerance,
        "relative_tolerance": relative_tolerance,
        "function_tolerance": function_tolerance,
        "max_iterations": max_iterations,
    }


def _execute(
    expression: str,
    lower: float,
    upper: float,
    *,
    context: ExecutionContext | None = None,
    absolute_tolerance: float = 1e-10,
    relative_tolerance: float = 1e-10,
    function_tolerance: float = 1e-10,
    max_iterations: int = 100,
) -> ExecutionOutcome:
    capability = BisectionRootFindingCapability()
    canonical = capability.normalize_and_validate(
        _raw(
            expression,
            lower,
            upper,
            absolute_tolerance=absolute_tolerance,
            relative_tolerance=relative_tolerance,
            function_tolerance=function_tolerance,
            max_iterations=max_iterations,
        )
    )
    return capability.execute(canonical, context or _context())


def test_capability_satisfies_protocol_and_finds_sqrt_two() -> None:
    capability = BisectionRootFindingCapability()

    assert isinstance(capability, BuiltInCapability)
    outcome = _execute("x*x-2", 0.0, 2.0)
    payload = outcome.result_payload

    assert outcome.result_kind == "success"
    assert payload.result_kind == "success"
    assert abs(payload.data.root - math.sqrt(2.0)) <= 1e-8
    assert abs(payload.data.function_value) <= 1e-10
    assert payload.data.evaluations == payload.data.iterations + 2
    assert payload.data.iterations > 0
    assert payload.data.termination_reason in {
        "residual_tolerance",
        "interval_tolerance",
    }


def test_execute_rejects_outer_canonical_schema_version_before_evaluation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = BisectionRootFindingCapability()
    valid = capability.normalize_and_validate(_raw("x", -1.0, 1.0))
    mismatched = CanonicalInputRecord(
        canonical_input_schema_version=("numerical.root_finding.canonical-input/9.9.9"),
        canonical_payload=valid.canonical_payload,
        canonical_payload_hash=valid.canonical_payload_hash,
        model_snapshot_hash=valid.model_snapshot_hash,
        data_snapshot_references=valid.data_snapshot_references,
        data_snapshot_set_hash=valid.data_snapshot_set_hash,
    )
    evaluations = 0

    def forbidden_evaluation(
        _self: SolverEvaluator, _ast: object, _x: float, _budget: object
    ) -> float:
        nonlocal evaluations
        evaluations += 1
        raise AssertionError("schema mismatch reached numerical evaluation")

    monkeypatch.setattr(SolverEvaluator, "evaluate", forbidden_evaluation)

    with pytest.raises(InputValidationError) as caught:
        capability.execute(mismatched, _context())
    assert caught.value.field_path == "/canonical_input_schema_version"
    assert caught.value.reason == "capability_payload_violation"
    assert evaluations == 0


@pytest.mark.parametrize(
    ("expression", "expected_root", "expected_evaluations"),
    [
        ("(x-0)*(x-2)", 0.0, 1),
        ("x-2", 2.0, 2),
    ],
)
def test_endpoint_roots_use_lower_then_upper_priority_and_exact_counts(
    expression: str, expected_root: float, expected_evaluations: int
) -> None:
    outcome = _execute(expression, 0.0, 2.0)
    data = outcome.result_payload.data

    assert outcome.result_kind == "success"
    assert data.root == expected_root
    assert data.function_value == 0.0
    assert data.iterations == 0
    assert data.evaluations == expected_evaluations
    assert data.termination_reason == "endpoint_root"


def test_when_both_endpoints_are_roots_lower_wins_without_upper_evaluation() -> None:
    outcome = _execute("(x-0)*(x-2)", 0.0, 2.0)
    data = outcome.result_payload.data

    assert data.root == 0.0
    assert data.evaluations == 1


@pytest.mark.parametrize(
    (
        "expression",
        "lower",
        "upper",
        "max_iterations",
        "failure_code",
        "iterations",
        "evaluations",
    ),
    [
        ("x*x+1", -1.0, 1.0, 100, "no_sign_change", 0, 2),
        ("1/x", 0.0, 1.0, 100, "domain_error", 0, 1),
        ("exp(x)", 1000.0, 1001.0, 100, "non_finite_evaluation", 0, 1),
        ("x*x-2", 0.0, 2.0, 1, "non_convergence", 1, 3),
    ],
)
def test_expected_math_failures_have_exact_codes_and_counts(
    expression: str,
    lower: float,
    upper: float,
    max_iterations: int,
    failure_code: str,
    iterations: int,
    evaluations: int,
) -> None:
    outcome = _execute(
        expression,
        lower,
        upper,
        max_iterations=max_iterations,
        absolute_tolerance=5e-324,
        relative_tolerance=5e-324,
        function_tolerance=5e-324,
    )
    data = outcome.result_payload.data

    assert outcome.result_kind == "numerical_failure"
    assert outcome.result_payload.result_kind == "numerical_failure"
    assert data.failure_code == failure_code
    assert data.iterations == iterations
    assert data.evaluations == evaluations


def test_midpoint_domain_error_counts_failed_evaluation_and_iteration() -> None:
    outcome = _execute(
        "1/x",
        -1.0,
        1.0,
        function_tolerance=5e-324,
    )
    data = outcome.result_payload.data

    assert outcome.result_kind == "numerical_failure"
    assert data.failure_code == "domain_error"
    assert data.iterations == 1
    assert data.evaluations == 3


def test_adjacent_binary64_midpoint_collapse_is_non_convergence() -> None:
    lower = math.pi / 2.0
    upper = math.nextafter(lower, math.inf)
    assert math.nextafter(lower, math.inf) == upper
    outcome = _execute(
        "tan(x)",
        lower,
        upper,
        function_tolerance=5e-324,
        absolute_tolerance=5e-324,
        relative_tolerance=5e-324,
    )
    data = outcome.result_payload.data

    assert outcome.result_kind == "numerical_failure"
    assert data.failure_code == "non_convergence"
    assert data.iterations == 1
    assert data.evaluations == 3


def test_midpoint_collapse_still_checks_interval_tolerance_after_evaluation() -> None:
    lower = math.pi / 2.0
    upper = math.nextafter(lower, math.inf)

    outcome = _execute("tan(x)", lower, upper)
    data = outcome.result_payload.data

    assert outcome.result_kind == "success"
    assert data.root == lower
    assert data.function_value == math.tan(lower)
    assert data.iterations == 1
    assert data.evaluations == 3
    assert data.termination_reason == "interval_tolerance"


def test_opposite_coordinate_signs_use_overflow_safe_midpoint() -> None:
    outcome = _execute(
        "x",
        -1.7e308,
        1.7e308,
        function_tolerance=5e-324,
    )
    data = outcome.result_payload.data

    assert outcome.result_kind == "success"
    assert data.root == 0.0
    assert data.function_value == 0.0
    assert data.iterations == 1
    assert data.evaluations == 3


def test_same_sign_coordinates_use_difference_based_midpoint() -> None:
    outcome = _execute(
        "x/1e308-1.2",
        1e308,
        1.7e308,
        absolute_tolerance=1.0,
        relative_tolerance=1.0,
        function_tolerance=5e-324,
        max_iterations=200,
    )
    data = outcome.result_payload.data

    assert outcome.result_kind == "success"
    assert data.root == pytest.approx(1.35e308)
    assert math.isfinite(data.root)
    assert math.isfinite(data.function_value)
    assert data.termination_reason == "interval_tolerance"


def test_sign_comparison_does_not_multiply_large_endpoint_values() -> None:
    outcome = _execute(
        "1e308*x",
        -1.0,
        1.0,
        function_tolerance=5e-324,
    )
    data = outcome.result_payload.data

    assert outcome.result_kind == "success"
    assert data.root == 0.0
    assert data.termination_reason == "residual_tolerance"


def test_sign_comparison_does_not_multiply_values_that_underflow() -> None:
    outcome = _execute(
        "1e-200*x",
        -1.0,
        1.0,
        function_tolerance=5e-324,
    )

    assert outcome.result_kind == "success"
    assert outcome.result_payload.data.root == 0.0


def test_same_sign_values_with_underflowing_product_are_not_bracketed() -> None:
    outcome = _execute(
        "1e-200*(x*x+1)",
        -1.0,
        1.0,
        absolute_tolerance=5e-324,
        relative_tolerance=5e-324,
        function_tolerance=5e-324,
    )
    data = outcome.result_payload.data

    assert outcome.result_kind == "numerical_failure"
    assert data.failure_code == "no_sign_change"
    assert data.iterations == 0
    assert data.evaluations == 2


def test_residual_precedes_interval_tolerance() -> None:
    outcome = _execute(
        "x",
        -1.0,
        1.0,
        absolute_tolerance=1.0,
        relative_tolerance=1.0,
        function_tolerance=1e-10,
    )

    assert outcome.result_kind == "success"
    assert outcome.result_payload.data.termination_reason == ("residual_tolerance")


def test_interval_success_preserves_real_midpoint_value_and_exact_counts() -> None:
    outcome = _execute(
        "x-0.3",
        0.0,
        1.0,
        absolute_tolerance=1.0,
        relative_tolerance=1.0,
        function_tolerance=1e-12,
    )
    data = outcome.result_payload.data

    assert outcome.result_kind == "success"
    assert data.root == 0.5
    assert data.function_value == pytest.approx(0.2)
    assert data.iterations == 1
    assert data.evaluations == 3
    assert data.termination_reason == "interval_tolerance"


def test_deadline_equality_propagates_without_result_payload() -> None:
    capability = BisectionRootFindingCapability()
    canonical = capability.normalize_and_validate(_raw("x", -1.0, 1.0))
    context = _context(clock=_Clock(iter([10.0])), deadline=10.0)

    with pytest.raises(EvaluationDeadlineExceeded):
        capability.execute(canonical, context)


def test_cancellation_has_priority_over_equal_deadline() -> None:
    capability = BisectionRootFindingCapability()
    canonical = capability.normalize_and_validate(_raw("x", -1.0, 1.0))
    cancellation = _Cancellation(cancelled=True)
    context = _context(
        clock=_Clock(iter([10.0])),
        cancellation=cancellation,
        deadline=10.0,
    )

    with pytest.raises(EvaluationCancelled):
        capability.execute(canonical, context)
    assert cancellation.checks >= 1


@pytest.mark.parametrize(
    ("control", "check_index", "expected_evaluations"),
    [
        ("cancel", 2, 1),  # lower -> upper
        ("deadline", 2, 1),
        ("cancel", 3, 2),  # upper -> loop
        ("deadline", 3, 2),
        ("cancel", 4, 2),  # loop -> midpoint evaluation
        ("deadline", 4, 2),
    ],
)
def test_control_is_checked_at_every_evaluation_transition(
    monkeypatch: pytest.MonkeyPatch,
    control: str,
    check_index: int,
    expected_evaluations: int,
) -> None:
    capability = BisectionRootFindingCapability()
    canonical = capability.normalize_and_validate(
        _raw(
            "x",
            -1.0,
            1.0,
            function_tolerance=5e-324,
        )
    )
    cancellation = _Cancellation(
        cancel_on_check=check_index if control == "cancel" else None
    )
    clock = _Clock(iter([0.0] * (check_index - 1) + [10.0] + [10.0] * 8))
    evaluations = 0

    def controlled_evaluation(
        _self: SolverEvaluator,
        _ast: object,
        x: float,
        budget: EvaluationBudget,
    ) -> float:
        nonlocal evaluations
        budget.begin_evaluation()
        evaluations += 1
        return x

    monkeypatch.setattr(SolverEvaluator, "evaluate", controlled_evaluation)
    context = _context(
        clock=clock,
        cancellation=cancellation,
        deadline=10.0,
    )

    expected_exception = (
        EvaluationCancelled if control == "cancel" else EvaluationDeadlineExceeded
    )
    with pytest.raises(expected_exception):
        capability.execute(canonical, context)
    assert evaluations == expected_evaluations


@pytest.mark.parametrize("result_path", ["success", "failure"])
@pytest.mark.parametrize("control", ["cancel", "deadline"])
def test_control_is_checked_before_success_and_failure_final_return(
    monkeypatch: pytest.MonkeyPatch,
    result_path: str,
    control: str,
) -> None:
    capability = BisectionRootFindingCapability()
    canonical = capability.normalize_and_validate(_raw("x", -1.0, 1.0))
    cancellation = _Cancellation()
    clock = _Clock()
    calls = 0

    def evaluation_then_stop(
        _self: SolverEvaluator,
        _ast: object,
        _x: float,
        budget: EvaluationBudget,
    ) -> float:
        nonlocal calls
        budget.begin_evaluation()
        calls += 1
        final_call = calls == (1 if result_path == "success" else 2)
        if final_call:
            clock.set(10.0)
            if control == "cancel":
                cancellation.cancelled = True
        return 0.0 if result_path == "success" else 1.0

    monkeypatch.setattr(SolverEvaluator, "evaluate", evaluation_then_stop)
    expected_exception = (
        EvaluationCancelled if control == "cancel" else EvaluationDeadlineExceeded
    )

    with pytest.raises(expected_exception):
        capability.execute(
            canonical,
            _context(
                clock=clock,
                cancellation=cancellation,
                deadline=10.0,
            ),
        )
    assert calls == (1 if result_path == "success" else 2)


@pytest.mark.parametrize(
    "error",
    [
        EvaluationBudgetExceeded("function_evaluations", 2),
        EvaluationCancelled("cancelled inside evaluator"),
        EvaluationDeadlineExceeded("deadline inside evaluator"),
    ],
)
def test_control_and_budget_exceptions_propagate_unchanged(
    monkeypatch: pytest.MonkeyPatch, error: RuntimeError
) -> None:
    capability = BisectionRootFindingCapability()
    canonical = capability.normalize_and_validate(_raw("x", -1.0, 1.0))

    def raise_exact(
        _self: SolverEvaluator, _ast: object, _x: float, _budget: object
    ) -> float:
        raise error

    monkeypatch.setattr(SolverEvaluator, "evaluate", raise_exact)

    with pytest.raises(type(error)) as caught:
        capability.execute(canonical, _context())
    assert caught.value is error


def test_all_evaluations_share_one_real_budget_with_fixed_maximum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = BisectionRootFindingCapability()
    canonical = capability.normalize_and_validate(
        _raw("x", -1.0, 1.0, function_tolerance=5e-324)
    )
    budgets: list[EvaluationBudget] = []

    def capture_budget(
        _self: SolverEvaluator,
        _ast: object,
        x: float,
        budget: EvaluationBudget,
    ) -> float:
        budget.begin_evaluation()
        budgets.append(budget)
        return x

    monkeypatch.setattr(SolverEvaluator, "evaluate", capture_budget)
    outcome = capability.execute(canonical, _context())

    assert outcome.result_kind == "success"
    assert len(budgets) == 3
    assert len({id(budget) for budget in budgets}) == 1
    assert budgets[0].max_evaluations == 20_000
    assert budgets[0].evaluations_used == 3


@pytest.mark.parametrize(
    ("expression", "failure_code"),
    [
        ("1/(1-x)", "domain_error"),
        ("exp(x)", "non_finite_evaluation"),
    ],
)
def test_upper_endpoint_failure_has_exact_count(
    expression: str, failure_code: str
) -> None:
    upper = 1.0 if failure_code == "domain_error" else 1000.0
    outcome = _execute(
        expression,
        0.0,
        upper,
        function_tolerance=5e-324,
    )
    data = outcome.result_payload.data

    assert outcome.result_kind == "numerical_failure"
    assert data.failure_code == failure_code
    assert data.iterations == 0
    assert data.evaluations == 2


def test_midpoint_non_finite_failure_counts_iteration_and_evaluation() -> None:
    outcome = _execute(
        "exp(1000-x**2)+x",
        -40.0,
        40.0,
        function_tolerance=5e-324,
    )
    data = outcome.result_payload.data

    assert outcome.result_kind == "numerical_failure"
    assert data.failure_code == "non_finite_evaluation"
    assert data.iterations == 1
    assert data.evaluations == 3


def test_unexpected_evaluator_exception_propagates_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capability = BisectionRootFindingCapability()
    canonical = capability.normalize_and_validate(_raw("x", -1.0, 1.0))
    error = RuntimeError("unexpected evaluator defect")

    def raise_unexpected(
        _self: SolverEvaluator,
        _ast: object,
        _x: float,
        _budget: EvaluationBudget,
    ) -> float:
        raise error

    monkeypatch.setattr(SolverEvaluator, "evaluate", raise_unexpected)

    with pytest.raises(RuntimeError) as caught:
        capability.execute(canonical, _context())
    assert caught.value is error


@pytest.mark.parametrize(
    ("expression", "lower", "upper"),
    [
        ("x*x-2", 0.0, 2.0),
        ("x", -1.0, 1.0),
        ("x-2", 0.0, 2.0),
    ],
)
def test_result_payload_has_exact_fields_and_only_finite_numbers(
    expression: str, lower: float, upper: float
) -> None:
    payload = _execute(expression, lower, upper).result_payload.model_dump(mode="json")

    assert set(payload) == {
        "result_schema_version",
        "capability_id",
        "contract_version",
        "result_kind",
        "data",
    }
    assert set(payload["data"]) == {
        "root",
        "function_value",
        "iterations",
        "evaluations",
        "termination_reason",
    }
    for name in ("root", "function_value"):
        assert math.isfinite(payload["data"][name])


def test_numerical_failure_payload_has_exact_fields() -> None:
    payload = _execute("x*x+1", -1.0, 1.0).result_payload.model_dump(mode="json")

    assert set(payload) == {
        "result_schema_version",
        "capability_id",
        "contract_version",
        "result_kind",
        "data",
    }
    assert set(payload["data"]) == {
        "failure_code",
        "iterations",
        "evaluations",
    }


def test_descriptor_has_fixed_identity_limits_and_packaged_schema_hashes() -> None:
    descriptor = BisectionRootFindingCapability().descriptor
    root = files("modeling_capabilities.root_finding").joinpath("schemas", "0.1.0")

    assert descriptor.kind == "built_in"
    assert descriptor.capability_api_version == "modeling-capability/0.1.0"
    assert descriptor.capability_id == "numerical.root_finding"
    assert descriptor.contract_version == "0.1.0"
    assert descriptor.implementation_id == "builtin.numerical.root_finding.bisection"
    assert descriptor.implementation_version == "0.1.0"
    assert descriptor.category == "numerical"
    assert descriptor.determinism == "deterministic"
    assert descriptor.randomness == "not_used"
    assert descriptor.default_limits.model_dump() == {
        "timeout_ms": 10_000,
        "max_iterations": 100,
        "max_evaluations": 20_000,
    }
    assert descriptor.maximum_limits.model_dump() == {
        "timeout_ms": 60_000,
        "max_iterations": 10_000,
        "max_evaluations": 20_000,
    }
    assert descriptor.artifact_roles == ()
    assert len(descriptor.validators) == 1
    validator = descriptor.validators[0]
    assert validator.validator_id == "numerical.root_finding.residual"
    assert tuple(policy.policy_version for policy in validator.policies) == ("0.1.0",)
    assert validator.report_schema_version == "modeling-validation-report/0.1.0"
    for reference, name in (
        (descriptor.input_schema, "input.schema.json"),
        (descriptor.canonical_input_schema, "canonical-input.schema.json"),
        (descriptor.success_schema, "success-data.schema.json"),
        (descriptor.failure_schema, "failure-data.schema.json"),
    ):
        assert root.joinpath(name).is_file()
        disk_schema = json.loads(root.joinpath(name).read_text(encoding="utf-8"))
        assert reference.schema == disk_schema
        assert reference.schema_hash == sha256_json(reference.schema)


def test_test_local_registry_resolves_only_exact_capability_version() -> None:
    capability = BisectionRootFindingCapability()
    registry = CapabilityRegistry(VersionSet.m1a())
    registry.register_capability(capability)
    registry.register_validator(ResidualRootFindingValidator())
    registry.seal(frozenset({("numerical.root_finding", "0.1.0")}))

    resolved = registry.resolve("numerical.root_finding", "0.1.0")
    assert resolved.descriptor == capability.descriptor
    assert resolved.normalize_and_validate(
        _raw("x", -1.0, 1.0)
    ) == capability.normalize_and_validate(_raw("x", -1.0, 1.0))
    with pytest.raises(RegistryError) as caught:
        registry.resolve("numerical.root_finding", "1.0.0")
    assert caught.value.code == "NOT_FOUND"
