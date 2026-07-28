# Task A6 report — safe canonical math expression input

## Scope and base

- Base commit: `604482e323e1479348844dbd2dd46ed7c9ac9c13`
- Scope: Task A6 only; no A7 solver, descriptor, result/failure contract, or
  orchestration work was started.
- Repository guidance: no root or nested `AGENTS.md` was present.

## TDD evidence

Initial RED command:

```powershell
uv run --locked --no-sync pytest tests/unit/expression/test_syntax.py tests/unit/expression/test_canonicalization.py -q
```

Initial result: exit 1 during collection with exactly 2 errors and 0 tests
run. Both errors were the expected
`ModuleNotFoundError: No module named 'modeling_capabilities.root_finding'`.
The focused schema/corpus test independently failed for the same missing
package.

Additional RED regressions were captured before their fixes:

- typed evaluator failures: collection failed because the two new failure
  classes did not exist;
- Unicode digits: 2 failed and 2 passed before the ASCII-only scanner fix;
- fixed parser caps: 4 failed before caller-supplied limits were bounded;
- forged canonical power exponents: 1 failed before Schema enforcement;
- invalid compound power mapping: 2 failed before pre-traversal validation;
- 1000 redundant parentheses: 1 failed with a false AST-depth error before
  iterative redundant-shell collapse.

## Fresh GREEN and verification evidence

- Unit GREEN:
  `uv run --locked --no-sync pytest tests/unit/expression/test_syntax.py tests/unit/expression/test_canonicalization.py -q`
  — **142 passed**.
- Focused contract gate:
  `uv run --locked --no-sync pytest tests/unit/expression/test_syntax.py tests/unit/expression/test_canonicalization.py tests/contract/test_capability_schemas_v0.py -q`
  — **146 passed**.
- A6 lint:
  `uv run --locked --no-sync ruff check src/modeling_capabilities/root_finding tests/unit/expression`
  — **all checks passed**.
- Authorized contract-test lint:
  `uv run --locked --no-sync ruff check tests/contract/test_capability_schemas_v0.py`
  — **all checks passed**.
- Strict typing:
  `uv run --locked --no-sync mypy src/modeling_capabilities/root_finding`
  — **no issues in 6 source files**.
- Required regression:
  `uv run --locked --no-sync pytest tests/unit/contracts tests/unit/expression tests/contract/test_capability_schemas_v0.py -q`
  — **172 passed**.
- Additional full locked suite:
  `uv run --locked --no-sync pytest -q`
  — **346 passed**.

## Changed files and diff audit

Created:

- `src/modeling_capabilities/root_finding/__init__.py`
- `src/modeling_capabilities/root_finding/contracts.py`
- `src/modeling_capabilities/root_finding/context.md`
- `src/modeling_capabilities/root_finding/expression/__init__.py`
- `src/modeling_capabilities/root_finding/expression/syntax.py`
- `src/modeling_capabilities/root_finding/expression/solver_evaluator.py`
- `src/modeling_capabilities/root_finding/expression/validator_evaluator.py`
- `src/modeling_capabilities/root_finding/schemas/0.1.0/input.schema.json`
- `src/modeling_capabilities/root_finding/schemas/0.1.0/canonical-input.schema.json`
- `tests/unit/expression/test_syntax.py`
- `tests/unit/expression/test_canonicalization.py`
- `tests/contract/corpus/root-finding/0.1.0.json`
- this report

Modified:

- `tests/contract/test_capability_schemas_v0.py`

Final staged diff stat: **14 files changed, 2532 insertions**.

`git diff --check` passed with no whitespace errors.

## Dependency and lock status

- `pyproject.toml`: unchanged.
- `uv.lock`: unchanged.
- No dependencies were added or updated.

## Deviations and concerns

- No A6 design deviation is known.
- The initial shallow-freeze concern was resolved in fix round 1 by storing
  canonical payloads and data references as canonical bytes and returning
  freshly decoded copies.
- UTF-8 byte length is enforced by normalization before tokenization. JSON
  Schema's `maxLength` remains a character-count declaration because Draft
  2020-12 has no UTF-8-byte-length keyword.

## Fix round 1 — independent-review findings

Fix base: `ffa1a05b9e65bd9cbcd0ebb8281797dab5e819ae`.

### RED evidence

- Canonical AST reconstruction: the A6 expression command exited 1 with
  exactly 2 collection errors because `ast_from_canonical_json` did not exist.
- Deep immutability: 1 focused core-contract test failed because mutating a
  returned nested AST/root dictionary changed the record's canonical bytes.
- Direct-AST depth: 2 focused evaluator tests failed because both evaluator
  paths accepted depth 33.
- Lossy binary64 forgery: 1 of 17 forged-value cases failed because
  integer `9007199254740993` was silently rounded.

### Implemented corrections

- Added and exported strict `ast_from_canonical_json`, covering exact six-node
  shapes, finite/exact binary64 conversion, signed-zero normalization, power
  restrictions, and hard 256-node/32-depth limits. Normalized records now
  reconstruct and evaluate without persisted expression text.
- Sealed `CanonicalInputRecord.canonical_payload` and every data snapshot
  reference behind immutable canonical bytes. Direct construction,
  `model_validate`, public getters, aliases, and `model_dump(mode="json")`
  retain their public shapes while every getter returns a fresh decoded copy.
- Added independent direct-AST depth tracking to both evaluator traversals.
  Balanced depth-safe ASTs with exactly 256 nodes remain accepted; node 257
  and depth 33 fail closed.

### Fresh fix-round gates

- Unit:
  `uv run --locked --no-sync pytest tests/unit/expression/test_syntax.py tests/unit/expression/test_canonicalization.py -q`
  — **173 passed**.
- Focused:
  `uv run --locked --no-sync pytest tests/unit/expression/test_syntax.py tests/unit/expression/test_canonicalization.py tests/contract/test_capability_schemas_v0.py -q`
  — **177 passed**.
- Expanded lint:
  `uv run --locked --no-sync ruff check src/modeling_capabilities/root_finding src/modeling_core/contracts/capability.py tests/unit/expression tests/unit/contracts/test_common_types.py`
  — **all checks passed**.
- Expanded strict typing:
  `uv run --locked --no-sync mypy src/modeling_core/contracts/capability.py src/modeling_capabilities/root_finding`
  — **no issues in 7 source files**.
- Exact regression:
  `uv run --locked --no-sync pytest tests/unit/contracts tests/unit/expression tests/contract/test_capability_schemas_v0.py -q`
  — **204 passed**.
- Full locked suite:
  `uv run --locked --no-sync pytest -q`
  — **378 passed**.

Fix-round staged diff stat: **10 files changed, 641 insertions, 26 deletions**.
