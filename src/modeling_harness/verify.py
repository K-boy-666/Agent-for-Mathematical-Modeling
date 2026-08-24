"""Milestone verification command wiring."""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import json
import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import shutil
import stat
import subprocess
import sys
import sysconfig
import tempfile
import time
import tomllib
from typing import Any, Callable, Final, Literal, cast
import unicodedata
import xml.etree.ElementTree as element_tree
import zipfile

from modeling_core import Milestone
from modeling_core.contracts.canonical_json import canonical_json_bytes, sha256_json
from modeling_harness.evidence import (
    AcceptanceClause,
    AcceptanceRequirement,
    EvidenceReference,
    RequiredTestNode,
    materialize_m1a_acceptance_map,
    materialize_m1b_acceptance_map,
    validate_m1a_acceptance_policy,
    validate_m1a_acceptance_report,
    validate_m1b_acceptance_policy,
    validate_m1b_acceptance_report,
)


_UV_VERSION = "0.11.28"
_UV_VERSION_TIMEOUT_SECONDS = 10
_UV_VERSION_OUTPUT = re.compile(
    r"uv 0\.11\.28(?: \((?:ebf0f43d7 2026-07-07 )?"
    r"(?:x86_64|aarch64)-(?:pc-windows-msvc|unknown-linux-(?:gnu|musl)|apple-darwin)"
    r"\))?\r?\n?\Z"
)
_M1A_CHECK_IDS: Final = (
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
_M1B_EXTRA_CHECK_IDS: Final = (
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
_M1B_CHECK_IDS: Final = (*_M1A_CHECK_IDS, *_M1B_EXTRA_CHECK_IDS)
M1A_CHECK_IDS: Final = _M1A_CHECK_IDS
M1B_CHECK_IDS: Final = _M1B_CHECK_IDS
_JUNIT_NODE_LIMIT: Final = 4096
# Bounded literal covering the real parameterized ids: A6/A11 embed full
# rejection expressions in pytest ids (current maximum is 4,245 bytes).
_JUNIT_NODE_BYTES: Final = 8192
# Clause-complete literal A-01..A-10 pytest node policy from the A12
# interface resolution section 4.3.  Every selector is a committed literal;
# each requirement owns one clause whose single success-evidence pointer
# targets its first owning check status in the fixed fifteen-check order.
_M1A_ACCEPTANCE_REQUIREMENTS: Final = (
    AcceptanceRequirement(
        acceptance_id="A-01",
        clauses=(
            AcceptanceClause(
                clause_id="A-01-1",
                required_nodes=(
                    RequiredTestNode(
                        selector=(
                            "tests/acceptance/test_m1a_acceptance_map.py::"
                            "test_a01_windows_locked_toolchain_is_current_and_offline"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_bootstrap_sqlite.py::"
                            "test_repeat_bootstrap_returns_same_id_without_changing_"
                            "any_bytes"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_bootstrap_sqlite.py::"
                            "test_uninitialized_bootstrap_creates_exact_storage_"
                            "ready_layout"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/unit/test_doctor.py::"
                            "test_uninitialized_is_warning_and_storage_ready_and_"
                            "ready_are_ready"
                        ),
                        match="exact",
                    ),
                ),
                check_ids=(
                    "pytest-acceptance",
                    "pytest-integration",
                    "pytest-unit",
                    "uv-lock",
                ),
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer="/checks/0/status",
                    ),
                ),
            ),
        ),
    ),
    AcceptanceRequirement(
        acceptance_id="A-02",
        clauses=(
            AcceptanceClause(
                clause_id="A-02-1",
                required_nodes=(
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_stdio_golden_m1a.py::"
                            "test_official_client_completes_m1a_golden_chain_"
                            "records_protocol_purity_and_closes_child"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_stdio_golden_m1a.py::"
                            "test_official_client_exception_path_closes_child_and_"
                            "releases_writer_lease"
                        ),
                        match="exact",
                    ),
                ),
                check_ids=("pytest-integration", "stdio-golden"),
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer="/checks/8/status",
                    ),
                ),
            ),
        ),
    ),
    AcceptanceRequirement(
        acceptance_id="A-03",
        clauses=(
            AcceptanceClause(
                clause_id="A-03-1",
                required_nodes=(
                    RequiredTestNode(
                        selector=(
                            "tests/architecture/test_dependency_boundaries.py::"
                            "test_core_never_imports_adapters_databases_or_"
                            "capabilities"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_application_workflow.py::"
                            "test_six_use_cases_reconstruct_a_validated_root_"
                            "finding_trace"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_stdio_golden_m1a.py::"
                            "test_official_client_completes_m1a_golden_chain_"
                            "records_protocol_purity_and_closes_child"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/unit/test_doctor.py::"
                            "test_doctor_uses_shared_facade_and_store_without_"
                            "starting_inspected_composition"
                        ),
                        match="exact",
                    ),
                ),
                check_ids=(
                    "pytest-architecture",
                    "pytest-integration",
                    "pytest-unit",
                    "stdio-golden",
                ),
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer="/checks/4/status",
                    ),
                ),
            ),
        ),
    ),
    AcceptanceRequirement(
        acceptance_id="A-04",
        clauses=(
            AcceptanceClause(
                clause_id="A-04-1",
                required_nodes=(
                    RequiredTestNode(
                        selector=(
                            "tests/architecture/test_composition_root.py::"
                            "test_composition_seals_the_exact_builtin_registry_"
                            "and_sole_store"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/unit/test_registry.py::"
                            "test_capability_and_compatible_validator_register_"
                            "before_seal"
                        ),
                        match="exact",
                    ),
                ),
                check_ids=("pytest-architecture", "pytest-unit"),
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer="/checks/4/status",
                    ),
                ),
            ),
        ),
    ),
    AcceptanceRequirement(
        acceptance_id="A-05",
        clauses=(
            AcceptanceClause(
                clause_id="A-05-1",
                required_nodes=(
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_stdio_golden_m1a.py::"
                            "test_official_client_completes_m1a_golden_chain_"
                            "records_protocol_purity_and_closes_child"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/unit/root_finding/test_validator.py::"
                            "test_golden_success_is_passed_with_exact_metrics_and_"
                            "hashes"
                        ),
                        match="exact",
                    ),
                ),
                check_ids=("pytest-unit", "stdio-golden"),
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer="/checks/4/status",
                    ),
                ),
            ),
        ),
    ),
    AcceptanceRequirement(
        acceptance_id="A-06",
        clauses=(
            AcceptanceClause(
                clause_id="A-06-1",
                required_nodes=(
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_application_workflow.py::"
                            "test_numerical_failure_is_durable_and_replayable"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_application_workflow.py::"
                            "test_pre_execution_rejections_leave_zero_provenance"
                        ),
                        # The test exists only with parameterized ids; the
                        # family match retains every exact parameter id.
                        match="family",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/unit/expression/test_canonicalization.py::"
                            "test_forbidden_expressions_map_to_security_violation"
                        ),
                        match="family",
                    ),
                ),
                check_ids=("pytest-integration", "pytest-unit"),
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer="/checks/4/status",
                    ),
                ),
            ),
        ),
    ),
    AcceptanceRequirement(
        acceptance_id="A-07",
        clauses=(
            AcceptanceClause(
                clause_id="A-07-1",
                required_nodes=(
                    RequiredTestNode(
                        selector=(
                            "tests/architecture/test_solver_validator_"
                            "independence.py::"
                            "test_validator_real_import_graph_has_only_"
                            "explicitly_allowed_modules"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/unit/root_finding/test_validator.py::"
                            "test_self_consistent_forged_result_hash_still_"
                            "fails_mathematically"
                        ),
                        match="exact",
                    ),
                ),
                check_ids=("pytest-architecture", "pytest-unit"),
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer="/checks/4/status",
                    ),
                ),
            ),
        ),
    ),
    AcceptanceRequirement(
        acceptance_id="A-08",
        clauses=(
            AcceptanceClause(
                clause_id="A-08-1",
                required_nodes=(
                    RequiredTestNode(
                        selector=(
                            "tests/contract/test_project_store.py::"
                            "test_trace_query_and_trace_enforce_all_parent_and_"
                            "uniqueness_relations"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_application_workflow.py::"
                            "test_six_use_cases_reconstruct_a_validated_root_"
                            "finding_trace"
                        ),
                        match="exact",
                    ),
                ),
                check_ids=("pytest-contract", "pytest-integration"),
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer="/checks/5/status",
                    ),
                ),
            ),
        ),
    ),
    AcceptanceRequirement(
        acceptance_id="A-09",
        clauses=(
            AcceptanceClause(
                clause_id="A-09-1",
                required_nodes=(
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_application_workflow.py::"
                            "test_completed_write_replay_is_side_effect_free"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/integration/test_application_workflow.py::"
                            "test_write_idempotency_mismatch_fails_without_new_"
                            "entities"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/security/test_m1a_boundaries.py::"
                            "test_cooperative_deadline_rejects_work_at_the_exact_"
                            "boundary"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/security/test_m1a_boundaries.py::"
                            "test_project_lock_is_exclusive_and_reusable_after_"
                            "release"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/security/test_m1a_boundaries.py::"
                            "test_public_mcp_contract_rejects_every_untrusted_"
                            "path_surface"
                        ),
                        match="family",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/security/test_m1a_boundaries.py::"
                            "test_request_larger_than_one_mib_is_rejected_before_"
                            "newline"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/unit/expression/test_canonicalization.py::"
                            "test_forbidden_expressions_map_to_security_violation"
                        ),
                        match="family",
                    ),
                ),
                check_ids=("pytest-integration", "pytest-security", "pytest-unit"),
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer="/checks/4/status",
                    ),
                ),
            ),
        ),
    ),
    AcceptanceRequirement(
        acceptance_id="A-10",
        clauses=(
            AcceptanceClause(
                clause_id="A-10-1",
                required_nodes=(
                    RequiredTestNode(
                        selector=(
                            "tests/acceptance/test_m1a_acceptance_map.py::"
                            "test_a12_runtime_and_nested_context_assets_are_"
                            "installed_offline_without_core_catalog_drift"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/acceptance/test_m1a_acceptance_map.py::"
                            "test_m1a_abstraction_budget_and_exact_context_"
                            "inventory_are_binding"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/acceptance/test_m1a_acceptance_map.py::"
                            "test_m1a_context_config_and_acceptance_map_are_"
                            "complete"
                        ),
                        match="exact",
                    ),
                    RequiredTestNode(
                        selector=(
                            "tests/reproducibility/test_m1a_repeatability.py::"
                            "test_a12_profile_and_report_transition_preserve_"
                            "a11_evidence_contract"
                        ),
                        match="exact",
                    ),
                ),
                check_ids=(
                    "pytest-acceptance",
                    "pytest-reproducibility",
                    "wheel",
                ),
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer="/checks/9/status",
                    ),
                ),
            ),
        ),
    ),
)


def _b_requirement(
    acceptance_id: str,
    selector: str | tuple[str, ...],
    check_ids: tuple[str, ...],
    check_position: int,
    *,
    match: Literal["exact", "family"] = "exact",
) -> AcceptanceRequirement:
    selectors = (selector,) if isinstance(selector, str) else selector
    return AcceptanceRequirement(
        acceptance_id=acceptance_id,
        clauses=(
            AcceptanceClause(
                clause_id=f"{acceptance_id}-1",
                required_nodes=tuple(
                    RequiredTestNode(selector=item, match=match) for item in selectors
                ),
                check_ids=check_ids,
                success_evidence=(
                    EvidenceReference(
                        artifact="verification-report.json",
                        json_pointer=f"/checks/{check_position}/status",
                    ),
                ),
            ),
        ),
    )


_M1B_ACCEPTANCE_REQUIREMENTS: Final = (
    *_M1A_ACCEPTANCE_REQUIREMENTS,
    _b_requirement(
        "B-01",
        "tests/contract/test_tool_schemas_v1.py::test_baseline_manifests_exist_and_are_valid",
        ("stable-schema-corpus",),
        15,
    ),
    _b_requirement(
        "B-02",
        "tests/contract/test_rfc8785_vectors.py::TestRFC8785AppendixB::test_b01_zero",
        ("canonical-json-conformance",),
        16,
    ),
    _b_requirement(
        "B-03",
        "tests/integration/test_artifact_workflow.py::test_artifact_workflow_persists_full_traceability_chain",
        ("artifact-store-sqlite-v2", "artifact-workflow"),
        18,
    ),
    _b_requirement(
        "B-04",
        "tests/integration/test_recovery_and_rerun.py::test_previous_session_attempt_converges_once_and_replays_abandoned",
        ("recovery-rerun", "stdio-restart"),
        19,
        match="family",
    ),
    _b_requirement(
        "B-05",
        "tests/integration/test_fault_recovery.py::test_process_death_recovers_exactly_once_at_each_persistence_window",
        ("fault-windows",),
        20,
        match="family",
    ),
    _b_requirement(
        "B-06",
        "tests/reproducibility/test_m1b_rerun.py::test_new_replay_rerun_and_restart_rerun_match_declared_invariants",
        ("restart-reproducibility", "stdio-restart"),
        23,
    ),
    _b_requirement(
        "B-07",
        "tests/security/test_m1b_artifact_boundaries.py::test_forged_project_paths_cannot_escape_the_bound_project_root",
        ("m1b-security", "stdio-restart"),
        21,
    ),
    _b_requirement(
        "B-08",
        "tests/architecture/test_echo_extension.py::TestEchoExtension::test_echo_executes_and_validates",
        ("echo-scaffold",),
        24,
    ),
    _b_requirement(
        "B-09",
        (
            "tests/acceptance/test_m1b_acceptance_map.py::test_workflow_runs_one_identical_m1b_command_on_two_os_families",
            "tests/acceptance/test_release_evidence.py::test_release_bundle_assembles_exact_redacted_tamper_evident_evidence",
        ),
        ("m1b-acceptance", "pytest-acceptance", "stdio-restart"),
        28,
    ),
    _b_requirement(
        "B-10",
        "tests/acceptance/test_documentation_consistency.py::test_stable_document_inventory_exists_and_is_nonempty",
        (
            "context-boundaries",
            "m1b-acceptance",
            "package-assets",
            "stable-documents",
        ),
        26,
    ),
)
_GOLDEN_NODE = (
    "tests/integration/test_stdio_golden_m1a.py::"
    "test_official_client_completes_m1a_golden_chain_records_protocol_purity_"
    "and_closes_child"
)
_NON_PYTHON_PACKAGE_ASSETS = frozenset(
    {
        "modeling_capabilities/AGENTS.md",
        "modeling_capabilities/root_finding/context.md",
        "modeling_capabilities/root_finding/schemas/0.1.0/canonical-input.schema.json",
        "modeling_capabilities/root_finding/schemas/0.1.0/failure-data.schema.json",
        "modeling_capabilities/root_finding/schemas/0.1.0/input.schema.json",
        "modeling_capabilities/root_finding/schemas/0.1.0/policy.schema.json",
        "modeling_capabilities/root_finding/schemas/0.1.0/report.schema.json",
        "modeling_capabilities/root_finding/schemas/0.1.0/success-data.schema.json",
        "modeling_capabilities/root_finding/schemas/1.0.0/canonical-input.schema.json",
        "modeling_capabilities/root_finding/schemas/1.0.0/failure-data.schema.json",
        "modeling_capabilities/root_finding/schemas/1.0.0/input.schema.json",
        "modeling_capabilities/root_finding/schemas/1.0.0/policy.schema.json",
        "modeling_capabilities/root_finding/schemas/1.0.0/report.schema.json",
        "modeling_capabilities/root_finding/schemas/1.0.0/success-data.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-capability.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-error.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-project.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-result.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-validation-report.schema.json",
        "modeling_core/contracts/schemas/common/0.1.0/modeling-validator.schema.json",
        "modeling_core/contracts/schemas/common/1.0.0/modeling-capability.schema.json",
        "modeling_core/contracts/schemas/common/1.0.0/modeling-error.schema.json",
        "modeling_core/contracts/schemas/common/1.0.0/modeling-project.schema.json",
        "modeling_core/contracts/schemas/common/1.0.0/modeling-result.schema.json",
        "modeling_core/contracts/schemas/common/1.0.0/modeling-validation-report.schema.json",
        "modeling_core/contracts/schemas/common/1.0.0/modeling-validator.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/create_project.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/create_project.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/create_project.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/confirm_subproblem_mmir.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/confirm_subproblem_mmir.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/confirm_subproblem_mmir.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/export_subproblem.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/export_subproblem.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/export_subproblem.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/get_project_status.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/get_project_status.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/get_project_status.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/health_check.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/health_check.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/health_check.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/list_capabilities.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/put_subproblem_mmir.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/put_subproblem_mmir.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/put_subproblem_mmir.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/register_problem_assets.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/register_problem_assets.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/register_problem_assets.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/run_experiment.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/run_experiment.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/run_experiment.result.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.error.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.request.schema.json",
        "modeling_core/contracts/schemas/tools/0.1.0/validate_experiment.result.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/confirm_subproblem_mmir.error.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/confirm_subproblem_mmir.request.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/confirm_subproblem_mmir.result.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/create_project.error.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/create_project.request.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/create_project.result.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/export_subproblem.error.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/export_subproblem.request.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/export_subproblem.result.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/get_project_status.error.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/get_project_status.request.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/get_project_status.result.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/health_check.error.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/health_check.request.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/health_check.result.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.error.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.request.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/list_capabilities.result.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/put_subproblem_mmir.error.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/put_subproblem_mmir.request.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/put_subproblem_mmir.result.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/register_problem_assets.error.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/register_problem_assets.request.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/register_problem_assets.result.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/run_experiment.error.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/run_experiment.request.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/run_experiment.result.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.error.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.request.schema.json",
        "modeling_core/contracts/schemas/tools/1.0.0/validate_experiment.result.schema.json",
        "modeling_core/AGENTS.md",
        "modeling_cli/schemas/doctor/0.1.0/report.schema.json",
        "modeling_cli/templates/codex/config.toml",
        "modeling_infrastructure/sqlite/schema_v1.sql",
        "modeling_infrastructure/sqlite/schema_v2.sql",
        "modeling_infrastructure/AGENTS.md",
        "modeling_bootstrap/AGENTS.md",
        "modeling_mcp/AGENTS.md",
    }
)
_PACKAGE_ROOT_PATHS = frozenset(
    {
        "src/modeling_cli",
        "src/modeling_capabilities",
        "src/modeling_core",
        "src/modeling_harness",
        "src/modeling_infrastructure",
        "src/modeling_bootstrap",
        "src/modeling_mcp",
    }
)


@dataclass(frozen=True, slots=True)
class _TestCounts:
    total: int
    passed: int
    failed: int
    errors: int
    skipped: int


@dataclass(frozen=True, slots=True)
class _CheckSpec:
    check_id: str
    argv: tuple[str, ...]
    timeout_seconds: int
    kind: Literal["command", "pytest", "wheel"]


@dataclass(frozen=True, slots=True)
class _CheckResult:
    check_id: str
    status: Literal["PASS", "FAIL"]
    duration_ms: int
    exit_code: int | None
    test_counts: _TestCounts | None
    diagnostic_code: str | None
    test_outcomes: dict[str, Literal["PASSED", "FAILED", "SKIPPED"]] | None = None


@dataclass(frozen=True, slots=True)
class _SourceEntry:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True)
class _SourceInventory:
    entries: tuple[_SourceEntry, ...]
    fingerprint: str


class _SourceInventoryDriftError(RuntimeError):
    """Raised when verified source bytes drift at the publication seam."""


@dataclass(frozen=True, slots=True)
class _PackageAsset:
    path: str
    sha256: str


class _WindowsFileTime(ctypes.Structure):
    _fields_ = (("low", ctypes.c_uint32), ("high", ctypes.c_uint32))


class _WindowsFileInformation(ctypes.Structure):
    _fields_ = (
        ("attributes", ctypes.c_uint32),
        ("creation_time", _WindowsFileTime),
        ("access_time", _WindowsFileTime),
        ("write_time", _WindowsFileTime),
        ("volume_serial", ctypes.c_uint32),
        ("size_high", ctypes.c_uint32),
        ("size_low", ctypes.c_uint32),
        ("link_count", ctypes.c_uint32),
        ("file_index_high", ctypes.c_uint32),
        ("file_index_low", ctypes.c_uint32),
    )


def _offline_environment() -> dict[str, str]:
    environment = dict(os.environ)
    environment["UV_OFFLINE"] = "1"
    return environment


def _validate_uv_executable(repository_root: Path) -> Path:
    uv_value = os.environ.get("UV")
    if uv_value is None:
        raise ValueError("UV must name the pinned executable")
    executable = Path(uv_value)
    if not executable.is_absolute() or not executable.is_file():
        raise ValueError("UV must be an absolute existing regular file")

    completed = subprocess.run(
        [str(executable), "--version"],
        cwd=repository_root,
        env=_offline_environment(),
        timeout=_UV_VERSION_TIMEOUT_SECONDS,
        capture_output=True,
        text=True,
        check=False,
    )
    if (
        completed.returncode != 0
        or _UV_VERSION_OUTPUT.fullmatch(completed.stdout) is None
    ):
        raise ValueError("UV must be exactly uv 0.11.28")
    return executable


def _execute_check(
    spec: _CheckSpec,
    *,
    cwd: Path,
    environment: dict[str, str],
) -> _CheckResult:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(spec.argv),
            cwd=cwd,
            env=environment,
            timeout=spec.timeout_seconds,
            capture_output=True,
            text=True,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return _CheckResult(
            check_id=spec.check_id,
            status="FAIL",
            duration_ms=max(0, round((time.monotonic() - started) * 1000)),
            exit_code=None,
            test_counts=None,
            diagnostic_code="timeout",
        )

    test_counts: _TestCounts | None = None
    test_outcomes: dict[str, Literal["PASSED", "FAILED", "SKIPPED"]] | None = None
    diagnostic_code: str | None = None
    if spec.kind == "pytest":
        junit_arguments = [
            argument for argument in spec.argv if argument.startswith("--junitxml=")
        ]
        if len(junit_arguments) != 1:
            diagnostic_code = "junit-missing"
        else:
            junit_path = Path(junit_arguments[0].partition("=")[2])
            try:
                root = element_tree.parse(junit_path).getroot()
                suites = (
                    [root] if root.tag == "testsuite" else root.findall("testsuite")
                )
                if root.tag not in {"testsuite", "testsuites"} or not suites:
                    raise ValueError("invalid JUnit root")
                total = sum(int(suite.attrib["tests"]) for suite in suites)
                failed = sum(int(suite.attrib.get("failures", "0")) for suite in suites)
                errors = sum(int(suite.attrib.get("errors", "0")) for suite in suites)
                skipped = sum(int(suite.attrib.get("skipped", "0")) for suite in suites)
                passed_count = total - failed - errors - skipped
                if min(total, passed_count, failed, errors, skipped) < 0:
                    raise ValueError("negative JUnit count")
                test_counts = _TestCounts(
                    total=total,
                    passed=passed_count,
                    failed=failed,
                    errors=errors,
                    skipped=skipped,
                )
            except (OSError, KeyError, ValueError, element_tree.ParseError):
                diagnostic_code = "junit-invalid"
            else:
                try:
                    test_outcomes = _parse_junit_test_nodes(junit_path, cwd)
                except (OSError, ValueError, element_tree.ParseError):
                    diagnostic_code = "junit-nodes-invalid"
                else:
                    if skipped:
                        diagnostic_code = "required-skip"
                    elif failed or errors:
                        diagnostic_code = "test-failure"
    if completed.returncode != 0:
        diagnostic_code = "nonzero-exit"
    passed = completed.returncode == 0 and diagnostic_code is None
    return _CheckResult(
        check_id=spec.check_id,
        status="PASS" if passed else "FAIL",
        duration_ms=max(0, round((time.monotonic() - started) * 1000)),
        exit_code=completed.returncode,
        test_counts=test_counts,
        diagnostic_code=diagnostic_code,
        test_outcomes=test_outcomes,
    )


def _collect_source_inventory(repository_root: Path) -> _SourceInventory:
    completed = subprocess.run(
        [
            "git",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
        ],
        cwd=repository_root,
        env=_offline_environment(),
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 or not isinstance(completed.stdout, bytes):
        raise ValueError("source inventory unavailable")
    try:
        decoded = completed.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as error:
        raise ValueError("source inventory paths must be UTF-8") from error
    if decoded and not decoded.endswith("\0"):
        raise ValueError("source inventory is not NUL-delimited")

    observed: dict[str, str] = {}
    entries: list[_SourceEntry] = []
    for raw_path in decoded.removesuffix("\0").split("\0") if decoded else []:
        normalized = unicodedata.normalize("NFC", raw_path)
        raw_parts = normalized.split("/")
        relative = PurePosixPath(normalized)
        if (
            not normalized
            or "\\" in normalized
            or PureWindowsPath(normalized).drive
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in raw_parts)
        ):
            raise ValueError("source inventory contains an unsafe path")
        previous = observed.get(normalized)
        if previous is not None:
            if previous != raw_path:
                raise ValueError("source inventory contains an NFC path collision")
            raise ValueError("source inventory contains a duplicate path")
        observed[normalized] = raw_path
        if not _is_regular_inventory_path(repository_root, relative):
            raise ValueError("source inventory contains a missing or non-file entry")
        entries.append(
            _SourceEntry(
                path=normalized,
                sha256=_hash_inventory_file(repository_root, relative),
            )
        )

    entries.sort(key=lambda entry: entry.path.encode("utf-8"))
    projection = [{"path": entry.path, "sha256": entry.sha256} for entry in entries]
    return _SourceInventory(
        entries=tuple(entries),
        fingerprint=sha256_json(projection),
    )


def _repository_commit(repository_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=repository_root,
        env=_offline_environment(),
        capture_output=True,
        text=True,
        check=False,
    )
    commit = completed.stdout.strip()
    if completed.returncode != 0 or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise ValueError("repository commit is unavailable")
    return commit


def _is_regular_inventory_path(repository_root: Path, relative: PurePosixPath) -> bool:
    candidate = repository_root
    metadata: os.stat_result | None = None
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    try:
        for part in relative.parts:
            candidate /= part
            metadata = os.lstat(candidate)
            if stat.S_ISLNK(metadata.st_mode) or (
                getattr(metadata, "st_file_attributes", 0) & reparse_flag
            ):
                return False
    except OSError:
        return False
    return metadata is not None and stat.S_ISREG(metadata.st_mode)


def _hash_inventory_file(repository_root: Path, relative: PurePosixPath) -> str:
    if os.name == "nt":
        return _hash_windows_inventory_file(repository_root, relative)
    return _hash_posix_inventory_file(repository_root, relative)


def _hash_posix_inventory_file(repository_root: Path, relative: PurePosixPath) -> str:
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory = getattr(os, "O_DIRECTORY", None)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    if nofollow is None or directory is None:
        raise OSError(errno.ENOTSUP, "non-following inventory open is unavailable")
    opened: list[int] = []
    try:
        current = os.open(repository_root, os.O_RDONLY | directory | cloexec)
        opened.append(current)
        for part in relative.parts[:-1]:
            current = os.open(
                part,
                os.O_RDONLY | directory | nofollow | cloexec,
                dir_fd=current,
            )
            opened.append(current)
            if not stat.S_ISDIR(os.fstat(current).st_mode):
                raise ValueError("inventory parent is not a directory")
        file_descriptor = os.open(
            relative.parts[-1],
            os.O_RDONLY | nofollow | cloexec,
            dir_fd=current,
        )
        opened.append(file_descriptor)
        if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
            raise ValueError("inventory entry is not a regular file")
        digest = hashlib.sha256()
        while chunk := os.read(file_descriptor, 1024 * 1024):
            digest.update(chunk)
        return "sha256:" + digest.hexdigest()
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _hash_windows_inventory_file(repository_root: Path, relative: PurePosixPath) -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = (
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_void_p,
    )
    create_file.restype = ctypes.c_void_p
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = (
        ctypes.c_void_p,
        ctypes.POINTER(_WindowsFileInformation),
    )
    get_information.restype = ctypes.c_int
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = (
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    )
    get_final_path.restype = ctypes.c_uint32
    read_file = kernel32.ReadFile
    read_file.argtypes = (
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_uint32),
        ctypes.c_void_p,
    )
    read_file.restype = ctypes.c_int
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = (ctypes.c_void_p,)
    close_handle.restype = ctypes.c_int

    expected = repository_root.resolve(strict=True).joinpath(*relative.parts)
    handle = create_file(
        str(expected),
        0x80000000,
        0x00000001,
        None,
        3,
        0x00200000,
        None,
    )
    if handle in {None, ctypes.c_void_p(-1).value}:
        error_code = ctypes.get_last_error()
        raise OSError(error_code, "non-following inventory open failed", expected)
    try:
        information = _WindowsFileInformation()
        if not get_information(handle, ctypes.byref(information)):
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "inventory handle metadata failed", expected)
        if information.attributes & (0x00000010 | 0x00000400):
            raise ValueError("inventory entry is not a regular file")

        required = get_final_path(handle, None, 0, 0)
        if required == 0:
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "inventory final path query failed", expected)
        buffer = ctypes.create_unicode_buffer(required + 1)
        written = get_final_path(handle, buffer, len(buffer), 0)
        if written == 0 or written >= len(buffer):
            error_code = ctypes.get_last_error()
            raise OSError(error_code, "inventory final path query failed", expected)
        observed = buffer.value
        if observed.startswith("\\\\?\\UNC\\"):
            observed = "\\\\" + observed[8:]
        elif observed.startswith("\\\\?\\"):
            observed = observed[4:]
        if os.path.normcase(os.path.abspath(observed)) != os.path.normcase(
            os.path.abspath(expected)
        ):
            raise ValueError("inventory handle resolved outside the listed path")

        digest = hashlib.sha256()
        read_buffer = ctypes.create_string_buffer(1024 * 1024)
        while True:
            count = ctypes.c_uint32()
            if not read_file(
                handle,
                read_buffer,
                len(read_buffer),
                ctypes.byref(count),
                None,
            ):
                error_code = ctypes.get_last_error()
                raise OSError(error_code, "inventory handle read failed", expected)
            if count.value == 0:
                break
            digest.update(read_buffer.raw[: count.value])
        return "sha256:" + digest.hexdigest()
    finally:
        close_handle(handle)


def _a12_incomplete_groups() -> list[dict[str, object]]:
    return []


def _parse_junit_test_nodes(
    junit_path: Path, repository_root: Path
) -> dict[str, Literal["PASSED", "FAILED", "SKIPPED"]]:
    """Parse strict normalized exact test nodes with per-node outcomes."""
    root = element_tree.parse(junit_path).getroot()
    suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
    if root.tag not in {"testsuite", "testsuites"} or not suites:
        raise ValueError("invalid JUnit root")
    outcomes: dict[str, Literal["PASSED", "FAILED", "SKIPPED"]] = {}
    for suite in suites:
        for case in suite.findall("testcase"):
            classname = case.attrib.get("classname", "")
            name = case.attrib.get("name", "")
            if not isinstance(classname, str) or not isinstance(name, str):
                raise ValueError("JUnit testcase names must be text")
            if not classname or not name:
                raise ValueError("JUnit testcase is missing a name")
            parts = classname.split(".")
            module_relative: str | None = None
            class_components: list[str] = []
            for length in range(len(parts), 0, -1):
                candidate = "/".join(parts[:length]) + ".py"
                candidate_normalized = unicodedata.normalize("NFC", candidate)
                if "\\" in candidate_normalized or any(
                    part in {"", ".", ".."} for part in parts[:length]
                ):
                    raise ValueError("JUnit classname contains an unsafe component")
                relative = PurePosixPath(candidate_normalized)
                if (
                    relative.is_absolute()
                    or PureWindowsPath(candidate_normalized).is_absolute()
                    or PureWindowsPath(candidate_normalized).drive
                ):
                    raise ValueError("JUnit classname is not a repository module")
                if not candidate_normalized.startswith("tests/"):
                    continue
                if (repository_root / candidate_normalized).is_file():
                    module_relative = candidate_normalized
                    class_components = parts[length:]
                    break
            if module_relative is None:
                raise ValueError("JUnit classname does not resolve to a tests module")
            normalized_name = unicodedata.normalize("NFC", name)
            # Backslashes are rejected in the module path above; parameterized
            # ids legitimately retain Windows path fragments verbatim.
            if any(
                ord(character) < 0x20 or ord(character) == 0x7F
                for character in normalized_name
            ):
                raise ValueError("JUnit testcase name contains unsafe characters")
            node = "::".join([module_relative, *class_components, normalized_name])
            if len(node.encode("utf-8")) > _JUNIT_NODE_BYTES:
                raise ValueError("JUnit node exceeds the byte budget")
            if node in outcomes:
                raise ValueError("JUnit node is duplicated")
            if len(outcomes) >= _JUNIT_NODE_LIMIT:
                raise ValueError("JUnit node count exceeds the budget")
            if case.find("skipped") is not None:
                outcomes[node] = "SKIPPED"
            elif case.find("failure") is not None or case.find("error") is not None:
                outcomes[node] = "FAILED"
            else:
                outcomes[node] = "PASSED"
    return outcomes


def _verification_outcome(
    checks: tuple[_CheckResult, ...] | list[_CheckResult],
    incomplete_groups: list[dict[str, object]],
) -> tuple[Literal["PASSED", "FAILED", "INCOMPLETE"], int]:
    if any(check.status == "FAIL" for check in checks):
        return "FAILED", 1
    if incomplete_groups:
        return "INCOMPLETE", 2
    return "PASSED", 0


def _inspect_package_assets(
    repository_root: Path, wheel_directory: Path
) -> tuple[_PackageAsset, ...]:
    wheels = tuple(wheel_directory.glob("*.whl"))
    if len(wheels) != 1:
        raise ValueError("wheel build must produce exactly one wheel")
    configuration = tomllib.loads(
        (repository_root / "pyproject.toml").read_text(encoding="utf-8")
    )
    packages = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    if (
        not isinstance(packages, list)
        or len(packages) != 7
        or any(not isinstance(package, str) for package in packages)
        or frozenset(packages) != _PACKAGE_ROOT_PATHS
    ):
        raise ValueError("wheel must declare the seven M1a package roots")
    package_roots: list[tuple[Path, str]] = []
    for package in packages:
        if not isinstance(package, str):
            raise ValueError("wheel package roots must be strings")
        source_root = repository_root / package
        if source_root.parent != repository_root / "src" or not source_root.is_dir():
            raise ValueError("wheel package root is outside src")
        package_roots.append((source_root, source_root.name))

    expected: set[str] = set()
    for source_root, root_name in package_roots:
        for source_path in source_root.rglob("*"):
            if not source_path.is_file():
                continue
            relative_parts = source_path.relative_to(source_root).parts
            if "__pycache__" in relative_parts or source_path.suffix in {
                ".pyc",
                ".pyo",
            }:
                continue
            expected.add(PurePosixPath(root_name, *relative_parts).as_posix())
    non_python = {path for path in expected if not path.endswith(".py")}
    if non_python != _NON_PYTHON_PACKAGE_ASSETS:
        raise ValueError("non-Python package asset inventory changed")

    payloads: dict[str, bytes] = {}
    root_names = {root_name for _, root_name in package_roots}
    with zipfile.ZipFile(wheels[0]) as archive:
        for member in archive.infolist():
            member_name = unicodedata.normalize("NFC", member.filename)
            windows_member = PureWindowsPath(member_name)
            member_path = PurePosixPath(member_name)
            if (
                "\\" in member_name
                or windows_member.drive
                or windows_member.is_absolute()
                or member_path.is_absolute()
                or ".." in member_path.parts
            ):
                raise ValueError("wheel contains an unsafe member path")
            if "spikes" in member_path.parts:
                raise ValueError("wheel contains excluded spikes")
            if member.is_dir():
                continue
            if member_path.parts and member_path.parts[0] in root_names:
                normalized = member_path.as_posix()
                if normalized in payloads:
                    raise ValueError("wheel contains a duplicate package member")
                payloads[normalized] = archive.read(member)
    if set(payloads) != expected:
        raise ValueError("wheel package payload differs from source packages")
    return tuple(
        _PackageAsset(
            path=path,
            sha256="sha256:" + hashlib.sha256(payloads[path]).hexdigest(),
        )
        for path in sorted(payloads, key=lambda value: value.encode("utf-8"))
    )


def _build_check_specs(uv: Path, internal: Path) -> tuple[_CheckSpec, ...]:
    executable = str(uv)

    def pytest_spec(check_id: str, test_path: str, timeout: int = 180) -> _CheckSpec:
        return _CheckSpec(
            check_id=check_id,
            argv=(
                executable,
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                test_path,
                "-q",
                f"--junitxml={internal / f'{check_id}.xml'}",
            ),
            timeout_seconds=timeout,
            kind="pytest",
        )

    wheel_directory = internal / "wheel"
    return (
        _CheckSpec(
            "uv-lock", (executable, "lock", "--check", "--offline"), 30, "command"
        ),
        _CheckSpec(
            "ruff-check",
            (
                executable,
                "run",
                "--locked",
                "--no-sync",
                "ruff",
                "check",
                "src",
                "tests",
            ),
            60,
            "command",
        ),
        _CheckSpec(
            "ruff-format",
            (
                executable,
                "run",
                "--locked",
                "--no-sync",
                "ruff",
                "format",
                "--check",
                "src",
                "tests",
            ),
            60,
            "command",
        ),
        _CheckSpec(
            "mypy",
            (executable, "run", "--locked", "--no-sync", "mypy", "src"),
            120,
            "command",
        ),
        pytest_spec("pytest-unit", "tests/unit"),
        pytest_spec("pytest-contract", "tests/contract"),
        pytest_spec("pytest-math", "tests/math"),
        pytest_spec("pytest-architecture", "tests/architecture"),
        pytest_spec("pytest-integration", "tests/integration"),
        pytest_spec("pytest-reproducibility", "tests/reproducibility"),
        pytest_spec("pytest-security", "tests/security"),
        pytest_spec("pytest-smoke", "tests/smoke"),
        pytest_spec("pytest-acceptance", "tests/acceptance"),
        _CheckSpec(
            "wheel",
            (
                executable,
                "build",
                "--wheel",
                "--offline",
                "--out-dir",
                str(wheel_directory),
            ),
            120,
            "wheel",
        ),
        pytest_spec("stdio-golden", _GOLDEN_NODE, 120),
    )


def _build_m1b_check_specs(uv: Path, internal: Path) -> tuple[_CheckSpec, ...]:
    executable = str(uv)

    def pytest_spec(check_id: str, *test_paths: str, timeout: int = 180) -> _CheckSpec:
        return _CheckSpec(
            check_id=check_id,
            argv=(
                executable,
                "run",
                "--locked",
                "--no-sync",
                "pytest",
                *test_paths,
                "-q",
                f"--junitxml={internal / f'{check_id}.xml'}",
            ),
            timeout_seconds=timeout,
            kind="pytest",
        )

    wheel_directory = internal / "wheel"
    package_check = (
        "from pathlib import Path; from zipfile import ZipFile; "
        f"w=next(Path({str(wheel_directory)!r}).glob('*.whl')); "
        "n=ZipFile(w).namelist(); "
        "assert any(x.endswith('.schema.json') for x in n); "
        "assert any(x.endswith('schema_v2.sql') for x in n)"
    )
    return (
        *_build_check_specs(uv, internal),
        pytest_spec(
            "stable-schema-corpus",
            "tests/contract/test_tool_schemas_v1.py",
            "tests/contract/test_schema_compatibility.py",
        ),
        pytest_spec(
            "canonical-json-conformance",
            "tests/contract/test_rfc8785_vectors.py",
        ),
        pytest_spec(
            "artifact-store-sqlite-v2",
            "tests/contract/test_artifact_store.py",
            "tests/contract/test_sqlite_schema_v2.py",
        ),
        pytest_spec("artifact-workflow", "tests/integration/test_artifact_workflow.py"),
        pytest_spec("recovery-rerun", "tests/integration/test_recovery_and_rerun.py"),
        pytest_spec("fault-windows", "tests/integration/test_fault_recovery.py"),
        pytest_spec("m1b-security", "tests/security/test_m1b_artifact_boundaries.py"),
        pytest_spec("affine-math", "tests/math/test_root_finding_affine_v1.py"),
        pytest_spec(
            "restart-reproducibility",
            "tests/reproducibility/test_m1b_rerun.py",
        ),
        pytest_spec("echo-scaffold", "tests/architecture/test_echo_extension.py"),
        pytest_spec(
            "context-boundaries", "tests/architecture/test_context_boundaries.py"
        ),
        pytest_spec(
            "stable-documents", "tests/acceptance/test_documentation_consistency.py"
        ),
        pytest_spec(
            "stdio-restart", "tests/integration/test_stdio_restart_m1b.py", timeout=240
        ),
        pytest_spec("m1b-acceptance", "tests/acceptance/test_m1b_acceptance_map.py"),
        _CheckSpec(
            "package-assets",
            (sys.executable, "-c", package_check),
            30,
            "command",
        ),
    )


def _json_payload(value: object) -> bytes:
    return canonical_json_bytes(value) + b"\n"  # type: ignore[arg-type]


def _atomic_replace(path: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _serialize_check(check: _CheckResult) -> dict[str, object]:
    counts = None
    if check.test_counts is not None:
        counts = {
            "total": check.test_counts.total,
            "passed": check.test_counts.passed,
            "failed": check.test_counts.failed,
            "errors": check.test_counts.errors,
            "skipped": check.test_counts.skipped,
        }
    return {
        "check_id": check.check_id,
        "status": check.status,
        "duration_ms": check.duration_ms,
        "exit_code": check.exit_code,
        "test_counts": counts,
        "test_nodes": (
            sorted(check.test_outcomes, key=lambda value: value.encode("utf-8"))
            if check.test_outcomes is not None
            else None
        ),
        "diagnostic_code": check.diagnostic_code,
    }


def _environment_report(
    repository_root: Path,
    uv: Path,
    *,
    include_distribution: bool = False,
) -> dict[str, object]:
    lock = repository_root / "uv.lock"
    if not lock.is_file():
        raise ValueError("uv.lock is missing")
    report: dict[str, object] = {
        "python_version": platform.python_version(),
        "uv_version": _UV_VERSION,
        "uv_executable_sha256": "sha256:" + hashlib.sha256(uv.read_bytes()).hexdigest(),
        "os_family": platform.system(),
        "os_version": platform.version(),
        "architecture": _architecture_label(),
        "lock_sha256": "sha256:" + hashlib.sha256(lock.read_bytes()).hexdigest(),
    }
    if include_distribution:
        report["distribution"] = _distribution_report()
    return report


def _distribution_report() -> dict[str, str]:
    family = platform.system()
    if family == "Windows":
        return {"id": "windows", "version": platform.version()}
    if family != "Linux":
        raise ValueError("m1b verification supports only Windows and Linux")
    values: dict[str, str] = {}
    for line in (
        Path("/etc/os-release").read_text(encoding="utf-8")[:16_384].splitlines()
    ):
        key, separator, raw_value = line.partition("=")
        if separator and key in {"ID", "VERSION_ID"}:
            values[key] = raw_value.strip().strip('"')
    distribution_id = values.get("ID", "")
    version = values.get("VERSION_ID", "")
    if (
        re.fullmatch(r"[a-z0-9._-]{1,64}", distribution_id) is None
        or re.fullmatch(r"[A-Za-z0-9._+-]{1,64}", version) is None
    ):
        raise ValueError("Linux distribution metadata is unavailable")
    return {"id": distribution_id, "version": version}


def _architecture_label() -> str:
    machine = platform.machine().strip()
    if machine:
        return machine
    platform_name = sysconfig.get_platform().strip()
    if not platform_name:
        raise ValueError("platform architecture is unavailable")
    return platform_name.rsplit("-", maxsplit=1)[-1].upper()


def _golden_ids(trace_path: Path) -> dict[str, str]:
    value = json.loads(trace_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("golden trace must be an object")
    if value.get("schema_version") == "m1a-golden-trace-failure/0.1.0":
        return {
            "project_id": "",
            "experiment_id": "",
            "attempt_id": "",
            "validation_id": "",
        }
    result: dict[str, str] = {}
    for key in ("project_id", "experiment_id", "attempt_id", "validation_id"):
        item = value.get(key)
        if not isinstance(item, str):
            raise ValueError("golden trace is missing an identifier")
        result[key] = item
    return result


def _replace_failed_golden_artifacts(staging: Path) -> None:
    transcript = staging / "stdio-transcript.json"
    trace = staging / "golden-trace.json"
    for path in (transcript, trace):
        if path.exists():
            if not path.is_file() or path.is_symlink():
                raise ValueError("failed golden artifact is unsafe")
            path.unlink()
    _atomic_replace(
        transcript,
        _json_payload(
            {
                "schema_version": "m1a-stdio-transcript-failure/0.1.0",
                "status": "UNAVAILABLE",
                "diagnostic_code": "golden-check-failed",
                "events": [],
            }
        ),
    )
    _atomic_replace(
        trace,
        _json_payload(
            {
                "schema_version": "m1a-golden-trace-failure/0.1.0",
                "status": "UNAVAILABLE",
                "diagnostic_code": "golden-check-failed",
            }
        ),
    )


def _summary(report: dict[str, object]) -> bytes:
    checks = cast(list[dict[str, object]], report["checks"])
    lines = [
        f"# {str(report['milestone']).upper()} verification",
        "",
        f"Status: {report['status']}",
        f"Source fingerprint: {report['source_fingerprint']}",
        f"Required skips: {report['required_skips']}",
        "",
        "Checks:",
    ]
    lines.extend(f"- {check['check_id']}: {check['status']}" for check in checks)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _run_m1a_verification(
    repository_root: Path,
    *,
    check_runner: Callable[..., _CheckResult] = _execute_check,
    incomplete_groups: list[dict[str, object]] | None = None,
) -> int:
    return _run_milestone_verification(
        repository_root,
        milestone="m1a",
        check_runner=check_runner,
        incomplete_groups=incomplete_groups,
    )


def _run_milestone_verification(
    repository_root: Path,
    *,
    milestone: Literal["m1a", "m1b"],
    check_runner: Callable[..., _CheckResult] = _execute_check,
    incomplete_groups: list[dict[str, object]] | None = None,
) -> int:
    uv = _validate_uv_executable(repository_root)
    if milestone == "m1b" and platform.system() not in {"Windows", "Linux"}:
        raise ValueError("m1b verification supports only Windows and Linux")
    check_ids: tuple[str, ...]
    requirements: tuple[AcceptanceRequirement, ...]
    if milestone == "m1a":
        check_ids = _M1A_CHECK_IDS
        requirements = _M1A_ACCEPTANCE_REQUIREMENTS
        validate_m1a_acceptance_policy(
            requirements=requirements,
            allowed_check_ids=check_ids,
        )
    else:
        check_ids = _M1B_CHECK_IDS
        requirements = _M1B_ACCEPTANCE_REQUIREMENTS
        validate_m1b_acceptance_policy(
            requirements=requirements,
            allowed_check_ids=check_ids,
        )
    os.environ["UV_OFFLINE"] = "1"
    environment = _offline_environment()
    environment.pop("MODELING_M1A_GOLDEN_EVIDENCE_DIR", None)
    initial_inventory = _collect_source_inventory(repository_root)
    commit = _repository_commit(repository_root) if milestone == "m1b" else None
    fingerprint_hex = initial_inventory.fingerprint.removeprefix("sha256:")
    if len(fingerprint_hex) != 64 or any(
        character not in "0123456789abcdef" for character in fingerprint_hex
    ):
        raise ValueError("source fingerprint is invalid")

    evidence_root = repository_root / "build" / "verification" / milestone
    evidence_root.mkdir(parents=True, exist_ok=True)
    final = evidence_root / fingerprint_hex
    staging = evidence_root / f".{fingerprint_hex}.staging"
    if final.exists():
        raise FileExistsError("verification evidence already exists")
    staging.mkdir(exist_ok=False)
    internal = staging / ".internal"
    internal.mkdir()
    (internal / "wheel").mkdir()

    specs = (
        _build_check_specs(uv, internal)
        if milestone == "m1a"
        else _build_m1b_check_specs(uv, internal)
    )
    results: list[_CheckResult] = []
    for spec in specs:
        child_environment = dict(environment)
        if spec.check_id == "stdio-golden":
            child_environment["MODELING_M1A_GOLDEN_EVIDENCE_DIR"] = str(staging)
        results.append(
            check_runner(
                spec,
                cwd=repository_root,
                environment=child_environment,
            )
        )

    wheel_index = next(
        index for index, result in enumerate(results) if result.check_id == "wheel"
    )
    wheel_result = results[wheel_index]
    package_assets: tuple[_PackageAsset, ...] = ()
    if wheel_result.status == "PASS":
        try:
            package_assets = _inspect_package_assets(
                repository_root, internal / "wheel"
            )
        except (
            KeyError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            zipfile.BadZipFile,
        ):
            wheel_result = _CheckResult(
                check_id=wheel_result.check_id,
                status="FAIL",
                duration_ms=wheel_result.duration_ms,
                exit_code=wheel_result.exit_code,
                test_counts=wheel_result.test_counts,
                diagnostic_code="package-inspection-failed",
            )
            results[wheel_index] = wheel_result
    transcript_path = staging / "stdio-transcript.json"
    trace_path = staging / "golden-trace.json"
    golden_result = next(
        result for result in results if result.check_id == "stdio-golden"
    )
    if golden_result.status == "FAIL":
        _replace_failed_golden_artifacts(staging)
    elif not transcript_path.is_file() or not trace_path.is_file():
        raise ValueError("dedicated golden evidence is missing")

    architecture = next(
        result for result in results if result.check_id == "pytest-architecture"
    )
    source_document = [
        {"path": entry.path, "sha256": entry.sha256}
        for entry in initial_inventory.entries
    ]
    package_document = [
        {"path": asset.path, "sha256": asset.sha256} for asset in package_assets
    ]
    architecture_document = {
        "schema_version": f"{milestone}-architecture-report/1.0.0"
        if milestone == "m1b"
        else "m1a-architecture-report/0.1.0",
        "status": architecture.status,
        "check_id": architecture.check_id,
        "test_counts": _serialize_check(architecture)["test_counts"],
    }
    _atomic_replace(staging / "source-inventory.json", _json_payload(source_document))
    _atomic_replace(staging / "package-assets.json", _json_payload(package_document))
    _atomic_replace(
        staging / "architecture-report.json", _json_payload(architecture_document)
    )

    groups = (
        (_a12_incomplete_groups() if milestone == "m1a" else [])
        if incomplete_groups is None
        else incomplete_groups
    )
    status, exit_code = _verification_outcome(results, groups)
    final_inventory = _collect_source_inventory(repository_root)
    if final_inventory != initial_inventory:
        status, exit_code = "FAILED", 1
    required_skips = sum(
        result.test_counts.skipped
        for result in results
        if result.test_counts is not None
    )
    observed_test_outcomes: dict[
        str, dict[str, Literal["PASSED", "FAILED", "SKIPPED"]]
    ] = {}
    for spec, result in zip(specs, results):
        if spec.kind == "pytest":
            observed_test_outcomes[spec.check_id] = dict(result.test_outcomes or {})

    def artifact_documents(base_report: dict[str, object]) -> dict[str, object]:
        return {
            "verification-report.json": base_report,
            "architecture-report.json": architecture_document,
            "source-inventory.json": source_document,
            "package-assets.json": package_document,
            "stdio-transcript.json": json.loads(
                transcript_path.read_text(encoding="utf-8")
            ),
            "golden-trace.json": json.loads(trace_path.read_text(encoding="utf-8")),
        }

    def compose_final_report(
        base_status: str,
    ) -> tuple[dict[str, object], int]:
        base_report: dict[str, object] = {
            "schema_version": (
                "m1a-verification-report/0.2.0"
                if milestone == "m1a"
                else "m1b-verification-report/1.0.0"
            ),
            "milestone": milestone,
            "status": base_status,
            "source_fingerprint": initial_inventory.fingerprint,
            "required_skips": required_skips,
            "environment": _environment_report(
                repository_root,
                uv,
                include_distribution=milestone == "m1b",
            ),
            "checks": [_serialize_check(result) for result in results],
            "artifacts": {
                "source_inventory": "source-inventory.json",
                "package_assets": "package-assets.json",
                "architecture_report": "architecture-report.json",
                "stdio_transcript": "stdio-transcript.json",
                "golden_trace": "golden-trace.json",
            },
            "golden_ids": _golden_ids(trace_path),
            "incomplete_groups": groups,
        }
        if commit is not None:
            base_report["commit"] = commit
        materialize = (
            materialize_m1a_acceptance_map
            if milestone == "m1a"
            else materialize_m1b_acceptance_map
        )
        acceptance_map = materialize(
            requirements=requirements,
            base_report=base_report,
            artifact_documents=artifact_documents(base_report),
            observed_test_outcomes=observed_test_outcomes,
        )
        final_status: str = base_status
        if base_status != "FAILED" and any(
            entry["status"] == "FAIL"
            for entry in cast(list[dict[str, object]], acceptance_map["entries"])
        ):
            final_status = "FAILED"
        final_exit = 1 if final_status == "FAILED" else exit_code
        report_document: dict[str, object] = {
            **base_report,
            "status": final_status,
            "acceptance_map": acceptance_map,
        }
        if milestone == "m1a":
            validate_m1a_acceptance_report(report_document)
        else:
            validate_m1b_acceptance_report(report_document)
        return report_document, final_exit

    report, composed_exit_code = compose_final_report(status)
    shutil.rmtree(internal)
    _atomic_replace(staging / "verification-report.json", _json_payload(report))
    _atomic_replace(staging / "SUMMARY.md", _summary(report))

    def guard_source_at_publication() -> None:
        current_inventory = _collect_source_inventory(repository_root)
        if report["status"] != "FAILED" and current_inventory != initial_inventory:
            raise _SourceInventoryDriftError

    try:
        _atomic_publish_directory(
            staging,
            final,
            before_publish=guard_source_at_publication,
        )
    except _SourceInventoryDriftError:
        report, composed_exit_code = compose_final_report("FAILED")
        _atomic_replace(staging / "verification-report.json", _json_payload(report))
        _atomic_replace(staging / "SUMMARY.md", _summary(report))
        _atomic_publish_directory(
            staging,
            final,
            before_publish=guard_source_at_publication,
        )
    return composed_exit_code


def _atomic_publish_directory(
    staging: Path,
    final: Path,
    *,
    before_publish: Callable[[], None] | None = None,
) -> None:
    """Atomically rename a directory while refusing an existing destination."""
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file = kernel32.MoveFileExW
        move_file.argtypes = (ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32)
        move_file.restype = ctypes.c_int
        if before_publish is not None:
            before_publish()
        if move_file(str(staging), str(final), 0):
            return
        error_code = ctypes.get_last_error()
        if error_code in {80, 183}:
            raise FileExistsError(
                error_code, "verification evidence already exists", final
            )
        raise OSError(error_code, "atomic verification publication failed", final)

    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        try:
            renameat2 = libc.renameat2
        except AttributeError as error:
            raise OSError(errno.ENOSYS, "renameat2 is unavailable") from error
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        at_fdcwd = -100
        rename_noreplace = 1
        if before_publish is not None:
            before_publish()
        if (
            renameat2(
                at_fdcwd,
                os.fsencode(staging),
                at_fdcwd,
                os.fsencode(final),
                rename_noreplace,
            )
            == 0
        ):
            return
        error_code = ctypes.get_errno()
        if error_code == errno.EEXIST:
            raise FileExistsError(
                error_code, "verification evidence already exists", final
            )
        raise OSError(error_code, "atomic verification publication failed", final)

    raise OSError(errno.ENOTSUP, "atomic no-replace publication is unsupported")


def _publish_failure_diagnostic(repository_root: Path) -> None:
    failures = repository_root / "build" / "verification" / "m1a" / "failures"
    failures.mkdir(parents=True, exist_ok=True)
    diagnostic = Path(tempfile.mkdtemp(prefix="failure-", dir=failures))
    _atomic_replace(
        diagnostic / "diagnostic.json",
        _json_payload(
            {
                "schema_version": "m1a-verification-diagnostic/0.1.0",
                "milestone": "m1a",
                "diagnostic_code": "prerequisite-or-publication-failure",
            }
        ),
    )


def _run_c1_verification(repository_root: Path) -> int:
    """Run C1 milestone verification: contract tests + solver/validator checks."""
    from modeling_harness.c1_verify import verify_c1

    initial_inventory = _collect_source_inventory(repository_root)

    # 1. Run C1 contract tests
    uv = _validate_uv_executable(repository_root)
    os.environ["UV_OFFLINE"] = "1"
    environment = _offline_environment()

    c1_test_files = [
        "tests/contract/test_c1_preview_contracts.py",
        "tests/contract/test_c1_asset_snapshots.py",
        "tests/contract/test_c1_mmir_confirmation.py",
        "tests/contract/test_c1_worker_isolation.py",
        "tests/contract/test_c1_coupled_heave_solver.py",
        "tests/contract/test_c1_validators.py",
        "tests/contract/test_c1_export.py",
    ]

    all_passed = True
    for test_file in c1_test_files:
        try:
            completed = subprocess.run(
                [str(uv), "run", "--locked", "--no-sync", "pytest", test_file, "-q"],
                cwd=repository_root,
                env=environment,
                timeout=120,
                capture_output=True,
                text=True,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print(f"C1 contract test timed out: {test_file}", file=sys.stderr)
            all_passed = False
            continue

        if completed.returncode != 0:
            print(
                f"C1 contract test FAILED ({completed.returncode}): {test_file}",
                file=sys.stderr,
            )
            print(completed.stdout[-2000:], file=sys.stderr)
            all_passed = False

    # 2. Run solver/validator/worker checks
    c1_passed, c1_report = verify_c1(repository_root)
    if not c1_passed:
        all_passed = False
        for check in cast(list[dict[str, Any]], c1_report["checks"]):
            if check["status"] == "FAIL":
                print(
                    f"  C1 check FAIL: {check['name']} — {check['details']}",
                    file=sys.stderr,
                )

    # 3. Source drift check
    final_inventory = _collect_source_inventory(repository_root)
    if final_inventory != initial_inventory:
        print("C1 verification: source drift detected", file=sys.stderr)
        all_passed = False

    if all_passed:
        print("C1 verification: PASSED", flush=True)
        return 0
    else:
        print("C1 verification: FAILED", file=sys.stderr)
        return 1


def run_verification(
    milestone: Milestone,
    only: list[str] | None = None,
    capability: str | None = None,
) -> int:
    """Run the registered milestone verification profile."""
    print(milestone.value, flush=True)
    repository_root = Path.cwd().resolve()
    if milestone is Milestone.M1A:
        if only or capability:
            print("--only/--capability is not supported for m1a", file=sys.stderr)
            return 2
        try:
            return _run_m1a_verification(repository_root)
        except (OSError, ValueError, subprocess.SubprocessError):
            try:
                _publish_failure_diagnostic(repository_root)
            except OSError:
                pass
            print(
                "verification harness prerequisite or publication failed",
                file=sys.stderr,
            )
            return 2
    if milestone is Milestone.C1:
        if only or capability:
            print("--only/--capability is not supported for c1", file=sys.stderr)
            return 2
        try:
            return _run_c1_verification(repository_root)
        except (OSError, ValueError, subprocess.SubprocessError):
            print("C1 verification harness prerequisite failed", file=sys.stderr)
            return 2
    if milestone is Milestone.M1B:
        if capability:
            return _run_capability_focused(repository_root, capability)
        return _run_m1b_verification(repository_root, only=only)
    print("verification milestone is not registered", file=sys.stderr)
    return 2


def _run_m1b_verification(
    repository_root: Path,
    only: list[str] | None = None,
) -> int:
    """Run the full M1b profile or selected development checks."""
    if only is None:
        return _run_milestone_verification(repository_root, milestone="m1b")

    for check_id in only:
        if check_id not in _M1B_CHECK_IDS:
            print(
                f"unknown check_id: {check_id} (valid: {', '.join(_M1B_CHECK_IDS)})",
                file=sys.stderr,
            )
            return 2

    uv = _validate_uv_executable(repository_root)
    with tempfile.TemporaryDirectory(prefix="modeling-m1b-focused-") as temporary:
        internal = Path(temporary)
        (internal / "wheel").mkdir()
        specs = {spec.check_id: spec for spec in _build_m1b_check_specs(uv, internal)}
        environment = _offline_environment()
        environment["MODELING_M1A_GOLDEN_EVIDENCE_DIR"] = str(internal)
        results: list[_CheckResult] = []
        if "package-assets" in only and "wheel" not in only:
            results.append(
                _execute_check(
                    specs["wheel"], cwd=repository_root, environment=environment
                )
            )
        results.extend(
            _execute_check(
                specs[check_id], cwd=repository_root, environment=environment
            )
            for check_id in only
        )
    for result in results:
        print(f"{result.check_id} {result.status}", flush=True)
    return 0 if all(result.status == "PASS" for result in results) else 1


def _run_canonical_json_conformance(repository_root: Path) -> bool:
    """Run RFC 8785 vector conformance tests."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(repository_root / "tests" / "contract" / "test_rfc8785_vectors.py"),
            "-q",
        ],
        cwd=repository_root,
        capture_output=False,
    )
    if result.returncode == 0:
        print("canonical-json-conformance PASS", flush=True)
        return True
    print("canonical-json-conformance FAIL", flush=True)
    return False


def _run_schema_compatibility(repository_root: Path) -> bool:
    """Run schema compatibility tests."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(
                repository_root / "tests" / "contract" / "test_schema_compatibility.py"
            ),
            "-q",
        ],
        cwd=repository_root,
        capture_output=False,
    )
    if result.returncode == 0:
        print("schema-compatibility PASS", flush=True)
        return True
    print("schema-compatibility FAIL", flush=True)
    return False


def _execute(arguments: argparse.Namespace) -> int:
    milestone = cast(Milestone | None, arguments.milestone)
    only = cast(list[str] | None, getattr(arguments, "only", None))
    capability = cast(str | None, getattr(arguments, "capability", None))
    if milestone is None:
        if capability is not None and only is None:
            return _run_capability_focused(Path.cwd().resolve(), capability)
        print("--milestone is required for completion evidence", file=sys.stderr)
        return 2
    return run_verification(milestone, only=only, capability=capability)


def _run_capability_focused(repository_root: Path, capability_id: str) -> int:
    """Run focused checks for a single capability — development feedback mode."""
    if capability_id == "numerical.root_finding":
        print(
            "numerical.root_finding: running contract, solver, validator, architecture checks",
            flush=True,
        )
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(repository_root / "tests" / "unit" / "test_registry.py"),
                str(repository_root / "tests" / "architecture"),
                str(
                    repository_root
                    / "tests"
                    / "contract"
                    / "test_capability_schemas_v0.py"
                ),
                str(repository_root / "tests" / "contract" / "test_tool_schemas_v1.py"),
                str(repository_root / "tests" / "math"),
                "-q",
            ],
            cwd=repository_root,
            capture_output=False,
        )
        return result.returncode

    print(f"unregistered capability: {capability_id}", file=sys.stderr)
    return 2


def add_verify_parser(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    """Register the verification subcommand."""
    parser = subparsers.add_parser("verify")
    parser.add_argument(
        "--milestone",
        type=Milestone,
        choices=tuple(Milestone),
        required=False,
    )
    parser.add_argument(
        "--only",
        action="append",
        dest="only",
        default=None,
        help="Run only the named check (repeatable); focused mode, no completion evidence",
    )
    parser.add_argument(
        "--capability",
        dest="capability",
        default=None,
        help="Run only the checks for the named capability; development feedback mode",
    )
    parser.set_defaults(handler=_execute)
