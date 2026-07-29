from __future__ import annotations

from typing import cast

import pytest

from modeling_capabilities.root_finding.solver import (
    BisectionRootFindingCapability,
)
from modeling_core.contracts.capability import (
    CancellationSignal,
    ExecutionContext,
)
from modeling_core.contracts.common import JsonObject


class _Clock:
    def utc_now(self) -> object:
        raise AssertionError("wall time is outside solver authority")

    def monotonic(self) -> float:
        return 0.0


class _NeverCancelled:
    def is_cancelled(self) -> bool:
        return False


def _root(expression: str, lower: float, upper: float) -> float:
    capability = BisectionRootFindingCapability()
    raw: JsonObject = {
        "expression": expression,
        "lower": lower,
        "upper": upper,
        "absolute_tolerance": 1e-12,
        "relative_tolerance": 1e-12,
        "function_tolerance": 1e-12,
        "max_iterations": 200,
    }
    canonical = capability.normalize_and_validate(raw)
    outcome = capability.execute(
        canonical,
        ExecutionContext(
            attempt_id="22222222-2222-4222-8222-222222222222",
            randomness="not_used",
            seed=None,
            deadline=10.0,
            clock=_Clock(),
            cancellation=cast(
                CancellationSignal, _NeverCancelled()
            ),
        ),
    )
    assert outcome.result_kind == "success"
    return outcome.result_payload.data.root


def test_translation_shifts_root_by_same_amount() -> None:
    original = _root("x*x-2", 0.0, 2.0)
    shifted = _root("(x-3)*(x-3)-2", 3.0, 5.0)

    assert shifted == pytest.approx(
        original + 3.0, rel=0.0, abs=1e-9
    )


@pytest.mark.parametrize("scale", [7.0, -3.0])
def test_nonzero_scale_and_sign_flip_preserve_root(scale: float) -> None:
    original = _root("x*x-2", 0.0, 2.0)
    transformed = _root(f"{scale}*(x*x-2)", 0.0, 2.0)

    assert transformed == pytest.approx(
        original, rel=0.0, abs=1e-9
    )


def test_narrowed_valid_bracket_preserves_root() -> None:
    broad = _root("x*x-2", 0.0, 2.0)
    narrow = _root("x*x-2", 1.0, 1.5)

    assert narrow == pytest.approx(broad, rel=0.0, abs=1e-9)
