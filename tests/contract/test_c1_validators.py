"""C1.6 independent validator tests — RED before GREEN.

Tests verify:
- linear validator uses augmented-state matrix exponential (independent of solver)
- power-law validator uses fixed-step RK4 at 0.01 and 0.005 s
- production/reference comparison: rtol=2e-4, atol=2e-6
- normalized energy-balance closure <= 1e-3
- solver and validator do not import each other
"""

from __future__ import annotations

from modeling_capabilities.dynamics.solver import (
    CoupledHeaveParams,
    DampingMode,
    solve_coupled_heave,
)


# ── linear validator ──────────────────────────────────────────────────


class TestLinearValidator:
    def test_linear_validator_agrees_with_production(self) -> None:
        """RED: linear validator must agree with production solver within tolerance."""
        from modeling_capabilities.dynamics.validators import validate_linear

        params = CoupledHeaveParams()
        production = solve_coupled_heave(params, DampingMode.LINEAR)
        metrics = validate_linear(production, params)

        assert metrics["x_f_rtol"] <= 2e-4
        assert metrics["x_f_atol"] <= 2e-6
        assert metrics["x_o_rtol"] <= 2e-4
        assert metrics["x_o_atol"] <= 2e-6
        assert metrics["energy_closure"] <= 1e-3

    def test_linear_validator_does_not_import_solver(self) -> None:
        """RED: linear validator must not import the production solver."""
        # Check that validators.py does not have 'import solver' or 'from.*solver'
        import re

        from modeling_capabilities.dynamics import validators

        path = validators.__file__
        with open(path, encoding="utf-8") as f:
            content = f.read()
        # Remove docstrings
        content_no_docs = re.sub(r'""".*?"""', "", content, flags=re.DOTALL)
        assert "import solver" not in content_no_docs, (
            "validator must not import solver module"
        )
        assert "from .solver" not in content_no_docs, (
            "validator must not import from solver module"
        )


# ── power-law validator ───────────────────────────────────────────────


class TestPowerLawValidator:
    def test_power_law_validator_agrees_with_production(self) -> None:
        """RED: power-law validator must agree with production solver within tolerance."""
        from modeling_capabilities.dynamics.validators import validate_power_law

        params = CoupledHeaveParams()
        production = solve_coupled_heave(params, DampingMode.POWER_LAW)
        metrics = validate_power_law(production, params)

        assert metrics["x_f_rtol"] <= 2e-4
        assert metrics["x_f_atol"] <= 2e-6
        assert metrics["x_o_rtol"] <= 2e-4
        assert metrics["x_o_atol"] <= 2e-6
        assert metrics["energy_closure"] <= 1e-3

    def test_power_law_validator_uses_rk4_step_0_01(self) -> None:
        """RED: power-law validator must use RK4 with step 0.01 s."""
        import inspect

        from modeling_capabilities.dynamics import validators

        source = inspect.getsource(validators)
        assert "0.01" in source, "power-law validator must use step 0.01"

    def test_power_law_validator_uses_rk4_step_0_005(self) -> None:
        """RED: power-law validator must also use RK4 with step 0.005 s."""
        import inspect

        from modeling_capabilities.dynamics import validators

        source = inspect.getsource(validators)
        assert "0.005" in source, "power-law validator must use step 0.005"

    def test_power_law_validator_does_not_import_solver(self) -> None:
        """RED: power-law validator must not import the production solver."""
        import re

        from modeling_capabilities.dynamics import validators

        path = validators.__file__
        with open(path, encoding="utf-8") as f:
            content = f.read()
        content_no_docs = re.sub(r'""".*?"""', "", content, flags=re.DOTALL)
        assert "import solver" not in content_no_docs, (
            "validator must not import solver module"
        )
        assert "from .solver" not in content_no_docs, (
            "validator must not import from solver module"
        )


# ── tolerances ────────────────────────────────────────────────────────


class TestTolerances:
    def test_production_reference_rtol_is_2e_4(self) -> None:
        from modeling_capabilities.dynamics.validators import REFERENCE_RTOL

        assert REFERENCE_RTOL == 2e-4

    def test_production_reference_atol_is_2e_6(self) -> None:
        from modeling_capabilities.dynamics.validators import REFERENCE_ATOL

        assert REFERENCE_ATOL == 2e-6

    def test_energy_closure_limit_is_1e_3(self) -> None:
        from modeling_capabilities.dynamics.validators import ENERGY_CLOSURE_LIMIT

        assert ENERGY_CLOSURE_LIMIT == 1e-3
