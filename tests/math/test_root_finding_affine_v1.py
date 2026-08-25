from __future__ import annotations

import math
import random
from typing import cast

import pytest

from modeling_capabilities.root_finding.solver import BisectionRootFindingCapability
from modeling_core.contracts.capability import CancellationSignal, ExecutionContext
from modeling_core.contracts.common import JsonObject
from modeling_core.contracts.versions import VersionSet


class _Clock:
    def utc_now(self) -> object:
        raise AssertionError("wall time is outside solver authority")

    def monotonic(self) -> float:
        return 0.0


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


def _execute(expression: str, lower: float, upper: float) -> object:
    capability = BisectionRootFindingCapability(VersionSet.m1b())
    canonical = capability.normalize_and_validate(
        cast(
            JsonObject,
            {
                "expression": expression,
                "lower": lower,
                "upper": upper,
                "absolute_tolerance": 1e-10,
                "relative_tolerance": 1e-10,
                "function_tolerance": 1e-10,
                "max_iterations": 1000,
            },
        )
    )
    return capability.execute(
        canonical,
        ExecutionContext(
            attempt_id="22222222-2222-4222-8222-222222222222",
            randomness="not_used",
            seed=None,
            deadline=10.0,
            clock=_Clock(),
            cancellation=cast(CancellationSignal, _NeverCancelled()),
        ),
    )


def test_fixed_seed_affine_family_preserves_analytical_roots() -> None:
    """Catches scaling, translation or sign handling moving a bracketed root."""
    seed = 20260716
    generator = random.Random(seed)
    nonzero_ranges = ((-8.0, -0.125), (0.125, 8.0))
    for case_index in range(200):
        r = generator.uniform(-10.0, 10.0)
        c = generator.uniform(-10.0, 10.0)
        a = generator.uniform(*nonzero_ranges[generator.randrange(2)])
        b = generator.uniform(*nonzero_ranges[generator.randrange(2)])
        d = generator.uniform(0.5, 5.0)
        expected = (r - c) / b
        expression = f"({a!r})*(({b!r})*x+({c!r})-({r!r}))"

        outcome = _execute(expression, expected - d, expected + d)

        assert outcome.result_kind == "success", (seed, case_index, outcome)
        data = outcome.result_payload.data
        assert data.root == pytest.approx(expected, rel=1e-10, abs=1e-10), (
            seed,
            case_index,
        )
        residual = a * (b * data.root + c - r)
        assert math.isfinite(residual), (seed, case_index)
        assert abs(residual) <= 1e-10, (seed, case_index, residual)


@pytest.mark.parametrize(
    ("expression", "lower", "upper", "expected_kind", "expected_code"),
    [
        ("exp(x)", 1000.0, 1001.0, "numerical_failure", "non_finite_evaluation"),
        ("1/(1e-300*x)", -1e-300, 1e-300, "numerical_failure", "domain_error"),
        ("sqrt(x)", -2.0, -1.0, "numerical_failure", "domain_error"),
        ("1e308*1e308+x", -1.0, 1.0, "numerical_failure", "non_finite_evaluation"),
    ],
)
def test_nonfinite_and_extreme_finite_branches_are_classified(
    expression: str,
    lower: float,
    upper: float,
    expected_kind: str,
    expected_code: str | None,
) -> None:
    """Catches overflow, underflow-to-zero, domain and nonfinite intermediates."""
    outcome = _execute(expression, lower, upper)
    assert outcome.result_kind == expected_kind
    if expected_code is not None:
        assert outcome.result_payload.data.failure_code == expected_code
