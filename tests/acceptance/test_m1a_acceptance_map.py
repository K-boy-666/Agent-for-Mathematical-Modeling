from __future__ import annotations

import json
import re
import tomllib
from importlib.resources import files
from pathlib import Path

import pytest

from modeling_core.contracts.schema_catalog import SchemaCatalog
from modeling_core.contracts.tools import TOOL_NAMES
from modeling_harness import verify as verification
from modeling_harness.evidence import (
    ACCEPTANCE_MAP_SCHEMA_VERSION,
    AcceptanceClause,
    AcceptanceRequirement,
    EvidenceReference,
    EvidenceValidationError,
    RequiredTestNode,
    materialize_m1a_acceptance_map,
    validate_m1a_acceptance_policy,
    validate_m1a_acceptance_report,
)


REPOSITORY = Path(__file__).parents[2]
CONTEXT_FILES = {
    "AGENTS.md",
    "README.md",
    "docs/architecture/overview.md",
    "docs/context/index.md",
    "docs/contracts/capability-api-v0.md",
    "docs/contracts/mcp-tools-v0.md",
    "docs/contracts/root-finding-v0.md",
    "docs/operations/bootstrap-and-doctor.md",
    "docs/product/m1-scope.md",
    "docs/templates/codex/config.toml",
    "src/modeling_capabilities/AGENTS.md",
    "src/modeling_core/AGENTS.md",
    "src/modeling_mcp/AGENTS.md",
    "tests/AGENTS.md",
}
NESTED_RULES = {
    "src/modeling_core/AGENTS.md": "modeling_core",
    "src/modeling_capabilities/AGENTS.md": "modeling_capabilities",
    "src/modeling_mcp/AGENTS.md": "modeling_mcp",
    "tests/AGENTS.md": "tests",
}


def _text(relative_path: str) -> str:
    return (REPOSITORY / relative_path).read_text(encoding="utf-8")


def _assert_local_links_resolve(relative_path: str) -> None:
    document = REPOSITORY / relative_path
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", document.read_text("utf-8")):
        target = target.split("#", 1)[0]
        if not target or "://" in target:
            continue
        assert (document.parent / target).resolve().exists(), (relative_path, target)


def test_m1a_context_config_and_acceptance_map_are_complete() -> None:
    """Catches a missing M1a route, task heading, or trusted Codex setting."""
    assert all((REPOSITORY / path).is_file() for path in CONTEXT_FILES)
    for path in sorted(CONTEXT_FILES):
        if path.endswith(".md"):
            _assert_local_links_resolve(path)

    plan = _text("docs/superpowers/plans/2026-07-17-math-modeling-mcp-m1.md")
    assert len(re.findall(r"^### Task M1a-0:", plan, re.MULTILINE)) == 1
    assert re.findall(r"^### Task A(\d+):", plan, re.MULTILINE) == [
        str(index) for index in range(1, 13)
    ]

    config = tomllib.loads(_text("docs/templates/codex/config.toml"))
    assert config == {
        "mcp_servers": {
            "modeling": {
                "command": "uv",
                "args": [
                    "run",
                    "--locked",
                    "--no-sync",
                    "modeling-mcp",
                    "--project-root",
                    ".",
                ],
                "cwd": ".",
                "required": True,
                "startup_timeout_sec": 10,
                "tool_timeout_sec": 65,
                "enabled_tools": list(TOOL_NAMES),
            }
        }
    }

    readme = _text("README.md")
    assert readme.count("spikes/m1a_0/README.md") == 1
    assert "stable hash smoke only" in readme
    assert "trusted project" in readme


def test_m1a_abstraction_budget_and_exact_context_inventory_are_binding() -> None:
    """Catches scope prose growing a new abstraction or duplicating contracts."""
    found = {
        path.relative_to(REPOSITORY).as_posix()
        for directory in (
            "context",
            "product",
            "architecture",
            "contracts",
            "operations",
        )
        for path in (REPOSITORY / "docs" / directory).rglob("*.md")
    }
    assert found == {
        path
        for path in CONTEXT_FILES
        if path.startswith("docs/") and path.endswith(".md")
    }
    assert {
        path.relative_to(REPOSITORY).as_posix()
        for path in REPOSITORY.rglob("AGENTS.md")
        if ".venv" not in path.parts
    } == {"AGENTS.md", *NESTED_RULES}

    root_rules = _text("AGENTS.md")
    assert 100 <= len(root_rules.splitlines()) <= 150
    for required in (
        "ApplicationFacade",
        "ProjectStore",
        "Built-in Capability",
        "Test result",
        "Git diff summary",
        "Commit hash",
        "uv run --locked --no-sync modeling verify --milestone m1a",
    ):
        assert required in root_rules
    for path, scope in NESTED_RULES.items():
        nested = _text(path)
        assert scope in nested
        assert "本文件只补充根规则" in nested

    architecture = _text("docs/architecture/overview.md")
    for abstraction in (
        "ApplicationFacade",
        "ProjectStore",
        "Clock",
        "IdGenerator",
        "BuiltInCapability",
        "CapabilityValidator",
    ):
        assert abstraction in architecture
    for forbidden in (
        "ExecutionBackend",
        "通用事件发布器",
        "动态插件发现器",
        "服务定位器",
        "任务队列",
        "worker 池",
    ):
        assert forbidden in architecture

    contract_routes = "\n".join(
        _text(path)
        for path in (
            "docs/contracts/mcp-tools-v0.md",
            "docs/contracts/capability-api-v0.md",
            "docs/contracts/root-finding-v0.md",
        )
    )
    assert "```json" not in contract_routes
    assert "src/modeling_core/contracts/schemas/tools/0.1.0/" in contract_routes
    assert "src/modeling_core/contracts/schemas/common/0.1.0/" in contract_routes
    assert "src/modeling_capabilities/root_finding/schemas/0.1.0/" in contract_routes
    assert "src/modeling_capabilities/root_finding/context.md" in contract_routes


def test_a12_runtime_and_nested_context_assets_are_installed_offline_without_core_catalog_drift() -> (
    None
):
    """Catches package-data loss or context work mutating the 0.1 tool catalog."""
    for package in ("modeling_core", "modeling_capabilities", "modeling_mcp"):
        installed = files(package).joinpath("AGENTS.md").read_bytes()
        assert installed == (REPOSITORY / "src" / package / "AGENTS.md").read_bytes()

    installed_config = (
        files("modeling_cli").joinpath("templates", "codex", "config.toml").read_bytes()
    )
    assert (
        installed_config
        == (REPOSITORY / "docs/templates/codex/config.toml").read_bytes()
    )

    catalog = SchemaCatalog.load_packaged("0.1.0")
    assert len(catalog.tool_schemas) == 30
    assert catalog.fingerprint == (
        "sha256:927a26b40a1cf0747a3f79d8ebb44f085cd7bf404ae22c7f957137a0d652bc73"
    )


CHECK_ORDER = (
    "uv-lock",
    "ruff-check",
    "ruff-format",
    "mypy",
    "pytest-unit",
    "pytest-contract",
    "pytest-math",
    "pytest-architecture",
    "pytest-integration",
    "pytest-reproducibility",
    "pytest-security",
    "pytest-smoke",
    "pytest-acceptance",
    "wheel",
    "stdio-golden",
)
PYTEST_CHECKS = frozenset(
    {
        "pytest-unit",
        "pytest-contract",
        "pytest-math",
        "pytest-architecture",
        "pytest-integration",
        "pytest-reproducibility",
        "pytest-security",
        "pytest-smoke",
        "pytest-acceptance",
        "stdio-golden",
    }
)
GOLDEN_CHAIN = (
    "tests/integration/test_stdio_golden_m1a.py::"
    "test_official_client_completes_m1a_golden_chain_records_protocol_purity_"
    "and_closes_child"
)
# A-01..A-10 literal clause-complete node policy from A12 resolution 4.3:
# acceptance_id -> ((check_id, selector, match), ...) with one clause each.
EXPECTED_POLICY: dict[str, tuple[tuple[str, str, str], ...]] = {
    "A-01": (
        (
            "pytest-acceptance",
            "tests/acceptance/test_m1a_acceptance_map.py::"
            "test_a01_windows_locked_toolchain_is_current_and_offline",
            "exact",
        ),
        (
            "pytest-integration",
            "tests/integration/test_bootstrap_sqlite.py::"
            "test_uninitialized_bootstrap_creates_exact_storage_ready_layout",
            "exact",
        ),
        (
            "pytest-integration",
            "tests/integration/test_bootstrap_sqlite.py::"
            "test_repeat_bootstrap_returns_same_id_without_changing_any_bytes",
            "exact",
        ),
        (
            "pytest-unit",
            "tests/unit/test_doctor.py::"
            "test_uninitialized_is_warning_and_storage_ready_and_ready_are_ready",
            "exact",
        ),
    ),
    "A-02": (
        ("stdio-golden", GOLDEN_CHAIN, "exact"),
        (
            "pytest-integration",
            "tests/integration/test_stdio_golden_m1a.py::"
            "test_official_client_exception_path_closes_child_and_releases_"
            "writer_lease",
            "exact",
        ),
    ),
    "A-03": (
        ("stdio-golden", GOLDEN_CHAIN, "exact"),
        (
            "pytest-integration",
            "tests/integration/test_application_workflow.py::"
            "test_six_use_cases_reconstruct_a_validated_root_finding_trace",
            "exact",
        ),
        (
            "pytest-unit",
            "tests/unit/test_doctor.py::"
            "test_doctor_uses_shared_facade_and_store_without_starting_"
            "inspected_composition",
            "exact",
        ),
        (
            "pytest-architecture",
            "tests/architecture/test_dependency_boundaries.py::"
            "test_core_never_imports_adapters_databases_or_capabilities",
            "exact",
        ),
    ),
    "A-04": (
        (
            "pytest-unit",
            "tests/unit/test_registry.py::"
            "test_capability_and_compatible_validator_register_before_seal",
            "exact",
        ),
        (
            "pytest-architecture",
            "tests/architecture/test_composition_root.py::"
            "test_composition_seals_the_exact_builtin_registry_and_sole_store",
            "exact",
        ),
    ),
    "A-05": (
        ("stdio-golden", GOLDEN_CHAIN, "exact"),
        (
            "pytest-unit",
            "tests/unit/root_finding/test_validator.py::"
            "test_golden_success_is_passed_with_exact_metrics_and_hashes",
            "exact",
        ),
    ),
    "A-06": (
        (
            "pytest-integration",
            "tests/integration/test_application_workflow.py::"
            "test_numerical_failure_is_durable_and_replayable",
            "exact",
        ),
        (
            "pytest-integration",
            "tests/integration/test_application_workflow.py::"
            "test_pre_execution_rejections_leave_zero_provenance",
            "family",
        ),
        (
            "pytest-unit",
            "tests/unit/expression/test_canonicalization.py::"
            "test_forbidden_expressions_map_to_security_violation",
            "family",
        ),
    ),
    "A-07": (
        (
            "pytest-unit",
            "tests/unit/root_finding/test_validator.py::"
            "test_self_consistent_forged_result_hash_still_fails_mathematically",
            "exact",
        ),
        (
            "pytest-architecture",
            "tests/architecture/test_solver_validator_independence.py::"
            "test_validator_real_import_graph_has_only_explicitly_allowed_modules",
            "exact",
        ),
    ),
    "A-08": (
        (
            "pytest-integration",
            "tests/integration/test_application_workflow.py::"
            "test_six_use_cases_reconstruct_a_validated_root_finding_trace",
            "exact",
        ),
        (
            "pytest-contract",
            "tests/contract/test_project_store.py::"
            "test_trace_query_and_trace_enforce_all_parent_and_uniqueness_relations",
            "exact",
        ),
    ),
    "A-09": (
        (
            "pytest-integration",
            "tests/integration/test_application_workflow.py::"
            "test_completed_write_replay_is_side_effect_free",
            "exact",
        ),
        (
            "pytest-integration",
            "tests/integration/test_application_workflow.py::"
            "test_write_idempotency_mismatch_fails_without_new_entities",
            "exact",
        ),
        (
            "pytest-unit",
            "tests/unit/expression/test_canonicalization.py::"
            "test_forbidden_expressions_map_to_security_violation",
            "family",
        ),
        (
            "pytest-security",
            "tests/security/test_m1a_boundaries.py::"
            "test_request_larger_than_one_mib_is_rejected_before_newline",
            "exact",
        ),
        (
            "pytest-security",
            "tests/security/test_m1a_boundaries.py::"
            "test_cooperative_deadline_rejects_work_at_the_exact_boundary",
            "exact",
        ),
        (
            "pytest-security",
            "tests/security/test_m1a_boundaries.py::"
            "test_project_lock_is_exclusive_and_reusable_after_release",
            "exact",
        ),
        (
            "pytest-security",
            "tests/security/test_m1a_boundaries.py::"
            "test_public_mcp_contract_rejects_every_untrusted_path_surface",
            "family",
        ),
    ),
    "A-10": (
        (
            "pytest-acceptance",
            "tests/acceptance/test_m1a_acceptance_map.py::"
            "test_m1a_context_config_and_acceptance_map_are_complete",
            "exact",
        ),
        (
            "pytest-acceptance",
            "tests/acceptance/test_m1a_acceptance_map.py::"
            "test_m1a_abstraction_budget_and_exact_context_inventory_are_binding",
            "exact",
        ),
        (
            "pytest-acceptance",
            "tests/acceptance/test_m1a_acceptance_map.py::"
            "test_a12_runtime_and_nested_context_assets_are_installed_offline_"
            "without_core_catalog_drift",
            "exact",
        ),
        (
            "pytest-reproducibility",
            "tests/reproducibility/test_m1a_repeatability.py::"
            "test_a12_profile_and_report_transition_preserve_a11_evidence_"
            "contract",
            "exact",
        ),
    ),
}
FAMILY_PARAMS = ("[case-alpha]", "[case-beta]")
_ACCEPTANCE_IDS = tuple(EXPECTED_POLICY)
# Owning checks per A12 resolution 4.3, including uv-lock and wheel which own
# no literal node; UTF-8 sorted.
EXPECTED_CHECKS: dict[str, tuple[str, ...]] = {
    "A-01": ("pytest-acceptance", "pytest-integration", "pytest-unit", "uv-lock"),
    "A-02": ("pytest-integration", "stdio-golden"),
    "A-03": (
        "pytest-architecture",
        "pytest-integration",
        "pytest-unit",
        "stdio-golden",
    ),
    "A-04": ("pytest-architecture", "pytest-unit"),
    "A-05": ("pytest-unit", "stdio-golden"),
    "A-06": ("pytest-integration", "pytest-unit"),
    "A-07": ("pytest-architecture", "pytest-unit"),
    "A-08": ("pytest-contract", "pytest-integration"),
    "A-09": ("pytest-integration", "pytest-security", "pytest-unit"),
    "A-10": ("pytest-acceptance", "pytest-reproducibility", "wheel"),
}
# Success evidence targets the first owning check in the fixed check order.
EVIDENCE_POINTER: dict[str, str] = {
    "A-01": "/checks/0/status",
    "A-02": "/checks/8/status",
    "A-03": "/checks/4/status",
    "A-04": "/checks/4/status",
    "A-05": "/checks/4/status",
    "A-06": "/checks/4/status",
    "A-07": "/checks/4/status",
    "A-08": "/checks/5/status",
    "A-09": "/checks/4/status",
    "A-10": "/checks/9/status",
}


def _expected_requirement(acceptance_id: str) -> AcceptanceRequirement:
    entries = EXPECTED_POLICY[acceptance_id]
    nodes = tuple(
        RequiredTestNode(selector=selector, match=match)  # type: ignore[arg-type]
        for _, selector, match in sorted(
            entries, key=lambda item: item[1].encode("utf-8")
        )
    )
    evidence = (
        EvidenceReference(
            artifact="verification-report.json",
            json_pointer=EVIDENCE_POINTER[acceptance_id],
        ),
    )
    return AcceptanceRequirement(
        acceptance_id=acceptance_id,  # type: ignore[arg-type]
        clauses=(
            AcceptanceClause(
                clause_id=f"{acceptance_id}-1",
                required_nodes=nodes,
                check_ids=EXPECTED_CHECKS[acceptance_id],
                success_evidence=evidence,
            ),
        ),
    )


def _expected_policy() -> tuple[AcceptanceRequirement, ...]:
    return tuple(_expected_requirement(aid) for aid in _ACCEPTANCE_IDS)


def _observed_outcomes(
    *,
    overrides: dict[str, dict[str, str]] | None = None,
) -> dict[str, dict[str, str]]:
    outcomes: dict[str, dict[str, str]] = {check: {} for check in PYTEST_CHECKS}
    for requirement in verification._M1A_ACCEPTANCE_REQUIREMENTS:
        for clause in requirement.clauses:
            for node in clause.required_nodes:
                owner = next(
                    check
                    for check, selector, _ in EXPECTED_POLICY[requirement.acceptance_id]
                    if selector == node.selector
                )
                members = [node.selector]
                if node.match == "family":
                    members.extend(node.selector + param for param in FAMILY_PARAMS)
                for member in members:
                    outcomes[owner][member] = "PASSED"
    # Decoys: unrelated passing nodes and a prefix-only non-member of A-06 family.
    outcomes["pytest-unit"]["tests/unit/test_registry.py::test_unrelated"] = "PASSED"
    outcomes["pytest-unit"][
        "tests/unit/expression/test_canonicalization.py::"
        "test_forbidden_expressions_map_to_security_violation_extra"
    ] = "PASSED"
    for check, nodes in (overrides or {}).items():
        outcomes[check].update(nodes)
    return outcomes


def _base_report(
    outcomes: dict[str, dict[str, str]],
    *,
    status: str = "PASSED",
    fingerprint: str = "sha256:" + "a" * 64,
    check_statuses: dict[str, str] | None = None,
    extra_test_nodes: dict[str, tuple[str, ...]] | None = None,
) -> dict[str, object]:
    checks: list[dict[str, object]] = []
    for check_id in CHECK_ORDER:
        nodes = sorted(outcomes.get(check_id, {}), key=lambda v: v.encode("utf-8"))
        if extra_test_nodes and check_id in extra_test_nodes:
            nodes = sorted(
                set(nodes) | set(extra_test_nodes[check_id]),
                key=lambda v: v.encode("utf-8"),
            )
        checks.append(
            {
                "check_id": check_id,
                "status": (check_statuses or {}).get(check_id, "PASS"),
                "duration_ms": 1,
                "exit_code": 0,
                "test_counts": (
                    {
                        "total": len(nodes),
                        "passed": len(nodes),
                        "failed": 0,
                        "errors": 0,
                        "skipped": 0,
                    }
                    if check_id in PYTEST_CHECKS
                    else None
                ),
                "test_nodes": nodes if check_id in PYTEST_CHECKS else None,
                "diagnostic_code": None,
            }
        )
    return {
        "schema_version": "m1a-verification-report/0.2.0",
        "milestone": "m1a",
        "status": status,
        "source_fingerprint": fingerprint,
        "required_skips": 0,
        "environment": {},
        "checks": checks,
        "artifacts": {
            "source_inventory": "source-inventory.json",
            "package_assets": "package-assets.json",
            "architecture_report": "architecture-report.json",
            "stdio_transcript": "stdio-transcript.json",
            "golden_trace": "golden-trace.json",
        },
        "golden_ids": {},
        "incomplete_groups": [],
    }


def _artifact_documents(
    base_report: dict[str, object],
    *,
    golden_failed: bool = False,
) -> dict[str, object]:
    if golden_failed:
        transcript = {
            "schema_version": "m1a-stdio-transcript-failure/0.1.0",
            "status": "UNAVAILABLE",
            "diagnostic_code": "golden-check-failed",
            "events": [],
        }
        trace = {
            "schema_version": "m1a-golden-trace-failure/0.1.0",
            "status": "UNAVAILABLE",
            "diagnostic_code": "golden-check-failed",
        }
    else:
        transcript = {
            "schema_version": "m1a-stdio-transcript/0.1.0",
            "events": [],
        }
        trace = {
            "schema_version": "m1a-golden-trace/0.1.0",
            "project_id": "00000000-0000-4000-8000-000000000001",
            "experiment_id": "00000000-0000-4000-8000-000000000002",
            "attempt_id": "00000000-0000-4000-8000-000000000003",
            "validation_id": "00000000-0000-4000-8000-000000000004",
        }
    return {
        "verification-report.json": base_report,
        "architecture-report.json": {
            "schema_version": "m1a-architecture-report/0.1.0",
            "status": "PASS",
            "check_id": "pytest-architecture",
            "test_counts": None,
        },
        "source-inventory.json": [{"path": "uv.lock", "sha256": "sha256:" + "b" * 64}],
        "package-assets.json": [
            {"path": "modeling_core/AGENTS.md", "sha256": "sha256:" + "c" * 64}
        ],
        "stdio-transcript.json": transcript,
        "golden-trace.json": trace,
    }


def test_committed_policy_is_the_clause_complete_literal_node_policy() -> None:
    """Catches a regenerated, wildcard, or reordered acceptance policy."""
    policy = verification._M1A_ACCEPTANCE_REQUIREMENTS
    assert policy == _expected_policy()
    assert verification._M1A_CHECK_IDS == CHECK_ORDER
    validate_m1a_acceptance_policy(requirements=policy, allowed_check_ids=CHECK_ORDER)


def test_a01_windows_locked_toolchain_is_current_and_offline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Catches pinned-uv drift between the lock file and the harness."""
    configuration = tomllib.loads(_text("pyproject.toml"))
    required = configuration["tool"]["uv"]["required-version"]
    assert required == "==0.11.28"
    assert verification._UV_VERSION == "0.11.28"
    monkeypatch.setenv("A12_SENTINEL", "preserved")
    environment = verification._offline_environment()
    assert environment["UV_OFFLINE"] == "1"
    assert environment["A12_SENTINEL"] == "preserved"


def test_acceptance_policy_mutations_reject_each_a_clause() -> None:
    """Catches structural policy drift passing Phase 1 as a prerequisite."""
    committed = verification._M1A_ACCEPTANCE_REQUIREMENTS
    for index in range(len(committed)):
        truncated = committed[:index] + committed[index + 1 :]
        with pytest.raises(EvidenceValidationError):
            validate_m1a_acceptance_policy(
                requirements=truncated, allowed_check_ids=CHECK_ORDER
            )
    validate_m1a_acceptance_policy(
        requirements=committed, allowed_check_ids=CHECK_ORDER
    )


def _minimal_policy(
    *,
    a01_clause: AcceptanceClause | None = None,
) -> tuple[AcceptanceRequirement, ...]:
    requirements: list[AcceptanceRequirement] = []
    for position, acceptance_id in enumerate(_ACCEPTANCE_IDS):
        if position == 0 and a01_clause is not None:
            clause = a01_clause
        else:
            selector = f"tests/synthetic/test_{position}.py::test_case"
            clause = AcceptanceClause(
                clause_id=f"{acceptance_id}-1",
                required_nodes=(RequiredTestNode(selector, "exact"),),
                check_ids=("pytest-unit",),
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer="/checks/4/status",
                    ),
                ),
            )
        requirements.append(
            AcceptanceRequirement(acceptance_id, (clause,))  # type: ignore[arg-type]
        )
    return tuple(requirements)


def _mutated_policies() -> dict[str, tuple[AcceptanceRequirement, ...]]:
    good_node = (RequiredTestNode("tests/synthetic/a.py::test_one", "exact"),)
    good_checks = ("pytest-architecture", "pytest-unit")
    good_evidence = (
        EvidenceReference(
            artifact="verification-report.json", json_pointer="/checks/4/status"
        ),
    )
    return {
        "wrong-id": _replace_requirement_id(_minimal_policy(), 0, "A-00"),
        "duplicate-id": _minimal_policy() + (_minimal_policy()[0],),
        "unsorted-ids": _minimal_policy()[::-1],
        "empty-nodes": _minimal_policy(
            a01_clause=AcceptanceClause("A-01-1", (), good_checks, good_evidence)
        ),
        "empty-checks": _minimal_policy(
            a01_clause=AcceptanceClause("A-01-1", good_node, (), good_evidence)
        ),
        "empty-evidence": _minimal_policy(
            a01_clause=AcceptanceClause("A-01-1", good_node, good_checks, ())
        ),
        "duplicate-nodes": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1", good_node + good_node, good_checks, good_evidence
            )
        ),
        "unsorted-nodes": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1",
                (
                    RequiredTestNode("tests/synthetic/b.py::test_two", "exact"),
                    RequiredTestNode("tests/synthetic/a.py::test_one", "exact"),
                ),
                good_checks,
                good_evidence,
            )
        ),
        "unsorted-checks": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1", good_node, good_checks[::-1], good_evidence
            )
        ),
        "duplicate-clause-ids": _minimal_policy(
            a01_clause=AcceptanceClause("shared", good_node, good_checks, good_evidence)
        )
        + _minimal_policy()[1:2],
        "unknown-check": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1", good_node, ("pytest-nonexistent",), good_evidence
            )
        ),
        "unknown-artifact": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1",
                good_node,
                good_checks,
                (EvidenceReference("SUMMARY.md", "/status"),),
            )
        ),
        "duplicate-evidence": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1", good_node, good_checks, good_evidence + good_evidence
            )
        ),
        "recursive-pointer": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1",
                good_node,
                good_checks,
                (
                    EvidenceReference(
                        "verification-report.json",
                        "/acceptance_map/entries/0/status",
                    ),
                ),
            )
        ),
        "bare-pointer": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1",
                good_node,
                good_checks,
                (EvidenceReference("verification-report.json", "checks/0/status"),),
            )
        ),
        "empty-pointer-token": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1",
                good_node,
                good_checks,
                (EvidenceReference("verification-report.json", "/checks//status"),),
            )
        ),
        "wildcard-selector": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1",
                (RequiredTestNode("tests/synthetic/a.py::test_*", "exact"),),
                good_checks,
                good_evidence,
            )
        ),
        "placeholder-selector": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1",
                (RequiredTestNode("tests/{module}.py::test_one", "exact"),),
                good_checks,
                good_evidence,
            )
        ),
        "non-tests-selector": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1",
                (RequiredTestNode("src/synthetic/a.py::test_one", "exact"),),
                good_checks,
                good_evidence,
            )
        ),
        "no-module-separator": _minimal_policy(
            a01_clause=AcceptanceClause(
                "A-01-1",
                (RequiredTestNode("tests/synthetic/test_a.py", "exact"),),
                good_checks,
                good_evidence,
            )
        ),
    }


def _replace_requirement_id(
    policy: tuple[AcceptanceRequirement, ...],
    index: int,
    acceptance_id: str,
) -> tuple[AcceptanceRequirement, ...]:
    replaced = policy[index]
    return (
        policy[:index]
        + (
            AcceptanceRequirement(
                acceptance_id,  # type: ignore[arg-type]
                replaced.clauses,
            ),
        )
        + policy[index + 1 :]
    )


@pytest.mark.parametrize("mutation", sorted(_mutated_policies()))
def test_acceptance_policy_mutations_are_structural_prerequisite_failures(
    mutation: str,
) -> None:
    """Catches each malformed policy shape passing Phase 1 validation."""
    with pytest.raises(EvidenceValidationError):
        validate_m1a_acceptance_policy(
            requirements=_mutated_policies()[mutation],
            allowed_check_ids=CHECK_ORDER,
        )


def test_acceptance_map_materializes_pass_and_failure_documents() -> None:
    """Catches forged PASS entries or missing failure evidence pointers."""
    outcomes = _observed_outcomes()
    base = _base_report(outcomes)
    documents = _artifact_documents(base)
    policy = verification._M1A_ACCEPTANCE_REQUIREMENTS

    passed = materialize_m1a_acceptance_map(
        requirements=policy,
        base_report=base,
        artifact_documents=documents,
        observed_test_outcomes=outcomes,
    )
    assert set(passed) == {"schema_version", "source_fingerprint", "entries"}
    assert passed["schema_version"] == ACCEPTANCE_MAP_SCHEMA_VERSION
    assert passed["source_fingerprint"] == base["source_fingerprint"]
    entries = passed["entries"]
    assert [entry["acceptance_id"] for entry in entries] == list(_ACCEPTANCE_IDS)
    for entry in entries:
        assert set(entry) == {"acceptance_id", "status", "test_nodes", "evidence"}
        assert entry["status"] == "PASS"
        expected_nodes = sorted(
            (
                node
                for clause in _expected_requirement(str(entry["acceptance_id"])).clauses
                for node in clause.required_nodes
            ),
            key=lambda node: node.selector.encode("utf-8"),
        )
        assert [(item["selector"], item["match"]) for item in entry["test_nodes"]] == [
            (node.selector, node.match) for node in expected_nodes
        ]
        for item in entry["test_nodes"]:
            assert set(item) == {"selector", "match", "observed_nodes"}
            if item["match"] == "exact":
                assert item["observed_nodes"] == [item["selector"]]
            else:
                assert item["observed_nodes"] == [item["selector"]] + [
                    item["selector"] + param for param in FAMILY_PARAMS
                ]
        assert entry["evidence"] == [
            {
                "artifact": reference.artifact,
                "json_pointer": reference.json_pointer,
            }
            for reference in _expected_requirement(str(entry["acceptance_id"]))
            .clauses[0]
            .success_evidence
        ]
    report = {**base, "acceptance_map": passed}
    validate_m1a_acceptance_report(report)

    failed_node = next(
        item for item in passed["entries"] if item["acceptance_id"] == "A-04"
    )
    registry_selector = EXPECTED_POLICY["A-04"][0][1]
    failing = _observed_outcomes(
        overrides={
            "pytest-unit": {registry_selector: "FAILED"},
        }
    )
    failing_base = _base_report(failing, check_statuses={"pytest-unit": "FAIL"})
    failed = materialize_m1a_acceptance_map(
        requirements=policy,
        base_report=failing_base,
        artifact_documents=_artifact_documents(failing_base),
        observed_test_outcomes=failing,
    )
    entry = next(item for item in failed["entries"] if item["acceptance_id"] == "A-04")
    assert entry["status"] == "FAIL"
    pointers = {(item["artifact"], item["json_pointer"]) for item in entry["evidence"]}
    assert ("verification-report.json", "/checks/4/status") in pointers
    assert ("verification-report.json", "/checks/4/test_nodes") in pointers
    assert failed_node["status"] == "PASS"

    golden_status = _observed_outcomes()
    golden_base = _base_report(golden_status, check_statuses={"stdio-golden": "FAIL"})
    golden_failed = materialize_m1a_acceptance_map(
        requirements=policy,
        base_report=golden_base,
        artifact_documents=_artifact_documents(golden_base, golden_failed=True),
        observed_test_outcomes=golden_status,
    )
    entry = next(
        item for item in golden_failed["entries"] if item["acceptance_id"] == "A-02"
    )
    assert entry["status"] == "FAIL"
    pointers = {(item["artifact"], item["json_pointer"]) for item in entry["evidence"]}
    assert ("stdio-transcript.json", "/status") in pointers
    assert ("golden-trace.json", "/status") in pointers
    assert ("golden-trace.json", "/diagnostic_code") in pointers

    drift_base = _base_report(_observed_outcomes(), status="FAILED")
    drifted = materialize_m1a_acceptance_map(
        requirements=policy,
        base_report=drift_base,
        artifact_documents=_artifact_documents(drift_base),
        observed_test_outcomes=_observed_outcomes(),
    )
    entry = next(item for item in drifted["entries"] if item["acceptance_id"] == "A-10")
    assert entry["status"] == "FAIL"
    pointers = {(item["artifact"], item["json_pointer"]) for item in entry["evidence"]}
    assert ("verification-report.json", "/status") in pointers
    assert ("verification-report.json", "/source_fingerprint") in pointers


def test_parameterized_family_requires_complete_passing_current_run_evidence() -> None:
    """Catches partial, skipped, or prefix-only family evidence passing."""
    family = "tests/synthetic/test_family.py::test_family"
    policy = _minimal_policy(
        a01_clause=AcceptanceClause(
            "A-01-1",
            (RequiredTestNode(family, "family"),),
            ("pytest-unit",),
            (
                EvidenceReference(
                    "verification-report.json", json_pointer="/checks/4/status"
                ),
            ),
        )
    )

    def materialize(outcomes: dict[str, dict[str, str]]) -> object:
        base = _base_report(outcomes)
        return materialize_m1a_acceptance_map(
            requirements=policy,
            base_report=base,
            artifact_documents=_artifact_documents(base),
            observed_test_outcomes=outcomes,
        )

    complete = {"pytest-unit": {family: "PASSED"}}
    for param in FAMILY_PARAMS:
        complete["pytest-unit"][family + param] = "PASSED"
    document = materialize(complete)
    entry = document["entries"][0]
    assert entry["status"] == "PASS"
    assert entry["test_nodes"][0]["observed_nodes"] == [family] + [
        family + param for param in FAMILY_PARAMS
    ]

    prefix_only = {"pytest-unit": {family + "_extra": "PASSED"}}
    assert materialize(prefix_only)["entries"][0]["status"] == "FAIL"

    skipped = dict(complete)
    skipped["pytest-unit"] = dict(complete["pytest-unit"])
    skipped["pytest-unit"][family + FAMILY_PARAMS[0]] = "SKIPPED"
    assert materialize(skipped)["entries"][0]["status"] == "FAIL"

    failed_case = dict(complete)
    failed_case["pytest-unit"] = dict(complete["pytest-unit"])
    failed_case["pytest-unit"][family] = "FAILED"
    assert materialize(failed_case)["entries"][0]["status"] == "FAIL"

    base_only = {"pytest-unit": {family: "PASSED"}}
    assert materialize(base_only)["entries"][0]["status"] == "PASS"

    no_member = {"pytest-unit": {}}
    assert materialize(no_member)["entries"][0]["status"] == "FAIL"


def test_acceptance_map_rejects_recursive_or_current_evidence_dependencies() -> None:
    """Catches the map reading itself, current evidence, or extra artifacts."""
    outcomes = _observed_outcomes()
    base = _base_report(outcomes)
    documents = _artifact_documents(base)
    policy = verification._M1A_ACCEPTANCE_REQUIREMENTS
    materialize_m1a_acceptance_map(
        requirements=policy,
        base_report=base,
        artifact_documents=documents,
        observed_test_outcomes=outcomes,
    )

    recursive_base = {**base, "acceptance_map": {"schema_version": "legacy"}}
    with pytest.raises(EvidenceValidationError):
        materialize_m1a_acceptance_map(
            requirements=policy,
            base_report=recursive_base,
            artifact_documents=documents,
            observed_test_outcomes=outcomes,
        )

    with pytest.raises(EvidenceValidationError):
        materialize_m1a_acceptance_map(
            requirements=policy,
            base_report=base,
            artifact_documents={**documents, "SUMMARY.md": "# summary"},
            observed_test_outcomes=outcomes,
        )

    with pytest.raises(EvidenceValidationError):
        materialize_m1a_acceptance_map(
            requirements=policy,
            base_report=base,
            artifact_documents={
                key: value
                for key, value in documents.items()
                if key != "golden-trace.json"
            },
            observed_test_outcomes=outcomes,
        )

    forged = {**base, "source_fingerprint": "sha256:" + "f" * 64}
    with pytest.raises(EvidenceValidationError):
        materialize_m1a_acceptance_map(
            requirements=policy,
            base_report=forged,
            artifact_documents=documents,
            observed_test_outcomes=outcomes,
        )

    map_document = materialize_m1a_acceptance_map(
        requirements=policy,
        base_report=base,
        artifact_documents=documents,
        observed_test_outcomes=outcomes,
    )
    report = {**base, "acceptance_map": map_document}
    validate_m1a_acceptance_report(report)
    tampered = {
        **report,
        "acceptance_map": {
            **map_document,  # type: ignore[arg-type]
            "source_fingerprint": "sha256:" + "e" * 64,
        },
    }
    with pytest.raises(EvidenceValidationError):
        validate_m1a_acceptance_report(tampered)

    unresolved = _minimal_policy(
        a01_clause=AcceptanceClause(
            "A-01-1",
            (RequiredTestNode("tests/synthetic/a.py::test_one", "exact"),),
            ("pytest-unit",),
            (
                EvidenceReference(
                    "golden-trace.json", json_pointer="/nonexistent_field"
                ),
            ),
        )
    )
    synthetic_outcomes = {
        "pytest-unit": {"tests/synthetic/a.py::test_one": "PASSED"},
        **{check: {} for check in PYTEST_CHECKS if check != "pytest-unit"},
    }
    unresolved_base = _base_report(synthetic_outcomes)
    document = materialize_m1a_acceptance_map(
        requirements=unresolved,
        base_report=unresolved_base,
        artifact_documents=_artifact_documents(unresolved_base),
        observed_test_outcomes=synthetic_outcomes,
    )
    assert document["entries"][0]["status"] == "FAIL"
    assert json.dumps(document, sort_keys=True).count("build/verification") == 0
