"""C1.5 coupled-heave production solver tests — RED before GREEN.

Tests verify:
- golden grid: exactly 898 rows at t_i=0.2*i, ending at 179.4
- linear damping case produces finite results
- power-law damping case produces finite results
- DOP853 solver with rtol=1e-9, atol=1e-11
- zero initial conditions (equilibrium)
"""

from __future__ import annotations

import numpy as np

# ── golden grid ───────────────────────────────────────────────────────


class TestGoldenGrid:
    def test_output_has_898_rows(self) -> None:
        """RED: output grid must have exactly 898 rows (t=0 to t=179.4 at 0.2 step)."""
        from modeling_capabilities.dynamics.solver import (
            solve_coupled_heave,
            CoupledHeaveParams,
            DampingMode,
        )

        params = CoupledHeaveParams()
        result = solve_coupled_heave(params, DampingMode.LINEAR)
        t = result["t"]
        assert len(t) == 898, f"expected 898 rows, got {len(t)}"

    def test_time_grid_starts_at_zero(self) -> None:
        """RED: first time point must be exactly 0.0."""
        from modeling_capabilities.dynamics.solver import (
            solve_coupled_heave,
            CoupledHeaveParams,
            DampingMode,
        )

        params = CoupledHeaveParams()
        result = solve_coupled_heave(params, DampingMode.LINEAR)
        t = result["t"]
        assert t[0] == 0.0

    def test_time_grid_ends_at_179_4(self) -> None:
        """RED: last time point must be exactly 179.4."""
        from modeling_capabilities.dynamics.solver import (
            solve_coupled_heave,
            CoupledHeaveParams,
            DampingMode,
        )

        params = CoupledHeaveParams()
        result = solve_coupled_heave(params, DampingMode.LINEAR)
        t = result["t"]
        assert t[-1] == 179.4

    def test_time_step_is_exactly_0_2(self) -> None:
        """RED: time step must be exactly 0.2 seconds."""
        from modeling_capabilities.dynamics.solver import (
            solve_coupled_heave,
            CoupledHeaveParams,
            DampingMode,
        )

        params = CoupledHeaveParams()
        result = solve_coupled_heave(params, DampingMode.LINEAR)
        t = result["t"]
        diffs = np.diff(t)
        assert np.allclose(diffs, 0.2, atol=1e-15), f"step not 0.2: {diffs[:5]}"


# ── linear damping ─────────────────────────────────────────────────────


class TestLinearDamping:
    def test_linear_damping_produces_finite_results(self) -> None:
        """RED: linear damping case must produce finite results for all variables."""
        from modeling_capabilities.dynamics.solver import (
            solve_coupled_heave,
            CoupledHeaveParams,
            DampingMode,
        )

        params = CoupledHeaveParams()
        result = solve_coupled_heave(params, DampingMode.LINEAR)
        for key in ["x_f", "v_f", "x_o", "v_o"]:
            assert np.all(np.isfinite(result[key])), f"{key} contains non-finite values"

    def test_linear_damping_initial_conditions_are_zero(self) -> None:
        """RED: initial conditions must be zero (equilibrium)."""
        from modeling_capabilities.dynamics.solver import (
            solve_coupled_heave,
            CoupledHeaveParams,
            DampingMode,
        )

        params = CoupledHeaveParams()
        result = solve_coupled_heave(params, DampingMode.LINEAR)
        assert result["x_f"][0] == 0.0
        assert result["v_f"][0] == 0.0
        assert result["x_o"][0] == 0.0
        assert result["v_o"][0] == 0.0


# ── power-law damping ──────────────────────────────────────────────────


class TestPowerLawDamping:
    def test_power_law_damping_produces_finite_results(self) -> None:
        """RED: power-law damping case must produce finite results for all variables."""
        from modeling_capabilities.dynamics.solver import (
            solve_coupled_heave,
            CoupledHeaveParams,
            DampingMode,
        )

        params = CoupledHeaveParams()
        result = solve_coupled_heave(params, DampingMode.POWER_LAW)
        for key in ["x_f", "v_f", "x_o", "v_o"]:
            assert np.all(np.isfinite(result[key])), f"{key} contains non-finite values"

    def test_power_law_damping_initial_conditions_are_zero(self) -> None:
        """RED: initial conditions must be zero (equilibrium)."""
        from modeling_capabilities.dynamics.solver import (
            solve_coupled_heave,
            CoupledHeaveParams,
            DampingMode,
        )

        params = CoupledHeaveParams()
        result = solve_coupled_heave(params, DampingMode.POWER_LAW)
        assert result["x_f"][0] == 0.0
        assert result["v_f"][0] == 0.0
        assert result["x_o"][0] == 0.0
        assert result["v_o"][0] == 0.0


# ── solver configuration ───────────────────────────────────────────────


class TestSolverConfig:
    def test_solver_uses_dop853(self) -> None:
        """RED: production solver must use DOP853 method."""
        from modeling_capabilities.dynamics.solver import SOLVER_METHOD

        assert SOLVER_METHOD == "DOP853"

    def test_solver_uses_rtol_1e_9(self) -> None:
        """RED: production solver must use rtol=1e-9."""
        from modeling_capabilities.dynamics.solver import SOLVER_RTOL

        assert SOLVER_RTOL == 1e-9

    def test_solver_uses_atol_1e_11(self) -> None:
        """RED: production solver must use atol=1e-11."""
        from modeling_capabilities.dynamics.solver import SOLVER_ATOL

        assert SOLVER_ATOL == 1e-11


# ── parameter values ───────────────────────────────────────────────────


class TestParameterValues:
    def test_parameters_match_design(self) -> None:
        """RED: parameters must match the approved design values."""
        from modeling_capabilities.dynamics.solver import CoupledHeaveParams

        params = CoupledHeaveParams()
        assert params.omega == 1.4005
        assert params.m_a == 1335.535
        assert params.B == 656.3616
        assert params.F == 6250
        assert params.m_f == 4866
        assert params.m_o == 2433
        assert params.r == 1
        assert params.rho == 1025
        assert params.g == 9.8
        assert params.k == 80000
        assert params.D_linear == 10000
        assert params.D_power_law_coeff == 10000
        assert params.D_power_law_exp == 0.5
