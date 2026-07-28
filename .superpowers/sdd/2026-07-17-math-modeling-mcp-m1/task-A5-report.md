# Task A5 Report — sealed explicit Built-in Capability registry

## Scope and baseline

- Task: A5 only.
- Starting commit:
  `670e8e00232b9d34edace9270f96b597ce5e386a`.
- The worktree was clean at the exact starting commit.
- Read before implementation:
  - the complete authoritative `task-A5-brief.md`;
  - design §§9.1–9.7;
  - the plan's exact `BuiltInCapability`, `CapabilityValidator`, context, and
    `CapabilityRegistry` method signatures;
  - A2 canonical JSON, schema catalog, error, common, and version contracts;
  - A3 ports and domain contracts;
  - the A4 explicit-Hatchling-package correction and its evidence.
- Did not implement or begin A6+, concrete mathematics, discovery, storage,
  MCP, installation, or an External Plugin type.

## TDD evidence

### Required missing-registry RED

The two authorized test files were created before production code:

- `tests/unit/test_registry.py`
- `tests/contract/test_capability_schemas_v0.py`

Command:

```powershell
uv run --locked --no-sync pytest tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py -q
```

Exit code: `1`.

Observed:

```text
ERROR tests/unit/test_registry.py
ModuleNotFoundError: No module named 'modeling_core.contracts.capability'
ERROR tests/contract/test_capability_schemas_v0.py
ModuleNotFoundError: No module named 'modeling_core.contracts.capability'
2 errors in 0.46s
```

This was the brief's planned missing-contract/registry collection failure.

### Self-review RED/GREEN cycles

Deep seal and range review added two focused tests after the first GREEN:

```text
test_every_declared_validator_contract_range_must_be_compatible
test_descriptor_nested_schemas_and_validator_summaries_are_deeply_immutable
```

Before the fix: `2 failed in 0.43s`. The first exposed an any-range-match
shortcut; the second exposed mutable nested Schema and validator-summary
dictionaries. After canonical-byte storage and per-range validation:
`2 passed in 0.40s`.

The capability descriptor's validator summaries are complete
`ValidatorSummary` records, not IDs. A focused hash test proved their nested
policy/report Schemas were not initially revalidated during seal:
`1 failed in 0.44s`. Seal now checks each summary reference's Draft, root,
and declared hash: `1 passed in 0.37s`.

A focused projection test proved capability validator-summary versions and
hashes were initially absent from the fingerprint: `1 failed in 0.61s`.
They are now deterministically sorted into the fingerprint projection:
`2 passed in 0.73s`, including the literal full-projection test.

The packaged common Schema IDs were aligned to the existing A2 convention.
The contract test first failed with three missing conventional IDs, then
passed all three cases after the assets and registry constants were corrected.

## Implemented behavior

- `BuiltInCapability` and `CapabilityValidator` are runtime-checkable,
  host-neutral structural protocols with the approved method signatures.
- Capability/validator descriptors and M1a execution/validation contexts are
  frozen. Nested Schemas and validator summaries are stored internally as
  canonical immutable bytes and exposed only as fresh decoded values.
- M1a capability `artifact_roles` is strictly the empty tuple.
- Registry registration storage is exactly two dictionaries:
  exact `(capability_id, contract_version)` keys and exact
  `(validator_id, policy_version)` keys.
- Registration is possible only before seal. Capability key,
  validator/policy key, or implementation identity reuse raises
  `CONFLICT` with the existing allowed
  `conflict_type=duplicate_registration`.
- A Capability API mismatch or any individually incompatible declared
  validator range raises `UNSUPPORTED_VERSION`.
- Seal always requires `numerical.root_finding/0.1.0`, even when the caller
  supplies an empty required set.
- Seal loads the two packaged descriptor Schemas, checks all capability,
  validator, and capability-summary Schema references as Draft 2020-12 root
  objects, verifies strict root shape and declared canonical SHA-256 hashes,
  validates every range, computes the ordered version/hash projection, and
  flips one sealed boolean.
- Listing and fingerprint inputs are sorted deterministically. Resolve uses
  only the exact requested version and never selects a latest version.
- No entry-point/directory scan, dynamic import, filesystem API, package
  installation API, storage, SQLite, MCP context, or External Plugin model was
  added.

## Packaging and dependency evidence

After `src/modeling_capabilities` existed, exactly one permitted editable
refresh ran:

```powershell
uv sync --locked --group dev
```

Exit code: `0`; one local `math-modeling-mcp==0.1.0` editable package was
rebuilt and installed.

`pyproject.toml` changes only add `src/modeling_capabilities` to Hatchling's
explicit wheel package list.

Pre-sync and final `uv.lock` SHA-256:

```text
b3d3517d8d284d5e3df142cae3fa225d4f83e789213a917a0984943e8f9cac4f
```

The dependency declaration block SHA-256 remained:

```text
83e95532967825aeb64feff55cdb39e93ebf3b9467086498920a48735f2e3ef2
```

The dev dependency declaration block SHA-256 remained:

```text
d004c96d88a6a8bded0d5d6067b6ef5f54ccd445bd56a292d78c1dad5724a4af
```

`git diff --exit-code -- uv.lock` exited `0`. No generated loader or
`PYTHONPATH` workaround was created.

## Final verification

Focused:

```powershell
uv run --locked --no-sync pytest tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py -q
```

Exit code: `0`; `23 passed in 2.92s`.

Types:

```powershell
uv run --locked --no-sync mypy src/modeling_core src/modeling_capabilities
```

Exit code: `0`; `Success: no issues found in 22 source files`.

Core regressions:

```powershell
uv run --locked --no-sync pytest tests/unit/contracts tests/unit/domain tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py tests/architecture/test_dependency_boundaries.py -q
```

Exit code: `0`; `156 passed in 3.47s`.

Lint:

```powershell
uv run --locked --no-sync ruff check src/modeling_core src/modeling_capabilities tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py
```

Exit code: `0`; `All checks passed!`

## Remaining ownership

A6 and later tasks own expression/canonical-input behavior, concrete
root-finding and validator implementations, composition, application
orchestration, MCP exposure, and future Artifact support.

## Independent review fix round 1 — descriptor snapshots and validator mapping

Baseline commit:

```text
0b5ca4c6d9801a9f5f459c2a4403fabc662fb265
```

Independent review found two seal-integrity defects:

1. the registry stored live structural implementations and reread their
   descriptor properties, so a provider could replace metadata after
   registration or sealing;
2. capability-advertised validator summaries were individually validated but
   not reconciled 1:1 with independently registered validator descriptors.

### RED

Real mutable structural providers and mapping fixtures were added before the
production fix. The exact focused command:

```powershell
uv run --locked --no-sync pytest tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py -q
```

Exited `1` with `10 failed, 23 passed in 5.87s`. The failures were:

- one live descriptor replacement changed seal-time validator metadata;
- advertised-but-missing and registered-but-unadvertised validators sealed;
- policy version/hash and report version/hash mismatches sealed;
- duplicate advertised summaries and policies sealed;
- overlapping ranges produced an ambiguous mapping that sealed.

### Minimal fix

The approved two registry dictionaries remain the only registration storage.
Each value now captures a frozen pair: the original implementation object and
a deep immutable descriptor snapshot taken from the single property read at
registration. Keys, API and implementation uniqueness, Schema validation,
range checks, summaries, fingerprinting, and validator support checks use
only these snapshots. Exact resolve methods return the original
implementations.

Seal now reconciles validators independently for every exact registered
capability:

- each registered validator range must cover a real registered capability;
- each capability's advertised validator IDs and policy versions are unique;
- every advertised policy version/hash has exactly one registered match;
- report Schema version/hash matches every registered policy implementation;
- a registered supporting validator must be advertised, and every advertised
  validator must be registered;
- overlapping ranges for the same exact mapping fail as
  `CONFLICT/duplicate_registration`;
- missing, orphaned, and mismatched mappings fail as `INTEGRITY_FAILURE`.

The mutable-provider regression replaces capability and validator descriptors
both before and after seal and proves fingerprint, capability summaries,
exact capability resolution, and validator selection remain captured and
stable.

### Fix-round verification

Focused:

```powershell
uv run --locked --no-sync pytest tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py -q
```

Exit code: `0`; `33 passed in 5.40s`.

Types:

```powershell
uv run --locked --no-sync mypy src/modeling_core src/modeling_capabilities
```

Exit code: `0`; `Success: no issues found in 22 source files`.

Lint:

```powershell
uv run --locked --no-sync ruff check src/modeling_core src/modeling_capabilities tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py
```

Exit code: `0`; `All checks passed!`

Regression:

```powershell
uv run --locked --no-sync pytest tests/unit/contracts tests/unit/domain tests/unit/test_registry.py tests/contract/test_capability_schemas_v0.py tests/architecture/test_dependency_boundaries.py -q
```

Exit code: `0`; `166 passed in 6.48s`.

No dependency declaration, `pyproject.toml`, packaged Schema, `uv.lock`, or
A6+ file changed in this fix round.
