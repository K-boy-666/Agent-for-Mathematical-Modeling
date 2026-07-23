from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Literal

from mcp.server.fastmcp import FastMCP

Equation = Literal["x*x-2"]


@dataclass(frozen=True)
class SpikeRootResult:
    root: float
    residual: float
    iterations: int
    equation: Equation


def solve_fixed_root(
    equation: Equation,
    lower: float,
    upper: float,
    tolerance: float,
    max_iterations: int,
) -> SpikeRootResult:
    if equation != "x*x-2":
        raise ValueError("M1a-0 accepts only x*x-2")
    if not all(math.isfinite(value) for value in (lower, upper, tolerance)):
        raise ValueError("inputs must be finite")
    if lower >= upper or tolerance <= 0.0 or max_iterations != 100:
        raise ValueError("invalid M1a-0 bounds, tolerance, or iteration limit")
    f_lower = lower * lower - 2.0
    f_upper = upper * upper - 2.0
    if f_lower * f_upper > 0.0:
        raise ValueError("interval does not bracket a root")
    for iteration in range(1, max_iterations + 1):
        midpoint = lower + (upper - lower) / 2.0
        f_midpoint = midpoint * midpoint - 2.0
        if abs(f_midpoint) <= tolerance or (upper - lower) / 2.0 <= tolerance:
            return SpikeRootResult(midpoint, abs(f_midpoint), iteration, equation)
        if f_lower * f_midpoint <= 0.0:
            upper = midpoint
        else:
            lower = midpoint
            f_lower = f_midpoint
    raise RuntimeError("M1a-0 bisection did not converge")


mcp = FastMCP("modeling-spike")


@mcp.tool()
def root_finding(
    equation: Equation,
    lower: float,
    upper: float,
    tolerance: float,
) -> dict[str, float | int | str]:
    return asdict(solve_fixed_root(equation, lower, upper, tolerance, 100))


if __name__ == "__main__":
    mcp.run(transport="stdio")
