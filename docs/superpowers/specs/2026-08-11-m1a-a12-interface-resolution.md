# M1a Task A12 Interface Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve Task A12's three interface gaps while preserving A11's source-nonmutation, failure-publication, exact-seven-artifact, and source-fingerprint guarantees.

**Architecture:** Capture a verified stable raw source snapshot, consolidate DB+WAL only in an owned temporary root, then bind the existing Facade and Store to that owned copy. Extend `ProjectStore` diagnostics, add one CLI-owned packaged Schema, and embed a failure-capable acceptance map in `verification-report.json` 0.2.0. No source SQLite open, second DB port, doctor-side SQL, seventh Facade/MCP method, or eighth evidence artifact is allowed.

**Tech Stack:** Python 3.11, bounded raw-file snapshots, SQLite WAL consolidation in owned temp storage, Pydantic DTOs, JSON Schema Draft 2020-12, pytest, Hatch/uv, existing M1a Harness.

## Global Constraints

- This document is binding for Task A12 and supersedes the original A12 text only where interfaces, file ownership, TDD slices, or evidence shapes conflict.
- A11 must be committed and clean before A12 product/test work begins.
- Source project is never opened through SQLite and receives no bootstrap, migration, repair, DML/DDL, SQLite connection, WAL/SHM participation, `ProjectLock` acquisition, writer lease, create/delete/rename, or byte change. Snapshot/consolidation failure is UNSAFE/2.
- Deep diagnostics may mutate only a newly owned `TemporaryDirectory` and must remove it.
- Preserve six MCP tools, seven package roots, seven final evidence filenames, 18 tool Schemas, and core catalog fingerprint.
- M1a remains fixed/repeatability stable-hash smoke only; no RFC 8785, M1b, release, recovery, worker, plugin, queue, UI, remote, or cross-platform claim.
- Every string ordering rule below means `value.encode("utf-8")`, component by component.

---

## 1. Authorized file delta

Original A12 files remain authorized. Add only:

- Create `src/modeling_cli/schemas/doctor/0.1.0/report.schema.json`.
- Create `src/modeling_cli/templates/codex/config.toml` as installed runtime authority.
- Create `src/modeling_infrastructure/diagnostic_snapshot.py`.
- Create `tests/integration/test_read_only_diagnostics.py`.
- Modify `src/modeling_core/ports/project_store.py`.
- Modify `src/modeling_infrastructure/sqlite/store.py`.
- Modify `tests/contract/test_project_store.py`.
- Modify `tests/security/test_m1a_boundaries.py`.
- Modify `tests/architecture/test_dependency_boundaries.py`.
- Modify `tests/reproducibility/test_m1a_repeatability.py`.

No `storage.py`, `pyproject.toml`, core Schema catalog, MCP Schema, composition API, or dependency change is authorized. Regular live Store connection, metadata, writer-lock, and transient-sidecar paths retain current behavior; only the section 2.1-2.2 `inspect_integrity` result semantics change. A12.1 must not add a global read-only opener.

## 2. Resolution R1: one complete source-nonmutating diagnostic path

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
- each legacy relation is queried independently with explicit `COLLATE BINARY`, `LIMIT 101`; 100 sorted unique rows pass;
- on 101 rows, only that relation contributes `database_relation`, its tuple is empty, and its `stale_*` issue is omitted; other relations continue and publish normally;
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
| one legacy relation returns 101 rows | retain PRAGMA outcome | empty only that tuple; `database_relation`, not its `stale_*`; continue other relations | DEGRADED |

Ordinary Facade `deep=False` calls therefore retain quick-check behavior. Issue output is unique and UTF-8-byte sorted.

### 2.3 Verified source snapshot and full call graph

The prior direct-source SQLite opener requirement is superseded. SQLite WAL
readers may create sidecars or update SHM even with URI read-only/query-only
settings; regular live Store reads remain unchanged. Runtime verification is
offline; design rationale may cite SQLite's official
[WAL read-only rules](https://sqlite.org/wal.html#readonly),
[WAL index/concurrency model](https://sqlite.org/wal.html), and
[URI immutable warning](https://sqlite.org/uri.html).

**Binding Windows probe correction (2026-08-11):** this paragraph supersedes
every later phrase that permits SQLite to open the copied raw DB or WAL
read/write. A Windows `CreateFileW` probe established that one raw handle
cannot simultaneously grant SQLite write ownership and exclude an arbitrary
second raw writer. A12.1 must instead hold copied
`state.sqlite3`, an always-present owned-input `state.sqlite3-wal`, and an
always-present zero-byte owned-input `state.sqlite3-shm` sentinel with
`GENERIC_READ` plus `FILE_SHARE_READ` only, open that input through SQLite URI
`mode=ro`, enable and verify connection-local `query_only`, and use
`sqlite3.Connection.backup` to a distinct `:memory:` destination. If the
source WAL exists, the owned-input WAL is its verified copy. If source WAL is
absent, the owned-input WAL is a newly created zero-byte sentinel with bound
identity, size zero, and SHA-256 of empty bytes. The owned-input SHM is always a
separately bound zero-byte SHA(empty) sentinel; no source SHM is copied. All
three DB/WAL/SHM guards bind immediately before SQLite input open and remain
held until after the input connection closes and their complete identities,
sizes, and hashes are rechecked. Normal `mode=ro`/`query_only` then uses a
private heap WAL-index, preserves committed copied-WAL state, and cannot mutate
the guarded SHM name. This closes both absent-name and writable-WAL-index races;
an absence recheck or SQLite-created input member is forbidden. No SQLite
connection ever opens the normalized filesystem output: the verified in-memory
database is serialized exactly once, then its bytes are exclusively created,
written, flushed, and fsynced as the final normalized `state.sqlite3`. Source
files remain outside all SQLite calls.

`diagnostic_snapshot.py` owns the complete executable failure interface:

```python
SnapshotFailureCode = Literal[
    "snapshot_unstable",
    "snapshot_invalid",
    "snapshot_resource_limit",
    "snapshot_unavailable",
    "snapshot_cleanup_failed",
]

class DiagnosticSnapshotError(RuntimeError):
    @property
    def code(self) -> SnapshotFailureCode: ...  # read-only

@dataclass(frozen=True)
class DiagnosticSnapshot:
    project_root: Path  # owned temporary root only
    source_state_hint: Literal["UNINITIALIZED", "INITIALIZED"]

@contextmanager
def materialize_diagnostic_snapshot(
    project_root: Path,
) -> Iterator[DiagnosticSnapshot]: ...
```

`DiagnosticSnapshotError` accepts only one validated code. Its `str()`/`args`
use a fixed code-to-message table: `snapshot changed during capture`,
`snapshot input is invalid`, `snapshot resource limit exceeded`,
`snapshot is unavailable`, or `snapshot cleanup failed`. It has no public
details/source/cause field; source path, identity, hash, timestamp, retry count,
OS/SQLite text, and arbitrary exception text never render. Raw causes may be
exception-chained internally. Expected classification is exhaustive:

| code | conditions |
| --- | --- |
| `snapshot_unstable` | A/B name, presence, identity, size, mtime, persistent hash, raw-input DB/WAL/SHM-sentinel post-backup identity/size/hash drift, or destination-copy mismatch |
| `snapshot_invalid` | unsafe shape/type/reparse/link state, nonempty or wrongly hashed synthetic WAL/SHM sentinel, invalid persistent DB/WAL bytes, non-I/O read-only-open/backup/serialize semantics, serialized page/length/hash mismatch, or exact-layout failure |
| `snapshot_resource_limit` | source/in-memory/serialized/final/peak byte bound, backup progress bound, cooperative deadline, SQLITE_FULL/NOMEM, ENOSPC, or `MemoryError` |
| `snapshot_unavailable` | permission, sharing, device, guarded input/WAL-or-SHM-sentinel create/open, backup/serialize/output-write I/O, BUSY/LOCKED/CANTOPEN/IOERR/PERM, or other I/O denial prevents proof without proving invalid bytes |
| `snapshot_cleanup_failed` | owned WAL/SHM sentinel, input/staging/snapshot/deep root cannot be identity-bound and fully removed; this supersedes any pending success or other failure |

`run_doctor` separately maps an unexpected non-`DiagnosticSnapshotError`
exception to fixed redacted `storage-integrity/check_error` UNSAFE/2. The
snapshot API exposes no source path, SQLite connection, repair, mutation, or
lock method and performs one attempt with no retry or source-SQLite fallback.

For initialized source `.modeling/`, allowed names are exact:

```text
required: project.json, state.sqlite3, project.lock
optional: state.sqlite3-wal, state.sqlite3-shm
```

Reject every other entry, nested directory, missing required member, reparse,
symlink, junction, non-regular file, or unprovable identity. The source
`project.lock` handling is metadata-only: it is never opened, read, hashed, or
copied, including while a Windows server holds its byte-range lock. Repeated
non-following `lstat` only must prove regular/non-reparse type, size `1..64 B`,
and stable A/B volume/device plus file-ID/inode identity, size, and `mtime_ns`.
The owned snapshot creates a new `project.lock` containing exactly `b"\0"`.

Opened persistent source files (`project.json`, `state.sqlite3`, and WAL iff
present) use non-following handles and revalidate handle device/volume plus
inode/file-ID identity against `lstat`. Manifest A and B both record exact
directory names and:

- persistent stability set: identity, size, `mtime_ns`, and full raw SHA-256 for `project.json`, `state.sqlite3`, and WAL iff present;
- copy set: those same persistent members, streamed to owned staging with destination size/SHA-256;
- lock metadata set: presence, regular/non-reparse type, identity, size, `mtime_ns`; never open/hash/copy contents;
- SHM metadata set: presence, regular/non-reparse type, and identity only; never copy/hash contents or require stable size, mtime, or bytes.

Capture order is exact:

```text
bind and validate source components
-> enumerate exact allowed names
-> capture manifest A
-> stream-copy persistent copy set while hashing destination
-> capture manifest B and re-enumerate
-> require A == B for persistent and lock stability fields,
   stable SHM presence/identity, and destination size/hash == manifest A
-> close all source handles
```

Source receives no SQLite call, source-lock open, `ProjectLock`, create,
delete, rename, chmod, timestamp normalization, or write. An idle fixture must
prove exact before/after source bytes and members; an active-writer fixture
does not compare SHM hashes and accepts only a verified stable DB+WAL snapshot
or finite `snapshot_unstable`/`snapshot_unavailable`.

Raw-source limits remain fixed: `project.json` 64 KiB, source lock metadata
size `1..64 B`, `state.sqlite3` 64 MiB, WAL 64 MiB, total copied persistent
bytes 128 MiB, and 1 MiB copy/hash chunks. The owned raw input is
`owned_root/.modeling.input/` and contains only `project.json`,
`state.sqlite3`, required `state.sqlite3-wal`, and required zero-byte
`state.sqlite3-shm`. The required owned-input WAL is either the verified source
WAL copy or the zero-byte synthetic sentinel; both synthetic sentinel forms
have SHA-256 exactly
`e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`.
Owned-input persistent bytes, including either WAL form, are capped by the
128 MiB copy limit; the zero-byte sentinel does not increase that literal byte
sum, and the guarded SHM sentinel has a zero-byte cap. No SQLite-created input
member is allowed. The distinct normalized output is
`owned_root/.modeling.staging/`; its serialized main DB is capped at
134,217,728 B, its copied `project.json` at 65,536 B, and its fresh
`project.lock` metadata at 64 B. Output WAL/SHM files are forbidden.

Peak owned bytes have one literal limit, not a dynamically derived or
filesystem-dependent allowance:

```text
raw persistent input                         134,217,728 B
guarded input SHM sentinel                             0 B
in-memory normalized DB                      134,217,728 B
serialized immutable bytes                   134,217,728 B
final on-disk normalized DB                  134,217,728 B
normalized project.json + project.lock            65,600 B
----------------------------------------------------------------
literal owned peak                           536,936,512 B
```

The peak intentionally counts the in-memory SQLite database, the immutable
`bytes` returned by exactly one `serialize()` call, and the complete on-disk
copy simultaneously; it is not derived from observed filesystem or database
contents. The implementation checks the fixed 536,936,512-byte peak plus each
128 MiB sublimit after raw copy, read-only input open, every backup progress
callback and blocking phase, backup completion, in-memory page verification,
serialization, every output-write chunk, flush/fsync, both connection closes,
sentinel deletion, raw-input removal, and publication. One shared minimal
bounded-streaming helper enumerates every owned/root/input/output/cleanup
allowlist, yields at most its literal limit plus one, and stops immediately at
that extra member; it never uses an unbounded recursive walk, dynamic member
count, or a limit calculated from observed files.

One 10-second monotonic budget is cooperative, not a hard timeout. Check it
before and after every manifest/enumeration/copy phase and chunk, raw-guard
acquisition, SQLite input/in-memory-destination open, allowed PRAGMA, backup
callback, serialize, output create/write/flush/fsync, close, raw-input removal,
and publication phase. `Connection.backup` uses exactly
`pages=256`, `sleep=0.0`, and a progress callback capped at 1,025 invocations;
the callback checks deadline, status, remaining/total page values, normalized
logical-size and peak-byte limits. Successful callback grammar is exactly
`SQLITE_OK* -> exactly one terminal SQLITE_DONE`; DONE-only is valid, DONE
requires `remaining == 0`, and no callback may follow DONE. `total` is fixed
from the first callback even when it is DONE, every tuple must satisfy
`0 <= remaining <= total`, and `remaining` is monotonically non-increasing.
Status must be an integer whose SQLite primary family (`status & 0xff`) is in
this finite map: OK(0)/DONE(101) are grammar; BUSY(5), LOCKED(6), CANTOPEN(14),
IOERR(10), and PERM(3), including their extended families, are immediate
`snapshot_unavailable`; FULL(13), NOMEM(7), and deadline are
`snapshot_resource_limit`; READONLY(8), NOTADB(26), CORRUPT(11), FORMAT(24),
page-size mismatch, an unknown family, or an impossible progress tuple are
`snapshot_invalid`. Serialize or final-write `MemoryError`, fixed byte excess,
and `SQLITE_FULL`/`SQLITE_NOMEM` are `snapshot_resource_limit`. Raw
identity/hash drift remains `snapshot_unstable`, and
owned cleanup failure overrides all as `snapshot_cleanup_failed`. A callback
count above 1,025 or total pages above the 128 MiB logical cap using the
validated raw SQLite-header page size is `snapshot_resource_limit`. No raw
SQLite text renders. No busy retry loop or dynamic sleep is allowed. A blocking
call may overrun before its after-check classifies
`snapshot_resource_limit`; hard interruption is deferred to a worker boundary.
Cleanup is never skipped because the deadline elapsed.

Transport normalization is exact:

```text
create .modeling.input and .modeling.staging under the owned root
-> copy and verify raw project.json + DB into .modeling.input
-> if source WAL exists, copy/hash it; otherwise atomically create the 0-byte
   state.sqlite3-wal sentinel and bind its identity/size/SHA(empty)
-> atomically create state.sqlite3-shm as a distinct 0-byte SHA(empty)
   sentinel; never copy source SHM
-> create normalized project.lock = b"\0" and verified project.json copy
-> immediately bind raw DB, the always-present WAL form, and the always-present
   SHM sentinel with GENERIC_READ + FILE_SHARE_READ only
-> open raw DB with URI mode=ro; execute query_only=ON and require query_only=1
-> create one distinct SQLite :memory: destination; never connect SQLite to
   normalized filesystem output
-> Connection.backup(raw_input, memory_output, pages=256, sleep=0.0,
   bounded progress callback)
-> on memory_output, require page_size == validated raw-header page size,
   page_count >= 0, and page_size * page_count <= 134,217,728
-> call memory_output.serialize() exactly once; require `bytes`, length exactly
   page_size * page_count, length <= 134,217,728, and hash the immutable bytes
-> exclusively create normalized state.sqlite3 with `xb`; stream the serialized
   bytes once while hashing, flush/fsync, close, and require final identity,
   size, and SHA-256 equal the serialized binding
-> close raw SQLite in finally; revalidate raw handle identities/link counts,
   sizes, mtimes, and full DB/WAL/SHM-sentinel SHA-256; then release raw guards
-> for always-synthetic SHM and synthetic WAL when applicable, reopen only each
   same identity under a bounded DELETE/no-share-delete handle, require size
   0/SHA(empty)/link-count 1, and delete-on-close; replacement or mutation fails
   closed
-> close memory_output in finally
-> safely remove .modeling.input before publication
-> require no WAL/SHM and exact project.json/state.sqlite3/project.lock output
-> rename .modeling.staging to .modeling and revalidate through publication
```

The input SQL allowlist is exactly `PRAGMA query_only=ON` and
`PRAGMA query_only`; the latter must return one integer row `(1,)`. The
in-memory-output SQL allowlist is exactly `PRAGMA page_size` and
`PRAGMA page_count`, both after backup. No page-size or max-page setter is
needed: the validated raw header plus the progress `total` bound limits backup,
and the post-backup page-size/page-count product, exact serialized length, and
fixed peak independently verify the result. The accepted page size is a
SQLite-valid power of two from 512 through 65,536 bytes, including the header
encoding for 65,536. No SQLite statement or connection targets the normalized
filesystem output, so no output WAL/SHM/checkpoint lifecycle exists.
`Connection.backup` is the only permitted cross-connection copy
operation. Normalization must not execute `quick_check`, `integrity_check`,
`foreign_key_check`, any legacy query, DML, DDL, VACUUM, ATTACH, or a
source-side checkpoint. No input-side SQLite-created member may appear. Copied
DB/WAL bytes are never writable by SQLite and must hash identically before and
after backup. The synthetic WAL when applicable and always-synthetic SHM are
likewise never writable by SQLite, are present before all three read guards
bind, and must retain identity, size zero, and SHA(empty) until identity-bound
post-close deletion. The exact input-name allowlist during SQLite lifetime is
`project.json`, `state.sqlite3`, `state.sqlite3-wal`, and
`state.sqlite3-shm`; all four are required and no other member is accepted.

After composition binds the published normalized copy,
`SQLiteProjectStore.inspect_integrity(deep)` exclusively executes the selected
quick/integrity check, foreign-key check, and each legacy query under sections
2.1-2.2. A backup-preserved logical integrity/FK finding therefore reaches
Store/doctor diagnostics and is not `snapshot_invalid`. Invalid SQLite format,
NOTADB/CORRUPT, impossible backup progress, serialize mismatch, or output
layout semantics is `snapshot_invalid`; SQLITE_FULL/NOMEM, `MemoryError`, fixed byte/progress/deadline
excess, or ENOSPC is `snapshot_resource_limit`; BUSY/LOCKED/CANTOPEN/IOERR,
permission, or sharing denial is `snapshot_unavailable`. Raw-input identity,
presence, size, mtime, or hash drift, including WAL/SHM sentinel
replacement/mutation, is `snapshot_unstable`. An unsafe sentinel type/link
state or initial nonempty/wrong-hash sentinel is `snapshot_invalid`. Failure to
prove and complete either owned sentinel deletion is `snapshot_cleanup_failed`.
Every message is redacted through the existing five-code interface.

Do not switch to DELETE journal mode, write/checkpoint the raw input, rely on
an absent-name recheck, permit SQLite to create input SHM, or manually unlink a
nonempty WAL. Synthetic empty WAL/SHM sentinels are removed only by the
bound-delete sequence above. All connections and
handles close and both owned input/output roots clean in `finally`. If cleanup succeeds, raise the
pending finite primary code; if cleanup fails, discard any computed READY
report or primary error and raise `snapshot_cleanup_failed`. UNINITIALIZED
source yields an owned empty project root plus UNINITIALIZED hint; no source
`.modeling` member is read or created.

RED-only deterministic mutation seams exist after manifest A, during each
member copy, before manifest B, after raw guards bind, after the read-only input
opens, during every backup progress callback, after backup, after serialize,
during output write, after fsync, through publication, and during cleanup. Tests attempt
raw DB/WAL write and truncate after the read-only open, replace/change copied
members, race creation/write/truncate against an absent-source-WAL sentinel,
mutate/replace the guarded SHM sentinel, inject backup progress grammar/status,
serialize length/hash/limit failures, output exclusive-create/write/fsync and
late-drift failures, ENOSPC/deadline failures, and fail cleanup.
These seams are not public retry/mutation APIs. Secret-bearing
OS/SQLite exception strings are injected at every expected and unexpected
boundary; tests require only fixed public messages/codes and prove the raw
strings never reach JSON, human output, stderr, or DTO fields.

Complete doctor call graph:

```text
main._doctor
-> doctor.run_doctor owns the fixed finite error and one-output boundary
-> enter materialize_diagnostic_snapshot(source_project_root)
   -> build_composition(snapshot.project_root), never source root
   -> diagnose_project(application, store, source_state_hint, deep)
      -> Facade health_check + list_capabilities on owned snapshot
      -> Store inspect_integrity(deep) on owned snapshot
      -> packaged Schema/hash and packaged Codex-template reads
      -> if deep, finish and clean the distinct deep-smoke context
   -> construct and Schema-validate DoctorReport entirely in memory
   -> close composition without starting source
-> exit snapshot context and finish owned cleanup
-> only after both context exits succeed, render exactly once
```

Normal MCP/server Store connection, metadata, writer-lock, and transient-sidecar
paths retain existing behavior because they operate on the server-owned project;
the section 2.1-2.2 `inspect_integrity` result semantics intentionally change.
Doctor's Store calls run only on the consolidated owned snapshot. `doctor.py`
does not import SQLite or inspect Store internals. Expected snapshot failure
becomes one finite UNSAFE/2 report; unexpected failure uses the separate fixed
boundary; neither emits traceback or source details.

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
| 5 `storage-integrity` | `not_initialized`, `ok` | — | `not_executed_degraded`, `check_failed`, `check_error`, `snapshot_unstable`, `snapshot_invalid`, `snapshot_resource_limit`, `snapshot_unavailable`, `snapshot_cleanup_failed` |
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
- unsafe/unreadable root or pre-Store snapshot failure -> strict UNSAFE/2 with synthesized DEGRADED, `storage.check=null`, `storage.issues=[]`, empty legacy arrays, the exact finite `storage-integrity` snapshot code, dependent checks `unavailable`, and no source path, hash, identity, timestamp, SQLite message, retry count, or exception text. `database_relation` remains reserved for an actual Store open/query/conversion failure.

All five `DiagnosticSnapshotError.code` values map unchanged to the
`storage-integrity` FAIL code. Invalid source binding uses `snapshot_invalid`;
permission/share/device denial uses `snapshot_unavailable`; any owned cleanup
failure uses `snapshot_cleanup_failed` and overrides a computed READY report.
`project-root` is FAIL/`unsafe` or `unreadable` only when root binding proves
that condition, otherwise PASS/`available`; `project-state` is FAIL/`degraded`;
`application-health` and `capability-registry` are FAIL/`unavailable`;
foreign-key and all three legacy checks are FAIL/`unavailable`. Independent
packaged `schema-assets` and `codex-config` checks still execute. An unexpected
exception at `run_doctor` uses the same empty storage payload and fixed
`storage-integrity/check_error`, never a fabricated snapshot code.

Both success and finite-failure reports are built and Schema-validated in
memory. No JSON/human bytes are emitted until the base snapshot and any deep
context have exited successfully. Cleanup failure discards the prior report,
builds and validates `snapshot_cleanup_failed` UNSAFE/2, then renders exactly
once; stdout was empty beforehand. Any Schema load/meta/instance failure emits
no stdout, exactly `MODELING_DOCTOR_SCHEMA_INVALID\n` to stderr, and exits 2.

`src/modeling_cli/templates/codex/config.toml` is canonical runtime authority,
loaded offline with `importlib.resources.files("modeling_cli")`.
`docs/templates/codex/config.toml` is mandatory byte-identical copy for users.
Doctor validates packaged bytes; acceptance validates both files have identical
bytes and SHA-256. Installed-wheel tests must not depend on repository `docs/`.

### 3.3 Deep smoke sequence

```text
second TemporaryDirectory, distinct from the base diagnostic snapshot
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

Every failure closes both compositions and independently removes the deep-smoke root and base diagnostic snapshot in `finally`. Neither the source project nor the base snapshot is locked, started, reused as the deep root, or mutated.
Deep-root cleanup failure is converted to `snapshot_cleanup_failed` before the
base context exits. Tests inject failure at deep-root and base-snapshot exit and
prove no READY/partial stdout precedes the single finite UNSAFE document.

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
| A-10 | `tests/acceptance/test_m1a_acceptance_map.py::test_m1a_context_config_and_acceptance_map_are_complete`; `tests/acceptance/test_m1a_acceptance_map.py::test_m1a_abstraction_budget_and_exact_context_inventory_are_binding`; `tests/acceptance/test_m1a_acceptance_map.py::test_a12_runtime_and_nested_context_assets_are_installed_offline_without_core_catalog_drift`; `tests/reproducibility/test_m1a_repeatability.py::test_a12_profile_and_report_transition_preserve_a11_evidence_contract` | `pytest-acceptance`, `pytest-reproducibility`, `wheel` |

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

A11 baseline and every A12 slice have a literal package inventory gate:

| Gate | Python | non-Python | total | exact new package members |
| --- | ---: | ---: | ---: | --- |
| A11 baseline | 53 | 32 | 85 | none |
| A12.1 | 54 | 32 | 86 | `modeling_infrastructure/diagnostic_snapshot.py` |
| A12.2 | 55 | 34 | 89 | `modeling_cli/doctor.py`; doctor Schema; packaged Codex template |
| A12.3 | 55 | 37 | 92 | three package-root `AGENTS.md` files |
| A12.4/final | 55 | 37 | 92 | no new member; freeze final five non-Python hashes |

The five final non-Python package assets are:

```text
modeling_cli/schemas/doctor/0.1.0/report.schema.json
modeling_cli/templates/codex/config.toml
modeling_core/AGENTS.md
modeling_capabilities/AGENTS.md
modeling_mcp/AGENTS.md
```

Seven unique roots remain throughout. Every slice may modify
`tests/reproducibility/test_m1a_repeatability.py` only to advance to its row's
literal counts and exact newly present paths; its complete test suite must be
GREEN before that slice commits. Expected counts/paths are constants from this
table, never derived from the wheel being checked. A12.4 fixes final raw-byte
SHA-256 constants for each of the five non-Python assets and asserts all seven
new package paths. The repository `docs/templates/codex/config.toml` remains a
mandatory byte/hash-identical mirror of the packaged template but is not a
wheel member.

Mutation matrix must cover: check FAIL; required skip; golden FAIL; wheel FAIL; removal or raw-byte mutation of each of the five new non-Python package assets; source drift; exact node removed/renamed/not run while broad group remains PASS; required family with no member; one observed family member missing outcome evidence; one family member FAILED; one family member SKIPPED; complete multi-member family PASS with all exact parameter IDs retained; malformed/duplicate/over-limit JUnit node; duplicate A ID; missing/recursive pointer; missing transcript/trace; eighth artifact; silent 0.1.0 mutation; acceptance test reading current evidence; acceptance test invoking verify. Executed failures publish valid exact-seven bundles.

## 6. Implementation slices, review gates, commits

### Slice A12.1: stable diagnostic snapshot and Store DTO correction

- [ ] Fix these Store RED nodes before production edits: `tests/contract/test_project_store.py::test_integrity_report_dtos_are_finite_unique_bounded_and_utf8_ordered`; `tests/contract/test_project_store.py::test_inspect_integrity_selects_exact_check_and_reports_legacy_rows`; `tests/contract/test_project_store.py::test_legacy_overflow_empties_only_affected_relation_and_continues_others`.
- [ ] The Windows-probe correction supersedes the old copied-input read/write
  checkpoint and filesystem-output SQLite RED wording. Fix these exact
  read-only-backup RED nodes before
  any corresponding production edit:
  - `tests/integration/test_read_only_diagnostics.py::test_read_only_backup_guards_block_raw_input_write_and_truncate_after_open`
  - `tests/integration/test_read_only_diagnostics.py::test_absent_source_wal_uses_guarded_empty_sentinel_that_blocks_create_write_and_truncate`
  - `tests/integration/test_read_only_diagnostics.py::test_guarded_empty_wal_sentinel_preserves_committed_main_database_state`
  - `tests/integration/test_read_only_diagnostics.py::test_guarded_empty_shm_sentinel_forces_private_wal_index_and_blocks_raw_mutation`
  - `tests/integration/test_read_only_diagnostics.py::test_read_only_backup_leaves_raw_input_database_and_wal_bytes_unchanged`
  - `tests/integration/test_read_only_diagnostics.py::test_read_only_backup_preserves_latest_committed_wal_state`
  - `tests/integration/test_read_only_diagnostics.py::test_read_only_backup_preserves_non_default_source_page_size`
  - `tests/integration/test_read_only_diagnostics.py::test_memory_backup_opens_no_output_filesystem_sqlite_or_sidecars`
  - `tests/integration/test_read_only_diagnostics.py::test_owned_peak_limit_is_literal_536936512_bytes`
  - `tests/integration/test_read_only_diagnostics.py::test_backup_progress_accepts_done_only_and_ok_star_done`
  - `tests/integration/test_read_only_diagnostics.py::test_backup_progress_rejects_duplicate_post_done_and_unknown_status_with_finite_codes`
  - `tests/integration/test_read_only_diagnostics.py::test_serialized_database_length_hash_and_limits_are_exact`
  - `tests/integration/test_read_only_diagnostics.py::test_normalized_output_is_exclusively_created_and_rejects_late_drift`
  - `tests/integration/test_read_only_diagnostics.py::test_backup_serialize_and_output_write_failures_are_finite_and_redacted`
  - `tests/integration/test_read_only_diagnostics.py::test_normalized_backup_publishes_exact_owned_layout_without_sidecars`
  - `tests/integration/test_read_only_diagnostics.py::test_preserved_foreign_key_violation_reaches_store_foreign_key_report`
  - `tests/integration/test_read_only_diagnostics.py::test_preserved_non_ok_integrity_reaches_store_check_failed`
- [ ] Fix these remaining A12.1 snapshot RED nodes before production edits:
  - `tests/integration/test_read_only_diagnostics.py::test_mode_ro_query_only_is_not_a_zero_byte_mutation_contract_on_wal`
  - `tests/integration/test_read_only_diagnostics.py::test_diagnostic_snapshot_opens_no_sqlite_connection_or_project_lock_on_source`
  - `tests/integration/test_read_only_diagnostics.py::test_held_windows_project_lock_is_never_opened_or_hashed_and_snapshot_succeeds`
  - `tests/integration/test_read_only_diagnostics.py::test_source_project_lock_open_spy_proves_metadata_only_capture`
  - `tests/integration/test_read_only_diagnostics.py::test_uncommitted_wal_tail_is_not_reported_as_committed_state`
  - `tests/integration/test_read_only_diagnostics.py::test_db_or_wal_change_between_manifests_fails_snapshot_unstable`
  - `tests/integration/test_read_only_diagnostics.py::test_same_size_owned_copy_corruption_fails_snapshot_unstable`
  - `tests/integration/test_read_only_diagnostics.py::test_wal_appearance_disappearance_or_identity_swap_fails_snapshot_unstable`
  - `tests/integration/test_read_only_diagnostics.py::test_snapshot_rejects_reparse_nonregular_unexpected_and_oversize_members`
  - `tests/integration/test_read_only_diagnostics.py::test_snapshot_expected_errors_are_typed_finite_read_only_and_redacted`
  - `tests/integration/test_read_only_diagnostics.py::test_input_wal_and_memory_serialized_final_bounds_fail_resource_limit`
  - `tests/integration/test_read_only_diagnostics.py::test_owned_peak_tree_and_enospc_fail_resource_limit`
  - `tests/integration/test_read_only_diagnostics.py::test_owned_and_cleanup_enumeration_stops_at_allowlist_plus_one`
  - `tests/integration/test_read_only_diagnostics.py::test_cooperative_deadline_checks_after_blocking_phases_fail_resource_limit`
  - `tests/integration/test_read_only_diagnostics.py::test_snapshot_failure_closes_handles_and_cleanup_failure_uses_typed_code`
  - `tests/integration/test_read_only_diagnostics.py::test_idle_source_bytes_and_members_remain_exactly_unchanged`
  - `tests/integration/test_read_only_diagnostics.py::test_active_writer_uses_stable_db_wal_or_finite_failure_without_shm_hash_equality`
  - `tests/integration/test_read_only_diagnostics.py::test_read_only_backup_sql_is_limited_to_input_and_memory_output_allowlists`
- [ ] Fix A12.1 boundaries: `tests/architecture/test_dependency_boundaries.py::test_a12_1_snapshot_and_store_tests_do_not_import_modeling_cli_doctor`; `tests/architecture/test_dependency_boundaries.py::test_diagnostic_snapshot_has_no_core_cli_or_source_sqlite_dependency`; `tests/security/test_m1a_boundaries.py::test_diagnostic_snapshot_rejects_unsafe_source_members_without_sensitive_error_text`.
- [ ] A12.1 tests and product contain no import of `modeling_cli.doctor` and no `test_doctor_*` node. The real-held-lock node is Windows-primary; the open-spy node enforces the no-open rule platform-independently.
- [ ] Run focused tests; record expected failures before editing production.
- [ ] Implement `diagnostic_snapshot.py` plus minimal DTO/Store changes. Do not change `storage.py`, add a general opener, or route regular live Store reads through this path.
- [ ] Modify `tests/reproducibility/test_m1a_repeatability.py` in this slice to require literal `86 total = 54 Python + 32 non-Python` and exact member `modeling_infrastructure/diagnostic_snapshot.py`; do not derive expected counts dynamically.
- [ ] Run focused tests, full Store/application regressions, Ruff, MyPy.
- [ ] Run the complete `pytest tests -q` suite GREEN at the 86/54/32 inventory before review or commit.
- [ ] Independent spec review: source lock is metadata-only; source has no SQLite/lock/mutation; copied raw DB, always-present copied-or-synthetic WAL, and always-present zero-byte SHM sentinel are guarded read-only, hash-invariant, and never checkpointed; absent source WAL cannot race-create and SQLite uses a private heap WAL-index because guarded sentinels occupy both sidecar names through input close before identity-bound deletion; copied destination DB hash equals manifest A; every owned/root/input/output/cleanup enumeration stops at the literal allowlist plus one; backup targets only `:memory:`, progress obeys `OK* -> exactly one DONE`, page size and logical size are verified, and `serialize()` is called exactly once; no SQLite connection targets filesystem output and no output WAL/SHM/checkpoint exists; exclusive output creation, chunked write/hash, fsync, final identity/hash, late-drift rejection, and exact three-file publication are verified; the trace uses only input/in-memory-output SQL allowlists and contains no Store diagnostic query; the literal 536,936,512-byte peak counts raw input, in-memory DB, serialized bytes, final DB, and project/lock without dynamic observed limits; no second port, doctor import/SQL, or core SQLite import.
- [ ] Commit only GREEN reviewed slice: `feat: add stable diagnostic snapshot`.

### Slice A12.2: doctor Schema and orchestration

- [ ] Fix these A12.2 integration REDs: `tests/integration/test_read_only_diagnostics.py::test_doctor_binds_composition_only_to_owned_snapshot_root`; `tests/integration/test_read_only_diagnostics.py::test_doctor_cleans_base_snapshot_and_deep_smoke_roots_on_every_exit`; `tests/integration/test_read_only_diagnostics.py::test_real_foreign_key_violation_maps_to_doctor_foreign_key_failure`; `tests/integration/test_read_only_diagnostics.py::test_preserved_non_ok_integrity_maps_to_doctor_check_failed`; `tests/integration/test_read_only_diagnostics.py::test_full_doctor_idle_source_bytes_and_members_are_unchanged`; `tests/integration/test_read_only_diagnostics.py::test_full_doctor_active_writer_is_verified_or_finite_without_shm_hash_assertion`.
- [ ] Fix these doctor REDs: `tests/unit/test_doctor.py::test_uninitialized_is_warning_and_storage_ready_and_ready_are_ready`; `tests/unit/test_doctor.py::test_degraded_legacy_and_integrity_failures_are_unsafe`; `tests/unit/test_doctor.py::test_doctor_uses_shared_facade_and_store_without_starting_inspected_composition`; `tests/unit/test_doctor.py::test_all_snapshot_failure_codes_map_to_empty_redacted_pre_store_payload`; `tests/unit/test_doctor.py::test_unexpected_doctor_error_maps_to_fixed_redacted_check_error`; `tests/unit/test_doctor.py::test_doctor_schema_is_strict_versioned_finite_and_packaged`; `tests/unit/test_doctor.py::test_build_composition_failures_render_one_redacted_unsafe_report`; `tests/unit/test_doctor.py::test_schema_validation_failure_is_stderr_only_and_exit_two`; `tests/unit/test_doctor.py::test_render_occurs_once_only_after_base_and_deep_context_exit`; `tests/unit/test_doctor.py::test_cleanup_failure_discards_ready_report_without_prior_stdout`; `tests/unit/test_doctor.py::test_deep_doctor_runs_owned_root_and_lock_smokes_then_cleans_up`.
- [ ] Fix A12.2 boundaries: `tests/architecture/test_dependency_boundaries.py::test_doctor_has_no_source_sqlite_or_writer_side_effects`; `tests/security/test_m1a_boundaries.py::test_doctor_rejects_unsafe_root_without_traceback_or_path_disclosure`.
- [ ] Implement packaged Schema, snapshot-consuming `diagnose_project`/`run_doctor`, CLI wiring, and canonical human/JSON rendering. Composition receives only the owned snapshot root.
- [ ] Modify `tests/reproducibility/test_m1a_repeatability.py` in this slice to require literal `89 total = 55 Python + 34 non-Python` and the exact new `modeling_cli/doctor.py`, doctor-Schema, and packaged-template paths; do not derive expected counts dynamically.
- [ ] Run doctor unit/integration/security/architecture tests and real bootstrap -> deep doctor command.
- [ ] Run real CLI doctor fixtures for clean-WAL, existing-WAL, active writer, preserved integrity/FK findings, and unopenable/backup/serialize/output-write-failing DB/WAL; the active writer either yields a verified stable DB+WAL snapshot or finite UNSAFE/2, never unverified READY.
- [ ] Run the complete `pytest tests -q` suite GREEN at the 89/55/34 inventory before review or commit.
- [ ] Independent review: frozen A12.1 interface, including guarded read-only input, bounded backup to `:memory:`, post-backup page verification, exactly-once serialization, exclusive output write/fsync/hash binding, no output filesystem SQLite/WAL/SHM/checkpoint, and the fixed 536,936,512-byte peak, is unchanged; five finite snapshot codes and unexpected boundary are redacted; output follows both cleanups; no source SQLite/composition/lock; exact state/exit map and two-root lifecycle.
- [ ] Commit: `feat: add snapshot-backed project doctor`.

A12.2 consumes the reviewed A12.1 interface, including guarded raw input,
bounded backup to `:memory:`, post-backup page verification, exactly-once
serialization, exclusive output creation/write/fsync/hash binding, no output
filesystem SQLite/WAL/SHM/checkpoint, and fixed peak arithmetic, and must not change capture,
consolidation, limits, or exception semantics. Any correction returns to A12.1
with a new failing regression, focused review, and separate `fix:` commit.

Acceptance/Harness REDs for A12.3/A12.4 remain the exact A-nodes in section
4.3 plus `tests/acceptance/test_m1a_acceptance_map.py::test_acceptance_policy_mutations_reject_each_a_clause`; `tests/acceptance/test_m1a_acceptance_map.py::test_acceptance_map_materializes_pass_and_failure_documents`; `tests/acceptance/test_m1a_acceptance_map.py::test_parameterized_family_requires_complete_passing_current_run_evidence`; `tests/acceptance/test_m1a_acceptance_map.py::test_acceptance_map_rejects_recursive_or_current_evidence_dependencies`; `tests/reproducibility/test_m1a_repeatability.py::test_junit_parser_records_strict_normalized_exact_test_nodes`; `tests/reproducibility/test_m1a_repeatability.py::test_missing_or_renamed_current_run_literal_node_forces_fingerprinted_failed_bundle`; `tests/reproducibility/test_m1a_repeatability.py::test_a12_failure_mutations_publish_exact_seven_file_failed_bundles`.

### Slice A12.3: minimum context and Codex template

- [ ] Add structural REDs for exact AGENTS/docs/link inventory, authority routing, M1 scope/abstraction budget, one M1a-0 plus A1-A12 headings, and exact trusted-project Codex TOML.
- [ ] Create only original A12 context/docs/template files; update README last.
- [ ] Modify `tests/reproducibility/test_m1a_repeatability.py` in this slice to require literal `92 total = 55 Python + 37 non-Python` and exact `modeling_core/AGENTS.md`, `modeling_capabilities/AGENTS.md`, and `modeling_mcp/AGENTS.md` package paths; do not derive expected counts dynamically.
- [ ] Run acceptance/static link/TOML tests and independent docs/config review.
- [ ] Run the complete `pytest tests -q` suite GREEN at the 92/55/37 inventory before review or commit.
- [ ] Commit: `docs: establish the M1a context contracts`.

### Slice A12.4: acceptance map and final gate

- [ ] Add REDs fixing every section-4 node name before policy code; add synthetic two-phase/pointer/failure mutation tests and narrow A11 transition REDs.
- [ ] Implement JUnit exact-node capture, policy validation, current-run acyclic materialization, report 0.2.0, 15-check profile, and empty A12 incomplete group while retaining literal `92 total = 55 Python + 37 non-Python`.
- [ ] Modify `tests/reproducibility/test_m1a_repeatability.py` in this slice to freeze fixed raw-byte SHA-256 constants for all five final non-Python assets and exact presence of all seven new package members; do not derive expected counts or hashes dynamically.
- [ ] Run focused acceptance/reproducibility/Harness tests; run real verify and inspect all seven files.
- [ ] Run the complete `pytest tests -q` suite GREEN at the unchanged 92/55/37 inventory before review or commit.
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

Final PASS requires doctor exit 0 for healthy STORAGE_READY after bootstrap, exact 15/15 Harness PASS, required skips 0, empty incomplete groups, A-01..A-10 PASS with current-run exact-node proof, exact seven evidence files, report/map 0.2.0/0.1.0, 37 non-Python assets, 92 synthetic wheel items, literal presence of both new Python modules, fixed hashes for all five new non-Python assets, packaged/docs template byte identity, unchanged core catalog/18 tool Schemas, ignored evidence output, and clean source tree.

## 8. Review traceability

| Review finding | Binding sections |
| --- | --- |
| C1 failure publication | 4.1, 5 |
| C2 acyclic report/artifact inputs | 4.1-4.2 |
| C3 complete diagnostic graph | 2.3, 3.2 |
| I1 finite DTO/branches | 2.1-2.2 |
| I2 doctor issues/check/state map | 3.1-3.2 |
| I3 clause-complete literal nodes | 4.3 |
| I4 bare-array pointers | 4.2 |
| I5 no current/recursive evidence tests | 4.2, 5 |
| I6 deep lifecycle | 3.3 |
| I7 37/92 package transition | 5 |
| M1 UTF-8 order | Global Constraints, 2.1, 4.2 |
| M2 Schema failure stdout/stderr | 3.2 |
| Addendum review C1 current-run node evidence | 4.1, 4.3, 5 |
| Addendum review I1 installed template authority | 1, 3.2, 5 |
| Addendum fix2 C1 parameterized family evidence | 4.1, 4.3, 5 |
| A12.1 WAL remediation: stable raw capture and owned consolidation | 1, 2.3, 3.2-3.3, 6 |
| A12.1 WAL remediation: per-relation overflow isolation | 2.1-2.2, 6 |
| WAL review C1 transport-only consolidation / Store-owned diagnostics | 2.2-2.3, 3.2, 6 |
| WAL review C2 complete 37/92 package inventory | 4.3, 5-7 |
| WAL review I1 typed finite snapshot exception | 2.3, 3.2, 6 |
| Technical C1 held source lock is metadata-only | 2.3, 6 |
| Technical I2 render only after both cleanups | 2.3, 3.2-3.3, 6 |
| Technical I3 destination and cooperative-time bounds | 2.3, 6 |
| Technical I4 empty pre-Store issue provenance | 3.1-3.2, 6 |
| Technical I5 literal A12.1/A12.2 test ownership | 6 |
| Technical M1 narrowed live-Store preservation | 1, 2.3 |
| Technical M2 idle/active SHM causality | 2.3, 6 |
| Slice-count clarification: every A12 commit has a literal GREEN wheel inventory | 1, 5-7 |
| Windows probe correction: raw-writer exclusion via read-only in-memory backup and serialize-only filesystem output | 2.3, 6 |
| Windows probe fix1: guarded empty WAL sentinel closes absent-name create race | 2.3, 6 |
| Windows probe fix2: guarded empty SHM/private WAL-index and corrected memory/serialize peak/progress bounds | 2.3, 6 |
