"""Coupled-heave production solver for CUMCM-2022-A-Q1.

Uses DOP853 with rtol=1e-9, atol=1e-11. Output grid is exactly
t_i = 0.2*i, i=0..897, for 898 rows ending at 179.4 seconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum, auto

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import solve_ivp

# ── solver configuration ──────────────────────────────────────────────

SOLVER_METHOD: str = "DOP853"
SOLVER_RTOL: float = 1e-9
SOLVER_ATOL: float = 1e-11

# ── output grid ───────────────────────────────────────────────────────

OUTPUT_DT: float = 0.2
OUTPUT_N: int = 898
OUTPUT_T_END: float = 179.4


class DampingMode(Enum):
    LINEAR = auto()
    POWER_LAW = auto()


# ── parameters ────────────────────────────────────────────────────────


@dataclass(frozen=True)
class CoupledHeaveParams:
    """Parameters for the coupled-heave model (CUMCM-2022-A-Q1)."""

    omega: float = 1.4005
    m_a: float = 1335.535
    B: float = 656.3616
    F: float = 6250
    m_f: float = 4866
    m_o: float = 2433
    r: float = 1.0
    rho: float = 1025.0
    g: float = 9.8
    k: float = 80000.0
    D_linear: float = 10000.0
    D_power_law_coeff: float = 10000.0
    D_power_law_exp: float = 0.5

    @property
    def K_h(self) -> float:
        return self.rho * self.g * math.pi * self.r**2


# ── solver ────────────────────────────────────────────────────────────


def solve_coupled_heave(
    params: CoupledHeaveParams,
    mode: DampingMode,
) -> dict[str, NDArray[np.float64]]:
    """Solve the coupled-heave ODE system.

    Args:
        params: Physical parameters.
        mode: Damping mode (linear or power-law).

    Returns:
        dict with keys: t, x_f, v_f, x_o, v_o
    """
    m_f_plus_m_a = params.m_f + params.m_a
    K_h = params.K_h

    def damping(q: float) -> float:
        if mode == DampingMode.LINEAR:
            return float(params.D_linear * q)
        else:
            return float(
                params.D_power_law_coeff * (abs(q) ** params.D_power_law_exp) * q
            )

    def rhs(t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        x_f, v_f, x_o, v_o = y
        dv = v_f - v_o
        d_force = damping(dv)

        dx_f = v_f
        dv_f = (
            params.F * math.cos(params.omega * t)
            - params.B * v_f
            - K_h * x_f
            - params.k * (x_f - x_o)
            - d_force
        ) / m_f_plus_m_a

        dx_o = v_o
        dv_o = (-params.k * (x_o - x_f) + d_force) / params.m_o

        return np.array([dx_f, dv_f, dx_o, dv_o], dtype=np.float64)

    y0 = np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float64)
    t_span = (0.0, OUTPUT_T_END)
    t_eval = np.linspace(0.0, OUTPUT_T_END, OUTPUT_N, dtype=np.float64)

    sol = solve_ivp(  # type: ignore[call-overload]
        rhs,
        t_span,
        y0,
        method=SOLVER_METHOD,
        t_eval=t_eval,
        rtol=SOLVER_RTOL,
        atol=SOLVER_ATOL,
    )

    return {
        "t": sol.t,
        "x_f": sol.y[0],
        "v_f": sol.y[1],
        "x_o": sol.y[2],
        "v_o": sol.y[3],
    }


__all__ = [
    "SOLVER_METHOD",
    "SOLVER_RTOL",
    "SOLVER_ATOL",
    "OUTPUT_DT",
    "OUTPUT_N",
    "OUTPUT_T_END",
    "DampingMode",
    "CoupledHeaveParams",
    "solve_coupled_heave",
]
