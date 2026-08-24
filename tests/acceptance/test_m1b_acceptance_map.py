from __future__ import annotations

import re
from pathlib import Path

from modeling_harness import verify as verification
from modeling_harness.evidence import (
    M1B_ACCEPTANCE_MAP_SCHEMA_VERSION,
    M1B_VERIFICATION_REPORT_SCHEMA_VERSION,
    validate_m1b_acceptance_policy,
)


ROOT = Path(__file__).parents[2]
EXPECTED_EXTRA_CHECKS = (
    "stable-schema-corpus",
    "canonical-json-conformance",
    "artifact-store-sqlite-v2",
    "artifact-workflow",
    "recovery-rerun",
    "fault-windows",
    "m1b-security",
    "affine-math",
    "restart-reproducibility",
    "echo-scaffold",
    "context-boundaries",
    "stable-documents",
    "stdio-restart",
    "m1b-acceptance",
    "package-assets",
)


def test_m1b_profile_is_an_ordered_strict_superset_without_redefining_m1a() -> None:
    assert verification.M1A_CHECK_IDS == verification._M1A_CHECK_IDS
    assert verification.M1B_CHECK_IDS == verification._M1B_CHECK_IDS
    assert verification.M1B_CHECK_IDS == (
        *verification.M1A_CHECK_IDS,
        *EXPECTED_EXTRA_CHECKS,
    )
    assert set(verification.M1A_CHECK_IDS) < set(verification.M1B_CHECK_IDS)

    uv = (
        ROOT
        / ".venv"
        / ("Scripts/uv.exe" if (ROOT / ".venv/Scripts").is_dir() else "bin/uv")
    )
    internal = ROOT / "build" / "test-m1b-profile"
    m1a = verification._build_check_specs(uv, internal)
    m1b = verification._build_m1b_check_specs(uv, internal)
    assert m1b[: len(m1a)] == m1a
    assert tuple(spec.check_id for spec in m1b) == verification.M1B_CHECK_IDS
    assert all("shell" not in spec.argv for spec in m1b)


def test_m1b_acceptance_policy_maps_exactly_a01_through_b10_to_real_tests() -> None:
    requirements = verification._M1B_ACCEPTANCE_REQUIREMENTS
    identifiers = tuple(item.acceptance_id for item in requirements)
    assert identifiers == tuple(
        f"{prefix}-{number:02d}" for prefix in ("A", "B") for number in range(1, 11)
    )
    assert requirements[:10] == verification._M1A_ACCEPTANCE_REQUIREMENTS
    validate_m1b_acceptance_policy(
        requirements=requirements,
        allowed_check_ids=verification.M1B_CHECK_IDS,
    )
    for requirement in requirements:
        for clause in requirement.clauses:
            for node in clause.required_nodes:
                test_path = node.selector.split("::", 1)[0]
                assert (ROOT / test_path).is_file(), node.selector
                assert "*" not in node.selector


def test_m1b_report_versions_are_distinct_from_preview_evidence() -> None:
    assert M1B_ACCEPTANCE_MAP_SCHEMA_VERSION == "m1b-acceptance-map/1.0.0"
    assert M1B_VERIFICATION_REPORT_SCHEMA_VERSION == "m1b-verification-report/1.0.0"


def test_workflow_runs_one_identical_m1b_command_on_two_os_families() -> None:
    workflow = (ROOT / ".github/workflows/verify.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "fail-fast: false" in workflow
    matrix = re.search(r"os:\s*\[([^]]+)\]", workflow)
    assert matrix is not None
    assert {item.strip() for item in matrix.group(1).split(",")} == {
        "windows-latest",
        "ubuntu-latest",
    }
    command = "uv run --locked --no-sync modeling verify --milestone m1b"
    assert workflow.count(command) == 1
    assert "if: runner.os" not in workflow
    for baseline in (
        "actions/checkout@v6",
        "astral-sh/setup-uv@11f9893b081a58869d3b5fccaea48c9e9e46f990",
        'version: "0.11.28"',
        'python-version: "3.11"',
        "actions/upload-artifact@v7",
    ):
        assert baseline in workflow
