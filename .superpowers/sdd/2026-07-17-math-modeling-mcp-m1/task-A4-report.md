# Task A4 Report — atomic storage bootstrap and SQLite schema 1

## Scope and baseline

- Task: A4 only.
- Starting commit: `fcb7358c73ee39ccbf8ed73534c61198b8e47dfc`.
- Authoritative sources read before implementation:
  - `.superpowers/sdd/2026-07-17-math-modeling-mcp-m1/task-A4-brief.md`
  - corrected Task A4 in
    `docs/superpowers/plans/2026-07-17-math-modeling-mcp-m1.md`
  - design §§3.1, 8.1–8.4, 8.9–8.10, 12.1–12.2,
    15.2–15.7, and 15.12
  - committed A3 `Clock`, `IdGenerator`, `ProjectStore`, domain records,
    state enums, and `VersionSet.m1a()`
- No root or nested `AGENTS.md` existed.
- Worktree was clean at the exact starting commit.

## TDD evidence

### RED

The two authorized real-disk test files were created before the production
package:

- `tests/contract/test_project_store.py`
- `tests/integration/test_bootstrap_sqlite.py`

Command:

```powershell
uv run --locked --no-sync pytest tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py -q
```

Exit code: `1`.

Observed result:

```text
ERROR tests/contract/test_project_store.py
ModuleNotFoundError: No module named 'modeling_infrastructure'
ERROR tests/integration/test_bootstrap_sqlite.py
ModuleNotFoundError: No module named 'modeling_infrastructure'
2 errors in 0.32s
```

This was the planned missing-package failure.

### GREEN development findings

The first implementation run reached the real Windows filesystem and found
that `os.fsync` rejects a read-only Windows descriptor. It failed 13 tests
before publication. The file flush path was changed from `rb` to `r+b`.
The same run showed an independently used `ProjectLock` must create an absent
lock file; it now creates one byte before locking.

The next run passed 12 tests and exposed two test-side SQLite lifecycle facts:
`foreign_keys` is connection-local, and a `sqlite3.Connection` context manager
commits but does not close the handle. Tests were corrected to inspect the
store-configured real connection and to close all SQLite handles explicitly,
so higher-version evidence is not masked by live WAL sidecars.

Focused GREEN command:

```powershell
uv run --locked --no-sync pytest tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py -q
```

Final exit code: `0`.

```text
..............                                                           [100%]
14 passed in 0.70s
```

## Implemented behavior

- Atomic `UNINITIALIZED -> STORAGE_READY` publication through a sibling
  `.modeling.tmp.<uuid4>` directory.
- All file and SQLite handles are closed before `os.rename`; files and the
  temporary directory are flushed where the platform supports it.
- Publication is no-clobber on Windows. Deterministic real-file tests exercise
  both `FileExistsError` and destination-race `PermissionError`; the loser is
  removed and a complete winner is verified before return.
- The published M1a layout contains exactly:

  ```text
  .modeling/project.json
  .modeling/state.sqlite3
  .modeling/project.lock
  ```

- `project.json` has exactly project format, canonicalization version, and
  `storage_instance_id`; it contains no absolute path.
- Repeat bootstrap verifies existing metadata and schema, returns the same
  storage ID with `created=false`, and changes no bytes.
- Schema 1 creates only `metadata`, `projects`, `experiments`, `attempts`,
  `result_snapshots`, `validations`, and `idempotency_records`.
- Required entity, payload, hash, timestamp, status, unique-key, and foreign-key
  constraints are present. No Project row is created by bootstrap.
- Every store connection enables foreign keys, WAL, synchronous FULL, and a
  250 ms busy timeout; `user_version=1` is set and verified.
- Higher database versions, incomplete/extra layout, mismatched metadata,
  invalid storage IDs, database errors, and unsafe reparse points fail closed.
- Windows `.modeling` junction detection is exercised against an actual
  junction and preserves its target bytes.
- `ProjectLock` uses nonblocking `msvcrt.locking` on Windows, returns retryable
  `CONFLICT/project_busy`, releases reliably, closes its handle, and can be
  renamed immediately after release. The POSIX branch uses nonblocking
  `flock`.
- `SQLiteProjectStore` structurally implements the exact A3 `ProjectStore`
  protocol. A4 implements storage-state inspection; A9-owned workflow methods
  remain explicit `NotImplementedError` boundaries.
- CLI `modeling bootstrap --project-root ...` passes `VersionSet.m1a()`
  explicitly and reports structured JSON.
- No staging/artifact directory, migration framework, recovery framework,
  second store, absolute persisted path, or A5+ abstraction was added.

## Packaging and lock evidence

Pre-sync `uv.lock` SHA-256:

```text
b3d3517d8d284d5e3df142cae3fa225d4f83e789213a917a0984943e8f9cac4f
```

After `src/modeling_infrastructure` existed, the one permitted refresh ran:

```powershell
uv sync --locked --group dev
```

Exit code: `0`.

```text
Resolved 44 packages in 28ms
Built math-modeling-mcp @ file:///C:/Users/39357/Desktop/...
Installed 1 package
~ math-modeling-mcp==0.1.0
```

Post-sync and final `uv.lock` SHA-256:

```text
b3d3517d8d284d5e3df142cae3fa225d4f83e789213a917a0984943e8f9cac4f
```

`git diff -- uv.lock` was empty. The `[project].dependencies` and
`[dependency-groups].dev` arrays remained byte-identical. The only
`pyproject.toml` change adds `src/modeling_infrastructure` to the explicit
Hatchling wheel package list. No `.pth`, editable-loader source, or
`PYTHONPATH` workaround was created.

## Manual CLI proof

Precondition:

```powershell
if (Test-Path -LiteralPath tests/.tmp/manual-project) {
  throw 'manual project already exists; inspect it instead of overwriting it'
}
New-Item -ItemType Directory -Path tests/.tmp/manual-project | Out-Null
```

First call:

```powershell
uv run --locked --no-sync modeling bootstrap --project-root tests/.tmp/manual-project
```

Exit code: `0`.

```json
{"created":true,"database_schema_version":1,"project_state":"STORAGE_READY","storage_instance_id":"c29e82c1-a93a-4806-8da3-5092eee07a79"}
```

Second call:

```powershell
uv run --locked --no-sync modeling bootstrap --project-root tests/.tmp/manual-project
```

Exit code: `0`.

```json
{"created":false,"database_schema_version":1,"project_state":"STORAGE_READY","storage_instance_id":"c29e82c1-a93a-4806-8da3-5092eee07a79"}
```

The manual directory contains only `project.json`, `project.lock`, and
`state.sqlite3`.

## Final verification

Focused tests:

```powershell
uv run --locked --no-sync pytest tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py -q
```

Exit code: `0`; `14 passed in 0.68s`.

Lint:

```powershell
uv run --locked --no-sync ruff check src/modeling_infrastructure src/modeling_cli tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py
```

Exit code: `0`; `All checks passed!`

Types:

```powershell
uv run --locked --no-sync mypy src/modeling_infrastructure src/modeling_cli
```

Exit code: `0`; `Success: no issues found in 9 source files`.

Regression:

```powershell
uv run --locked --no-sync pytest tests/unit/domain tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py -q
```

Exit code: `0`; `117 passed in 0.80s`.

Pre-staging `git diff --check` exited `0`.

## Remaining ownership

A9 owns Project creation, idempotency transactions, experiment/attempt/result
and validation persistence. A4 intentionally supplies only their schema and
the structurally exact store boundary.

## Review fix round 1 — reparse ancestors

Baseline commit:

```text
878acf1058bea4e46e4168c000a5ac97a904d55a
```

Independent review found that `ProjectPaths.bind()` checked the leaf project
root and `.modeling`, but resolved the path without checking its ancestors.
Thus a normal leaf such as `ancestor/project` beneath a Windows junction (or
POSIX symlink) could redirect bootstrap writes into the junction target.

### RED

A real Windows junction/POSIX symlink ancestor test was added. It passes the
project root as a relative path, places a marker in the target project, and
requires rejection before `.modeling` can be created in that target.

```powershell
uv run --locked --no-sync pytest tests/integration/test_bootstrap_sqlite.py::test_project_root_under_reparse_ancestor_is_rejected_before_target_write -q
```

Exit code: `1`.

```text
Failed: DID NOT RAISE StorageError
1 failed in 0.29s
```

### Minimal fix

Before `exists()`, `resolve()`, or any write, `ProjectPaths.bind()` now binds
relative input to the current directory and walks from the filesystem
drive/root through every user-path component using `lstat`. A symlink,
junction, or other Windows reparse point at any existing component raises the
existing fail-closed `SECURITY_VIOLATION/unsafe_reparse_point`. Drive-relative
Windows paths are rejected because they do not provide an unambiguous rooted
component chain. No new public abstraction was added.

Focused GREEN:

```powershell
uv run --locked --no-sync pytest tests/integration/test_bootstrap_sqlite.py::test_project_root_under_reparse_ancestor_is_rejected_before_target_write -q
```

Exit code: `0`; `1 passed in 0.19s`.

### Fix-round verification

```powershell
uv run --locked --no-sync pytest tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py -q
```

Exit code: `0`; `15 passed in 0.73s`.

```powershell
uv run --locked --no-sync ruff check src/modeling_infrastructure src/modeling_cli tests/contract/test_project_store.py tests/integration/test_bootstrap_sqlite.py
```

Exit code: `0`; `All checks passed!`

```powershell
uv run --locked --no-sync mypy src/modeling_infrastructure src/modeling_cli
```

Exit code: `0`; `Success: no issues found in 9 source files`.

```powershell
uv run --locked --no-sync pytest tests/unit/contracts tests/unit/domain tests/contract tests/integration/test_bootstrap_sqlite.py tests/architecture -q
```

Exit code: `0`; `165 passed in 3.40s`.
