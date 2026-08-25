"""Independent validators for coupled-heave dynamics.

Linear validator: augmented-state matrix exponential.
Power-law validator: fixed-step RK4 at 0.01 and 0.005 s.

These validators MUST NOT import the production module.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import simpson as simpson_rule
from scipy.linalg import expm

# ── tolerances ────────────────────────────────────────────────────────

REFERENCE_RTOL: float = 2e-4
REFERENCE_ATOL: float = 2e-6
ENERGY_CLOSURE_LIMIT: float = 1e-3


class _Params:
    omega = 1.4005
    m_a = 1335.535
    B = 656.3616
    F = 6250.0
    m_f = 4866.0
    m_o = 2433.0
    r = 1.0
    rho = 1025.0
    g = 9.8
    k = 80000.0
    D_linear = 10000.0
    D_power_law_coeff = 10000.0
    D_power_law_exp = 0.5

    @property
    def K_h(self) -> float:
        return self.rho * self.g * math.pi * self.r**2

    @property
    def M(self) -> float:
        return self.m_f + self.m_a


# ── linear validator ──────────────────────────────────────────────────


def _build_linear_matrix(params: _Params) -> NDArray[np.float64]:
    M = params.M
    K_h = params.K_h
    D = params.D_linear
    k = params.k

    A = np.zeros((4, 4), dtype=np.float64)
    A[0, 1] = 1.0
    A[1, 0] = -(K_h + k) / M
    A[1, 1] = -(params.B + D) / M
    A[1, 2] = k / M
    A[1, 3] = D / M
    A[2, 3] = 1.0
    A[3, 0] = k / params.m_o
    A[3, 1] = D / params.m_o
    A[3, 2] = -k / params.m_o
    A[3, 3] = -D / params.m_o
    return A


def _forcing_vector(t: float, params: _Params) -> NDArray[np.float64]:
    b = np.zeros(4, dtype=np.float64)
    b[1] = params.F * math.cos(params.omega * t) / params.M
    return b


def _solve_linear_reference(
    params: _Params, t_eval: NDArray[np.float64]
) -> dict[str, NDArray[np.float64]]:
    A = _build_linear_matrix(params)
    omega = params.omega
    b = _forcing_vector(0.0, params)

    A_aug = np.zeros((6, 6), dtype=np.float64)
    A_aug[:4, :4] = A
    A_aug[:4, 4] = b
    A_aug[4, 5] = -omega
    A_aug[5, 4] = omega

    n = len(t_eval)
    n_sub = 10

    x_f = np.zeros(n, dtype=np.float64)
    v_f = np.zeros(n, dtype=np.float64)
    x_o = np.zeros(n, dtype=np.float64)
    v_o = np.zeros(n, dtype=np.float64)

    z = np.zeros(6, dtype=np.float64)
    z[4] = 1.0
    z[5] = 0.0

    for i in range(1, n):
        dt_out = t_eval[i] - t_eval[i - 1]
        dt_sub = dt_out / n_sub
        Phi = expm(A_aug * dt_sub)
        for _ in range(n_sub):
            z = Phi @ z

        x_f[i] = z[0]
        v_f[i] = z[1]
        x_o[i] = z[2]
        v_o[i] = z[3]

    return {"t": t_eval, "x_f": x_f, "v_f": v_f, "x_o": x_o, "v_o": v_o}


def validate_linear(
    production: dict[str, NDArray[np.float64]], params: Any
) -> dict[str, float]:
    p = _Params()
    reference = _solve_linear_reference(p, production["t"])

    x_f_ref = reference["x_f"]
    x_f_prod = production["x_f"]
    x_o_ref = reference["x_o"]
    x_o_prod = production["x_o"]

    x_f_abs = np.max(np.abs(x_f_prod - x_f_ref))
    x_f_rel = x_f_abs / max(np.max(np.abs(x_f_ref)), 1e-20)
    x_o_abs = np.max(np.abs(x_o_prod - x_o_ref))
    x_o_rel = x_o_abs / max(np.max(np.abs(x_o_ref)), 1e-20)

    energy = _compute_energy_closure(production, p, power_law=False)

    return {
        "x_f_rtol": float(x_f_rel),
        "x_f_atol": float(x_f_abs),
        "x_o_rtol": float(x_o_rel),
        "x_o_atol": float(x_o_abs),
        "energy_closure": float(energy),
    }


# ── power-law validator ───────────────────────────────────────────────


def _rk4_step(
    y: NDArray[np.float64],
    t: float,
    dt: float,
    params: _Params,
) -> NDArray[np.float64]:
    m_f_plus_m_a = params.M
    K_h = params.K_h
    d_coeff = params.D_power_law_coeff
    d_exp = params.D_power_law_exp

    def rhs(t: float, y: NDArray[np.float64]) -> NDArray[np.float64]:
        x_f, v_f, x_o, v_o = y
        dv = v_f - v_o
        d_force = d_coeff * (abs(dv) ** d_exp) * dv

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

    k1 = rhs(t, y)
    k2 = rhs(t + dt / 2, y + dt / 2 * k1)
    k3 = rhs(t + dt / 2, y + dt / 2 * k2)
    k4 = rhs(t + dt, y + dt * k3)
    return y + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)


def _solve_power_law_rk4(
    params: _Params, t_eval: NDArray[np.float64], dt: float
) -> dict[str, NDArray[np.float64]]:
    n = len(t_eval)
    x_f = np.zeros(n, dtype=np.float64)
    v_f = np.zeros(n, dtype=np.float64)
    x_o = np.zeros(n, dtype=np.float64)
    v_o = np.zeros(n, dtype=np.float64)

    y = np.zeros(4, dtype=np.float64)
    t = 0.0
    idx = 0

    while idx < n:
        if abs(t - t_eval[idx]) < 1e-15 or t > t_eval[idx]:
            x_f[idx] = y[0]
            v_f[idx] = y[1]
            x_o[idx] = y[2]
            v_o[idx] = y[3]
            idx += 1
            if idx >= n:
                break

        step = min(dt, t_eval[idx] - t)
        if step < 1e-16:
            step = dt
        y = _rk4_step(y, t, step, params)
        t += step

    return {"t": t_eval, "x_f": x_f, "v_f": v_f, "x_o": x_o, "v_o": v_o}


def validate_power_law(
    production: dict[str, NDArray[np.float64]], params: Any
) -> dict[str, float]:
    p = _Params()
    t_eval = production["t"]

    reference = _solve_power_law_rk4(p, t_eval, 0.005)

    x_f_ref = reference["x_f"]
    x_f_prod = production["x_f"]
    x_o_ref = reference["x_o"]
    x_o_prod = production["x_o"]

    x_f_abs = np.max(np.abs(x_f_prod - x_f_ref))
    x_f_rel = x_f_abs / max(np.max(np.abs(x_f_ref)), 1e-20)
    x_o_abs = np.max(np.abs(x_o_prod - x_o_ref))
    x_o_rel = x_o_abs / max(np.max(np.abs(x_o_ref)), 1e-20)

    energy = _compute_energy_closure(production, p, power_law=True)

    return {
        "x_f_rtol": float(x_f_rel),
        "x_f_atol": float(x_f_abs),
        "x_o_rtol": float(x_o_rel),
        "x_o_atol": float(x_o_abs),
        "energy_closure": float(energy),
    }


# ── energy balance ────────────────────────────────────────────────────


def _compute_energy_closure(
    data: dict[str, NDArray[np.float64]], params: _Params, *, power_law: bool = False
) -> float:
    t = data["t"]
    x_f = data["x_f"]
    v_f = data["v_f"]
    x_o = data["x_o"]
    v_o = data["v_o"]

    KE = 0.5 * params.M * v_f**2 + 0.5 * params.m_o * v_o**2
    PE_spring = 0.5 * params.k * (x_f - x_o) ** 2
    PE_buoyancy = 0.5 * params.K_h * x_f**2
    E_total = KE + PE_spring + PE_buoyancy

    dE = E_total[-1] - E_total[0]

    F_ext = params.F * np.cos(params.omega * t)
    W_input = simpson_rule(F_ext * v_f, t)

    dv = v_f - v_o
    if power_law:
        W_damp = simpson_rule(
            params.B * v_f**2
            + params.D_power_law_coeff * (np.abs(dv) ** params.D_power_law_exp) * dv**2,
            t,
        )
    else:
        W_damp = simpson_rule(params.B * v_f**2 + params.D_linear * dv**2, t)

    denom = max(abs(dE), abs(W_input), 1e-20)
    closure = abs(dE - W_input + W_damp) / denom

    return float(closure)


__all__ = [
    "REFERENCE_RTOL",
    "REFERENCE_ATOL",
    "ENERGY_CLOSURE_LIMIT",
    "validate_linear",
    "validate_power_law",
]
