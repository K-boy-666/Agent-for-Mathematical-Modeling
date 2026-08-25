# Task A8 implementation report

## Scope

Implemented only Task A8: the independent
`numerical.root_finding.residual/0.1.0` validator, strict policy and report
schemas, capability advertisement, hand-built forged-result fixtures,
mathematical/control/schema tests, and a fail-closed transitive import-graph
guard.

The validator accepts only a verified committed `ResultSnapshotView`; A9
still owns persistence re-read, expected-result-hash comparison, terminal
state mapping, and application orchestration.

## TDD evidence

Initial RED, before any production implementation:

```text
uv run --locked --no-sync pytest tests/unit/root_finding/test_validator.py tests/architecture/test_solver_validator_independence.py -q
exit 1
2 collection errors
ModuleNotFoundError: modeling_capabilities.root_finding.validator
```

The minimum validator module, schemas, and descriptor projection made the
focused behavioral contract GREEN. Subsequent test-driven tightening added
the strict inner result-kind precondition and real transitive import closure.

## Final verification

```text
uv run --locked --no-sync pytest tests/unit/root_finding/test_validator.py tests/architecture/test_solver_validator_independence.py tests/contract/test_capability_schemas_v0.py -q
exit 0 — 60 passed, 0 failed, 0 skipped

uv run --locked --no-sync ruff check src/modeling_capabilities/root_finding tests/unit/root_finding tests/architecture/test_solver_validator_independence.py tests/fixtures/forged_results.py
exit 0 — All checks passed

uv run --locked --no-sync mypy src/modeling_capabilities/root_finding
exit 0 — 9 source files, no issues

uv run --locked --no-sync pytest tests/unit/expression tests/unit/root_finding tests/math tests/architecture/test_solver_validator_independence.py -q
exit 0 — 268 passed, 0 failed, 0 skipped

uv run --locked --no-sync pytest -q
exit 0 — 483 passed, 0 failed, 0 skipped
```

`pyproject.toml` and `uv.lock` are unchanged.

## Authorized deviations

The parent agent approved two narrow corrections to the original A8 file
list:

1. `tests/unit/root_finding/test_solver.py` replaces A7's temporary
   `validators == ()` expectation with the A8 residual summary.
2. The same test-local registry setup registers the now-advertised A8
   validator before sealing.

No A7 solver behavior or registry semantics changed.

## Commit

```text
feat: add independent residual validation
```

The full commit hash is recorded in the post-commit handoff; a commit cannot
embed its own content-derived hash.

## Known deviations

None. Task A8 remains subject to a separate read-only task review before A9
is authorized.
