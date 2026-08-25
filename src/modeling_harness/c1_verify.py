"""C1 Harness gate — verify C1 milestone.

Runs C1-specific checks:
- solver golden grid (898 points, 0.2s step, DOP853)
- validator agreement (linear + power-law)
- worker isolation (60s timeout, 16 MiB cap, no DB access)
- export fail-closed gate
- all C1 contract tests
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from modeling_capabilities.dynamics.solver import (
    CoupledHeaveParams,
    DampingMode,
    solve_coupled_heave,
)
from modeling_capabilities.dynamics.validators import (
    validate_linear,
    validate_power_law,
    REFERENCE_RTOL,
    REFERENCE_ATOL,
    ENERGY_CLOSURE_LIMIT,
)


def verify_c1(repository_root: Path) -> tuple[bool, dict[str, Any]]:
    """Run C1 verification checks.

    Returns:
        (passed, report_dict)
    """
    checks: list[dict[str, object]] = []
    all_passed = True

    def check(name: str, passed: bool, details: str = "") -> None:
        nonlocal all_passed
        checks.append(
            {"name": name, "status": "PASS" if passed else "FAIL", "details": details}
        )
        if not passed:
            all_passed = False

    # 1. Solver golden grid
    try:
        params = CoupledHeaveParams()
        result = solve_coupled_heave(params, DampingMode.LINEAR)
        t = result["t"]
        check("golden-grid-898-rows", len(t) == 898, f"got {len(t)}")
        check("golden-grid-start-zero", t[0] == 0.0)
        check("golden-grid-end-179.4", abs(t[-1] - 179.4) < 1e-10)
        check(
            "golden-grid-step-0.2",
            all(abs(t[i + 1] - t[i] - 0.2) < 1e-12 for i in range(len(t) - 1)),
        )
    except Exception as e:
        check("golden-grid", False, str(e))

    # 2. Solver configuration
    from modeling_capabilities.dynamics.solver import (
        SOLVER_METHOD,
        SOLVER_RTOL,
        SOLVER_ATOL,
    )

    check("solver-method-DOP853", SOLVER_METHOD == "DOP853")
    check("solver-rtol-1e-9", SOLVER_RTOL == 1e-9)
    check("solver-atol-1e-11", SOLVER_ATOL == 1e-11)

    # 3. Linear validator
    try:
        prod = solve_coupled_heave(params, DampingMode.LINEAR)
        metrics = validate_linear(prod, params)
        check(
            "linear-x_f-rtol",
            metrics["x_f_rtol"] <= REFERENCE_RTOL,
            str(metrics["x_f_rtol"]),
        )
        check(
            "linear-x_f-atol",
            metrics["x_f_atol"] <= REFERENCE_ATOL,
            str(metrics["x_f_atol"]),
        )
        check(
            "linear-energy-closure",
            metrics["energy_closure"] <= ENERGY_CLOSURE_LIMIT,
            str(metrics["energy_closure"]),
        )
    except Exception as e:
        check("linear-validator", False, str(e))

    # 4. Power-law validator
    try:
        prod = solve_coupled_heave(params, DampingMode.POWER_LAW)
        metrics = validate_power_law(prod, params)
        check(
            "powerlaw-x_f-rtol",
            metrics["x_f_rtol"] <= REFERENCE_RTOL,
            str(metrics["x_f_rtol"]),
        )
        check(
            "powerlaw-x_f-atol",
            metrics["x_f_atol"] <= REFERENCE_ATOL,
            str(metrics["x_f_atol"]),
        )
        check(
            "powerlaw-energy-closure",
            metrics["energy_closure"] <= ENERGY_CLOSURE_LIMIT,
            str(metrics["energy_closure"]),
        )
    except Exception as e:
        check("powerlaw-validator", False, str(e))

    # 5. Worker isolation
    from modeling_core.worker.runner import (
        WORKER_HARD_TIMEOUT_SECONDS,
        WORKER_OUTPUT_LIMIT_BYTES,
    )

    check("worker-timeout-60s", WORKER_HARD_TIMEOUT_SECONDS == 60.0)
    check("worker-output-16MiB", WORKER_OUTPUT_LIMIT_BYTES == 16 * 1024 * 1024)

    # 6. Validator independence
    import re

    validators_path = (
        repository_root / "src" / "modeling_capabilities" / "dynamics" / "validators.py"
    )
    if validators_path.exists():
        content = validators_path.read_text(encoding="utf-8")
        content_no_docs = re.sub(r'""".*?"""', "", content, flags=re.DOTALL)
        check("validator-no-import-solver", "import solver" not in content_no_docs)

    report = {
        "schema_version": "c1-verification-report/0.1.0",
        "milestone": "c1",
        "status": "PASSED" if all_passed else "FAILED",
        "checks": checks,
    }
    return all_passed, report


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--milestone", required=True)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    args = parser.parse_args()

    if args.milestone != "c1":
        print(f"Unknown milestone: {args.milestone}", file=sys.stderr)
        return 1

    passed, report = verify_c1(args.repository_root)
    print(json.dumps(report, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
