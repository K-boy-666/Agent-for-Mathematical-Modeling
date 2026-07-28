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
- The existing core `CanonicalInputRecord` freezes the record but not nested
  dictionaries. Per the approved A6 boundary, no core deep-freezing change was
  made; hashes are computed from the canonical payload before return.
- UTF-8 byte length is enforced by normalization before tokenization. JSON
  Schema's `maxLength` remains a character-count declaration because Draft
  2020-12 has no UTF-8-byte-length keyword.
