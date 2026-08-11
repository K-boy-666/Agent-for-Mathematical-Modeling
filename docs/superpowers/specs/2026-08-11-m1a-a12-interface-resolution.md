# M1a Task A12 Interface Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve Task A12's three interface gaps while preserving A11's read-only, failure-publication, exact-seven-artifact, and source-fingerprint guarantees.

**Architecture:** Extend the existing `ProjectStore` read-only snapshot; keep doctor as a CLI consumer of the composed Facade and Store; add one CLI-owned packaged Schema; embed a failure-capable acceptance map in `verification-report.json` 0.2.0. No second DB port, doctor-side SQL, seventh Facade/MCP method, or eighth evidence artifact is allowed.

**Tech Stack:** Python 3.11, SQLite URI read-only mode, Pydantic DTOs, JSON Schema Draft 2020-12, pytest, Hatch/uv, existing M1a Harness.

## Global Constraints

- This document is binding for Task A12 and supersedes the original A12 text only where interfaces, file ownership, TDD slices, or evidence shapes conflict.
- A11 must be committed and clean before A12 product/test work begins.
- Inspected project: no bootstrap, migration, repair, DML/DDL, writer lease, writer lock, or authoritative byte change.
- Deep diagnostics may mutate only a newly owned `TemporaryDirectory` and must remove it.
- Preserve six MCP tools, seven package roots, seven final evidence filenames, 18 tool Schemas, and core catalog fingerprint.
- M1a remains fixed/repeatability stable-hash smoke only; no RFC 8785, M1b, release, recovery, worker, plugin, queue, UI, remote, or cross-platform claim.
- Every string ordering rule below means `value.encode("utf-8")`, component by component.

---

## 1. Authorized file delta

Original A12 files remain authorized. Add only:

- Create `src/modeling_cli/schemas/doctor/0.1.0/report.schema.json`.
- Create `src/modeling_cli/templates/codex/config.toml` as installed runtime authority.
- Create `tests/integration/test_read_only_diagnostics.py`.
- Modify `src/modeling_core/ports/project_store.py`.
- Modify `src/modeling_infrastructure/storage.py`.
- Modify `src/modeling_infrastructure/sqlite/store.py`.
- Modify `tests/contract/test_project_store.py`.
- Modify `tests/security/test_m1a_boundaries.py`.
- Modify `tests/architecture/test_dependency_boundaries.py`.
- Modify `tests/reproducibility/test_m1a_repeatability.py`.

No `pyproject.toml`, core Schema catalog, MCP Schema, composition API, or dependency change is authorized.

## 2. Resolution R1: one complete read-only diagnostic path

### 2.1 Core DTO contract

Retain:

```python
def inspect_integrity(self, deep: bool) -> StoreIntegrityReport: ...
```

Add frozen DTOs and finite aliases in `project_store.py`:

```python
IntegrityCheckMode = Literal["quick", "integrity"]
IntegrityCheckOutcome = Literal["PASS", "FAIL", "ERROR"]
StoreIntegrityIssue = Literal[
    "sqlite_quick_check", "sqlite_integrity_check", "foreign_key",
    "stale_attempt", "stale_validation", "stale_operation",
    "database_relation", "project_state",
]
LegacyOperationTool = Literal["run_experiment", "validate_experiment"]

@dataclass(frozen=True)
class StoreIntegrityCheck:
    mode: IntegrityCheckMode
    outcome: IntegrityCheckOutcome

@dataclass(frozen=True)
class LegacyAttempt:
    attempt_id: EntityId
    status: Literal["PENDING", "RUNNING"]

@dataclass(frozen=True)
class LegacyValidation:
    validation_id: EntityId
    status: Literal["PENDING", "RUNNING"]

@dataclass(frozen=True)
class LegacyIdempotencyRecord:
    scope_id: EntityId
    tool_name: LegacyOperationTool
    operation_id: EntityId
    status: Literal["IN_PROGRESS"]

@dataclass(frozen=True)
class StoreIntegrityReport:
    state: ProjectState
    issues: tuple[StoreIntegrityIssue, ...]
    check: StoreIntegrityCheck | None = None
    legacy_attempts: tuple[LegacyAttempt, ...] = ()
    legacy_validations: tuple[LegacyValidation, ...] = ()
    legacy_idempotency_records: tuple[LegacyIdempotencyRecord, ...] = ()
```

Validation is exact:

- all IDs use existing canonical lowercase UUIDv4 `EntityId` validation;
- issue/row tuples reject duplicates and require UTF-8-byte order;
- attempt/validation order is `(status.encode(), id.encode())`;
- operation order is `(scope_id.encode(), tool_name.encode(), operation_id.encode())`;
- each legacy tuple is capped at 100; query 101 rows and map overflow to `database_relation` without publishing a partial tuple;
- unknown `IN_PROGRESS.tool_name` becomes `database_relation`, never free text;
- defaults preserve existing fake Store constructors.

### 2.2 Store branch table

| Condition | `check` | issues / rows | returned state |
| --- | --- | --- | --- |
| UNINITIALIZED | `None` | empty | UNINITIALIZED |
| already DEGRADED | `None` | exactly `project_state`; rows empty; no PRAGMA | DEGRADED |
| `deep=False` | execute exactly `PRAGMA quick_check` | continue below | source state or DEGRADED |
| `deep=True` | execute exactly `PRAGMA integrity_check` | continue below | source state or DEGRADED |
| selected PRAGMA returns exactly one row `("ok",)` | selected mode / PASS | no SQLite issue | continue |
| any other PRAGMA row shape/value | selected mode / FAIL | selected `sqlite_*` issue | DEGRADED |
| open/execute error | selected mode / ERROR | `database_relation` | DEGRADED |
| foreign-key rows | retain PRAGMA outcome | add `foreign_key` | DEGRADED |
| legacy rows | retain PRAGMA outcome | exact stale issue + exact rows | DEGRADED |

Ordinary Facade `deep=False` calls therefore retain quick-check behavior. Issue output is unique and UTF-8-byte sorted.

### 2.3 Shared infrastructure opener and full call graph

`storage.py` owns one shared internal function:

```python
def open_read_only_sqlite(
    database: Path, *, named_rows: bool = False, timeout_seconds: float = 0.25
) -> sqlite3.Connection: ...
```

It rejects missing, reparse/symlink, and non-regular DB paths before open; uses SQLite URI `mode=ro`, `uri=True`, and `PRAGMA query_only=ON`; never uses `immutable=1`; applies bounded busy timeout; closes on configuration failure. Both `_read_database_metadata()` and `SQLiteProjectStore._read()` use it. Write paths keep their existing writer connection.

Complete inspected-project call graph:

```text
main._doctor
-> doctor.run_doctor fixed error boundary
-> build_composition(project_root), without start/context entry
-> diagnose_project(application, store, project_root, deep)
   -> ApplicationFacade.health_check(HealthCheckRequest())
      -> inspect_project_state
         -> load_storage_metadata
            -> _read_database_metadata -> open_read_only_sqlite
         -> SQLiteProjectStore._read -> open_read_only_sqlite
      -> inspect_integrity(False) -> same read-only paths
   -> ApplicationFacade.list_capabilities(ListCapabilitiesSummaryRequest())
      -> inspect_project_state + inspect_integrity(False) -> same paths
   -> ProjectStore.inspect_integrity(deep) -> same paths
   -> packaged Schema/hash and packaged Codex-template reads
```

`doctor.py` must not import `sqlite3`, access Store private paths/connections, or call bootstrap/migrate/repair/start/start_writer_session. `run_doctor()` catches unsafe/missing/unreadable root and composition failures and emits one finite UNSAFE report, never a traceback.

Tests prove no DML/DDL, lock acquisition, authoritative byte change, new WAL/SHM, or temp residue for every branch; existing sidecars, if fixture-provided, remain byte-identical. Read-only open rejects reparse/non-regular paths fail-closed.

## 3. Resolution R2: strict doctor document

### 3.1 Packaged authority

Schema path and identity are exact:

```text
src/modeling_cli/schemas/doctor/0.1.0/report.schema.json
https://schemas.math-modeling-mcp.local/cli/doctor/0.1.0/report.schema.json
modeling-doctor-report/0.1.0
```

Schema is Draft 2020-12, meta-valid, offline-loadable via `importlib.resources.files("modeling_cli")`, and absent from `SchemaCatalog`. Top object is strict with required fields:

```text
schema_version, status, exit_code, project_state,
ready_for_project_creation, deep, checks, storage
```

`status/exit_code` is exactly READY/0, WARNING/1, or UNSAFE/2. `project_state` is one of the four existing states. `storage` is strict and requires `check`, `issues`, and all three legacy arrays. `issues` uses the eight finite codes, is unique, max 8. Legacy arrays are unique, max 100; stale operation `tool_name` uses the two-value enum. IDs copy the canonical UUIDv4 pattern into local `$defs`.

### 3.2 Canonical checks and codes

Base reports contain the first 11 checks in this order; `deep=true` appends the final two. No other check/code is legal.

| Order/name | PASS codes | WARN codes | FAIL codes |
| --- | --- | --- | --- |
| 1 `project-root` | `available` | — | `unsafe`, `unreadable` |
| 2 `project-state` | `storage_ready`, `ready` | `uninitialized` | `degraded` |
| 3 `application-health` | `healthy` | — | `degraded`, `unavailable` |
| 4 `capability-registry` | `sealed` | — | `invalid`, `unavailable` |
| 5 `storage-integrity` | `not_initialized`, `ok` | — | `not_executed_degraded`, `check_failed`, `check_error` |
| 6 `foreign-keys` | `not_initialized`, `ok` | — | `not_executed_degraded`, `foreign_key_failure`, `unavailable` |
| 7 `legacy-attempts` | `not_initialized`, `none` | — | `not_executed_degraded`, `stale_attempt`, `unavailable` |
| 8 `legacy-validations` | `not_initialized`, `none` | — | `not_executed_degraded`, `stale_validation`, `unavailable` |
| 9 `legacy-operations` | `not_initialized`, `none` | — | `not_executed_degraded`, `stale_operation`, `unavailable` |
| 10 `schema-assets` | `hashes_match` | — | `hash_mismatch`, `unavailable` |
| 11 `codex-config` | `valid` | — | `invalid`, `unavailable` |
| 12 `deep-lock-smoke` | `passed` | — | `busy_classification_mismatch`, `failed` |
| 13 `deep-root-smoke` | `passed` | — | `result_mismatch`, `validation_failed`, `failed` |

Health `OK` maps to doctor PASS/`healthy`; health `DEGRADED` maps to FAIL/`degraded`. Schema conditionals bind every name to its finite code set and enforce base/deep length and prefix order; producer tests enforce UTF-8 order where Schema cannot.

State mapping is total:

- UNINITIALIZED -> WARNING/1, `ready_for_project_creation=true`; only `project-state` WARN, non-applicable storage checks PASS/`not_initialized`.
- healthy STORAGE_READY -> READY/0, `ready_for_project_creation=true`.
- healthy READY -> READY/0, `ready_for_project_creation=false`.
- DEGRADED, any legacy row, Store FAIL/ERROR, foreign-key failure, version/hash mismatch, lock ambiguity, or deep-smoke failure -> UNSAFE/2, ready false.
- unsafe/unreadable root or pre-composition failure -> strict UNSAFE/2 with synthesized DEGRADED, finite unavailable/failure codes, empty legacy arrays; no path text.

Schema validation precedes JSON and human rendering. Any Schema load/meta/instance failure emits no stdout, exactly `MODELING_DOCTOR_SCHEMA_INVALID\n` to stderr, and exits 2.

`src/modeling_cli/templates/codex/config.toml` is canonical runtime authority,
loaded offline with `importlib.resources.files("modeling_cli")`.
`docs/templates/codex/config.toml` is mandatory byte-identical copy for users.
Doctor validates packaged bytes; acceptance validates both files have identical
bytes and SHA-256. Installed-wheel tests must not depend on repository `docs/`.

### 3.3 Deep smoke sequence

```text
TemporaryDirectory
-> bootstrap temporary root
-> build owner composition
-> enter/start owner
-> create project
-> run exact golden root experiment
-> validate SUCCEEDED/PASSED and residual contract
-> start second temporary composition while owner holds lease
-> require fixed CONFLICT/project_busy classification
-> close contender and owner in finally
-> remove TemporaryDirectory
```

Every failure closes both compositions and removes only the owned temp root. The inspected project lock is never touched.

## 4. Resolution R3: failure-capable A-01–A-10 map

### 4.1 Types and two phases

`evidence.py` owns types/validation; `verify.py` owns one literal policy tuple.

```python
@dataclass(frozen=True, slots=True)
class EvidenceReference:
    artifact: Literal[
        "verification-report.json", "architecture-report.json",
        "source-inventory.json", "package-assets.json",
        "stdio-transcript.json", "golden-trace.json",
    ]
    json_pointer: str

@dataclass(frozen=True, slots=True)
class RequiredTestNode:
    selector: str
    match: Literal["exact", "family"]

@dataclass(frozen=True, slots=True)
class AcceptanceClause:
    clause_id: str
    required_nodes: tuple[RequiredTestNode, ...]
    check_ids: tuple[str, ...]
    success_evidence: tuple[EvidenceReference, ...]

@dataclass(frozen=True, slots=True)
class AcceptanceRequirement:
    acceptance_id: Literal["A-01", "A-02", "A-03", "A-04", "A-05", "A-06", "A-07", "A-08", "A-09", "A-10"]
    clauses: tuple[AcceptanceClause, ...]

def validate_m1a_acceptance_policy(
    *, requirements: Sequence[AcceptanceRequirement],
    allowed_check_ids: Sequence[str]
) -> None: ...

def materialize_m1a_acceptance_map(
    *, requirements: Sequence[AcceptanceRequirement],
    base_report: Mapping[str, object],
    artifact_documents: Mapping[str, object],
    observed_test_outcomes: Mapping[
        str, Mapping[str, Literal["PASSED", "FAILED", "SKIPPED"]]
    ],
) -> JsonObject: ...
```

Phase 1 runs before checks. It validates policy shape and syntax only: wrong/missing/duplicate A IDs or clause IDs, empty/duplicate/unsorted nodes/checks/references, malformed/nonliteral node IDs, unknown declared check IDs/artifacts, malformed/recursive pointers, or incomplete clause coverage. It does not claim a node exists or ran. Structural failures are prerequisite exit 2.

Phase 2 runs after all checks. `base_report` has the ten legacy 0.1.0 keys and no `acceptance_map`. `artifact_documents` has exactly six JSON filename keys and maps `verification-report.json` to that base report. It resolves pointers against parsed documents, forbids report pointers beginning `/acceptance_map`, compares map/base fingerprints, then attaches the map and validates the exact 11-key report.

Materialization reconciles `observed_test_outcomes` keys exactly with each
current-run pytest check's strict `test_nodes`. `exact` selector `B` matches
only exact node `B`. `family` selector `B` matches exactly `B` or a node whose
string is `B + "[" + parameter_id + "]"`; prefix-only matches such as
`B_extra` are forbidden. Parameter IDs remain present in exact observed nodes.
Each required family needs at least one observed member, every observed member
needs one outcome, and all members must be PASSED. No observed member, missing
outcome/member evidence, rename, FAILED, or SKIPPED makes that clause and
A-entry FAIL. These are executed-evidence failures/exit 1, never structural
prerequisites.

Executed check failure, required skip, golden failure, wheel failure, or source drift never raises a policy prerequisite. Each entry emits `status: PASS|FAIL`. PASS requires every clause node to be observed by its owner, every owning check PASS with zero skips, and every success pointer to resolve. FAIL points to affected base-report `/checks/<index>/status`, `/test_nodes`, and `/diagnostic_code`; golden failure also points to transcript/trace `/status` and `/diagnostic_code`; source drift makes A-10 FAIL with base `/status` and `/source_fingerprint` evidence.

Final PASSED/0 requires 15 PASS checks, zero required skips, empty incomplete groups, no drift, and ten PASS map entries. Any executed failure yields FAILED/1 and a valid fingerprinted exact-seven-file `m1a-verification-report/0.2.0` bundle. Structural policy failure remains exit 2.

The embedded map has exactly `schema_version`, `source_fingerprint`, and
`entries`; each entry has exactly `acceptance_id`, `status`, `test_nodes`, and
`evidence`; each evidence item has exactly `artifact` and `json_pointer`.
Each `test_nodes` item has exactly `selector`, `match`, and `observed_nodes`;
`observed_nodes` retains exact parameter IDs and is UTF-8-byte sorted.
Pre-report and publication-seam source drift both rebuild the base status and
materialize A-10 as FAIL before atomic publication.

### 4.2 Pointer policy

- Versioned object artifacts require `/schema_version` plus semantic pointers.
- Bare `source-inventory.json` and `package-assets.json` arrays use empty pointer `""`; named Harness validators prove membership, never a row index.
- `verification-report.json` resolves only against `base_report`.
- `SUMMARY.md` is excluded.
- Policy, node, clause, reference, issue, and row strings use UTF-8-byte ordering.

Acceptance tests use synthetic documents only: they never read current `build/verification`, invoke `modeling verify`, or depend on current evidence. Parent Harness alone validates current fingerprint, current artifact docs, pointers, and final map after checks.

### 4.3 Clause-complete literal node policy

Before `_M1A_ACCEPTANCE_REQUIREMENTS` is written, RED tests must define these exact selectors. Committed policy contains these literals, no generated wildcard or placeholder. Every selector is `exact` except the explicitly marked A-06/A-09 families. Each semicolon-delimited Phase 0 clause has an `AcceptanceClause`; mutation tests delete every clause's sole evidence node in turn.

| ID | Required literal pytest nodes | Owning checks |
| --- | --- | --- |
| A-01 | `tests/acceptance/test_m1a_acceptance_map.py::test_a01_windows_locked_toolchain_is_current_and_offline`; `tests/integration/test_bootstrap_sqlite.py::test_uninitialized_bootstrap_creates_exact_storage_ready_layout`; `tests/integration/test_bootstrap_sqlite.py::test_repeat_bootstrap_returns_same_id_without_changing_any_bytes`; `tests/unit/test_doctor.py::test_uninitialized_is_warning_and_storage_ready_and_ready_are_ready` | `uv-lock`, `pytest-integration`, `pytest-unit`, `pytest-acceptance` |
| A-02 | `tests/integration/test_stdio_golden_m1a.py::test_official_client_completes_m1a_golden_chain_records_protocol_purity_and_closes_child`; `tests/integration/test_stdio_golden_m1a.py::test_official_client_exception_path_closes_child_and_releases_writer_lease` | `stdio-golden`, `pytest-integration` |
| A-03 | `tests/integration/test_stdio_golden_m1a.py::test_official_client_completes_m1a_golden_chain_records_protocol_purity_and_closes_child`; `tests/integration/test_application_workflow.py::test_six_use_cases_reconstruct_a_validated_root_finding_trace`; `tests/unit/test_doctor.py::test_doctor_uses_shared_facade_and_store_without_starting_inspected_composition`; `tests/architecture/test_dependency_boundaries.py::test_core_never_imports_adapters_databases_or_capabilities` | `stdio-golden`, `pytest-integration`, `pytest-unit`, `pytest-architecture` |
| A-04 | `tests/unit/test_registry.py::test_capability_and_compatible_validator_register_before_seal`; `tests/architecture/test_composition_root.py::test_composition_seals_the_exact_builtin_registry_and_sole_store` | `pytest-unit`, `pytest-architecture` |
| A-05 | `tests/integration/test_stdio_golden_m1a.py::test_official_client_completes_m1a_golden_chain_records_protocol_purity_and_closes_child`; `tests/unit/root_finding/test_validator.py::test_golden_success_is_passed_with_exact_metrics_and_hashes` | `stdio-golden`, `pytest-unit` |
| A-06 | exact `tests/integration/test_application_workflow.py::test_numerical_failure_is_durable_and_replayable`; exact `tests/integration/test_application_workflow.py::test_pre_execution_rejections_leave_zero_provenance`; family `tests/unit/expression/test_canonicalization.py::test_forbidden_expressions_map_to_security_violation` | `pytest-integration`, `pytest-unit` |
| A-07 | `tests/unit/root_finding/test_validator.py::test_self_consistent_forged_result_hash_still_fails_mathematically`; `tests/architecture/test_solver_validator_independence.py::test_validator_real_import_graph_has_only_explicitly_allowed_modules` | `pytest-unit`, `pytest-architecture` |
| A-08 | `tests/integration/test_application_workflow.py::test_six_use_cases_reconstruct_a_validated_root_finding_trace`; `tests/contract/test_project_store.py::test_trace_query_and_trace_enforce_all_parent_and_uniqueness_relations` | `pytest-integration`, `pytest-contract` |
| A-09 | exact `tests/integration/test_application_workflow.py::test_completed_write_replay_is_side_effect_free`; exact `tests/integration/test_application_workflow.py::test_write_idempotency_mismatch_fails_without_new_entities`; family `tests/unit/expression/test_canonicalization.py::test_forbidden_expressions_map_to_security_violation`; exact `tests/security/test_m1a_boundaries.py::test_request_larger_than_one_mib_is_rejected_before_newline`; exact `tests/security/test_m1a_boundaries.py::test_cooperative_deadline_rejects_work_at_the_exact_boundary`; exact `tests/security/test_m1a_boundaries.py::test_project_lock_is_exclusive_and_reusable_after_release`; family `tests/security/test_m1a_boundaries.py::test_public_mcp_contract_rejects_every_untrusted_path_surface` | `pytest-integration`, `pytest-unit`, `pytest-security` |
| A-10 | `tests/acceptance/test_m1a_acceptance_map.py::test_m1a_context_config_and_acceptance_map_are_complete`; `tests/acceptance/test_m1a_acceptance_map.py::test_m1a_abstraction_budget_and_exact_context_inventory_are_binding`; `tests/acceptance/test_m1a_acceptance_map.py::test_doctor_schema_and_codex_template_are_installed_offline_without_core_catalog_drift`; `tests/reproducibility/test_m1a_repeatability.py::test_a12_profile_and_report_transition_preserve_a11_evidence_contract` | `pytest-acceptance`, `pytest-reproducibility`, `wheel` |

## 5. Harness and package transition

Check order is exact:

```text
uv-lock, ruff-check, ruff-format, mypy, pytest-unit, pytest-contract,
pytest-math, pytest-architecture, pytest-integration, pytest-reproducibility,
pytest-security, pytest-smoke, pytest-acceptance, wheel, stdio-golden
```

`pytest-smoke` and `pytest-acceptance` each use 180 seconds. Existing 13 checks retain relative order. Required skips remain zero.

JUnit parsing is current-run authority. For each pytest check, parse every
`testcase`, find the longest `classname` prefix resolving to a repository test
module, append remaining class components and exact parameterized `name`, then
normalize to NFC forward-slash `path.py::Class::test[param]`. Reject controls,
backslashes, absolute/parent paths, non-`tests/` paths, malformed components,
duplicates, nodes over 512 UTF-8 bytes, or more than 4096 nodes. Preserve
per-node outcome internally. `_CheckResult` and report 0.2 check objects add
`test_nodes`: UTF-8-byte-sorted unique array for pytest checks, `null` for
non-pytest checks. Failed/skipped cases remain observed with exact parameter
IDs but cannot satisfy a required exact node or family. JUnit node parse failure is an executed check FAIL with a
finite diagnostic, not a prerequisite error.

Keep seven filenames. Report changes from `m1a-verification-report/0.1.0` to `0.2.0`; retain all ten old keys and add exactly `acceptance_map` with `m1a-acceptance-map/0.1.0`. Legacy five-entry `artifacts` map does not gain self-reference.

Add exactly `modeling_cli/schemas/doctor/0.1.0/report.schema.json` and `modeling_cli/templates/codex/config.toml` to non-Python package assets: 32 -> 34. Synthetic wheel total: 85 -> 87. Seven unique roots remain. Tests assert both literal paths and both final raw-byte SHA-256 constants, not self-derived expected hashes; docs template bytes/hash equal packaged template.

Mutation matrix must cover: check FAIL; required skip; golden FAIL; wheel FAIL; source drift; exact node removed/renamed/not run while broad group remains PASS; required family with no member; one observed family member missing outcome evidence; one family member FAILED; one family member SKIPPED; complete multi-member family PASS with all exact parameter IDs retained; malformed/duplicate/over-limit JUnit node; duplicate A ID; missing/recursive pointer; missing transcript/trace; eighth artifact; silent 0.1.0 mutation; acceptance test reading current evidence; acceptance test invoking verify. Executed failures publish valid exact-seven bundles.

## 6. Implementation slices, review gates, commits

New RED node names are fixed before production/policy edits:

- Store: `tests/contract/test_project_store.py::test_integrity_report_dtos_are_finite_unique_bounded_and_utf8_ordered`; `tests/contract/test_project_store.py::test_inspect_integrity_selects_exact_check_and_reports_legacy_rows`.
- Read-only integration: `tests/integration/test_read_only_diagnostics.py::test_all_doctor_storage_reads_are_mode_ro_query_only_and_leave_no_sidecars`; `tests/integration/test_read_only_diagnostics.py::test_read_only_sqlite_opener_rejects_reparse_and_nonregular_database_paths`; `tests/integration/test_read_only_diagnostics.py::test_integrity_error_and_overflow_branches_fail_closed_with_finite_codes`.
- Doctor: `tests/unit/test_doctor.py::test_uninitialized_is_warning_and_storage_ready_and_ready_are_ready`; `tests/unit/test_doctor.py::test_degraded_legacy_and_integrity_failures_are_unsafe`; `tests/unit/test_doctor.py::test_doctor_uses_shared_facade_and_store_without_starting_inspected_composition`; `tests/unit/test_doctor.py::test_doctor_schema_is_strict_versioned_finite_and_packaged`; `tests/unit/test_doctor.py::test_build_composition_failures_render_one_redacted_unsafe_report`; `tests/unit/test_doctor.py::test_schema_validation_failure_is_stderr_only_and_exit_two`; `tests/unit/test_doctor.py::test_deep_doctor_runs_owned_root_and_lock_smokes_then_cleans_up`.
- Boundary: `tests/architecture/test_dependency_boundaries.py::test_doctor_has_no_sql_or_inspected_writer_side_effects`; `tests/security/test_m1a_boundaries.py::test_doctor_rejects_unsafe_root_without_traceback_or_path_disclosure`.
- Acceptance/Harness: the exact A-nodes in section 4.3 plus `tests/acceptance/test_m1a_acceptance_map.py::test_acceptance_policy_mutations_reject_each_a_clause`; `tests/acceptance/test_m1a_acceptance_map.py::test_acceptance_map_materializes_pass_and_failure_documents`; `tests/acceptance/test_m1a_acceptance_map.py::test_parameterized_family_requires_complete_passing_current_run_evidence`; `tests/acceptance/test_m1a_acceptance_map.py::test_acceptance_map_rejects_recursive_or_current_evidence_dependencies`; `tests/reproducibility/test_m1a_repeatability.py::test_junit_parser_records_strict_normalized_exact_test_nodes`; `tests/reproducibility/test_m1a_repeatability.py::test_missing_or_renamed_current_run_literal_node_forces_fingerprinted_failed_bundle`; `tests/reproducibility/test_m1a_repeatability.py::test_a12_failure_mutations_publish_exact_seven_file_failed_bundles`.

### Slice A12.1: read-only Store correction

- [ ] Add REDs in Store contract, `test_read_only_diagnostics.py`, security, and architecture for DTO validation, exact PRAGMA modes, all finite branches, full call graph, reparse/non-regular rejection, and zero writes/sidecars/locks.
- [ ] Run focused tests; record expected failures before editing production.
- [ ] Implement minimal DTO/opener/Store changes.
- [ ] Run focused tests, full Store/application regressions, Ruff, MyPy.
- [ ] Independent spec review: no second port, doctor SQL, write connection, or core SQLite import.
- [ ] Commit only GREEN reviewed slice: `fix: make project diagnostics strictly read only`.

### Slice A12.2: doctor Schema and orchestration

- [ ] Add REDs in `tests/unit/test_doctor.py` with exact names from section 4 plus strict Schema branches, fixed stderr failure, root error boundary, lossless Store serialization, and deep cleanup.
- [ ] Implement packaged Schema, `diagnose_project`, `run_doctor`, CLI wiring, canonical human/JSON rendering.
- [ ] Run doctor unit/integration/security/architecture tests and real bootstrap -> deep doctor command.
- [ ] Independent review: finite/redacted report; no inspected composition start; exact state/exit map; deep owned lifecycle.
- [ ] Commit: `feat: add strict read-only project doctor`.

### Slice A12.3: minimum context and Codex template

- [ ] Add structural REDs for exact AGENTS/docs/link inventory, authority routing, M1 scope/abstraction budget, one M1a-0 plus A1-A12 headings, and exact trusted-project Codex TOML.
- [ ] Create only original A12 context/docs/template files; update README last.
- [ ] Run acceptance/static link/TOML tests and independent docs/config review.
- [ ] Commit: `docs: establish the M1a context contracts`.

### Slice A12.4: acceptance map and final gate

- [ ] Add REDs fixing every section-4 node name before policy code; add synthetic two-phase/pointer/failure mutation tests and narrow A11 transition REDs.
- [ ] Implement JUnit exact-node capture, policy validation, current-run acyclic materialization, report 0.2.0, 15-check profile, 34/87 package transition, and empty A12 incomplete group.
- [ ] Run focused acceptance/reproducibility/Harness tests; run real verify and inspect all seven files.
- [ ] Independent Harness review: failure bundles, no recursion/current evidence, exact nodes/pointers/order/counts, A11 no-clobber/source-drift preservation.
- [ ] Commit: `test: close the M1a acceptance evidence gate`.

Any review correction gets a failing regression first, focused re-review, and separate `fix:` commit. No slice may borrow files from the next slice to obtain GREEN.

## 7. Final commands and acceptance

```powershell
uv run --locked --no-sync pytest tests/unit/test_doctor.py tests/contract/test_project_store.py tests/integration/test_read_only_diagnostics.py tests/acceptance/test_m1a_acceptance_map.py tests/reproducibility/test_m1a_repeatability.py -q
uv run --locked --no-sync modeling bootstrap --project-root tests/.tmp/a12-doctor-project
uv run --locked --no-sync modeling doctor --project-root tests/.tmp/a12-doctor-project --deep --json
uv run --locked --no-sync modeling verify --milestone m1a
uv run --locked --no-sync pytest tests -q
uv run --locked --no-sync ruff check src tests
uv run --locked --no-sync ruff format --check src tests
uv run --locked --no-sync mypy src
python -m compileall -q src tests
git diff --check
git status --short
```

Final PASS requires doctor exit 0 for healthy STORAGE_READY after bootstrap, exact 15/15 Harness PASS, required skips 0, empty incomplete groups, A-01..A-10 PASS with current-run exact-node proof, exact seven evidence files, report/map 0.2.0/0.1.0, 34 non-Python assets, 87 synthetic wheel items, packaged/docs template byte identity, unchanged core catalog/18 tool Schemas, ignored evidence output, and clean source tree.

## 8. Review traceability

| Review finding | Binding sections |
| --- | --- |
| C1 failure publication | 4.1, 5 |
| C2 acyclic report/artifact inputs | 4.1-4.2 |
| C3 complete read-only graph | 2.3, 3.2 |
| I1 finite DTO/branches | 2.1-2.2 |
| I2 doctor issues/check/state map | 3.1-3.2 |
| I3 clause-complete literal nodes | 4.3 |
| I4 bare-array pointers | 4.2 |
| I5 no current/recursive evidence tests | 4.2, 5 |
| I6 deep lifecycle | 3.3 |
| I7 34/87 package transition | 5 |
| M1 UTF-8 order | Global Constraints, 2.1, 4.2 |
| M2 Schema failure stdout/stderr | 3.2 |
| Addendum review C1 current-run node evidence | 4.1, 4.3, 5 |
| Addendum review I1 installed template authority | 1, 3.2, 5 |
| Addendum fix2 C1 parameterized family evidence | 4.1, 4.3, 5 |
