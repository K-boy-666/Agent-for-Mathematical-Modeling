# CUMCM-2022-A-Q1 C1 contest vertical slice implementation plan

> Implement only after M1a-0R, A1–A12, and the M1a Hard Gate pass. Each task
> uses strict RED → GREEN → regression → staged diff/check → one commit.

**Goal:** deliver the approved C1 product-validation preview without claiming
or silently implementing the deferred remainder of M1b.

**Authority:** `../specs/2026-07-23-cumcm-2022-a-q1-contest-vertical-slice-design.md`.

## Guardrails

- Do not begin any C1 implementation during M1a-0R.
- Keep the M1 parent as the only owner of SQLite, locks, state transitions, and
  artifact publication.
- The worker is short lived, has no database or project-root access, has a
  60-second hard timeout and 16 MiB output ceiling, and never retries math.
- MMIR execution is blocked until explicit confirmation of the exact revision.
- Solver and independent validators must not import one another.
- Raw official assets stay user-local, read-only, content addressed, and
  uncommitted.

## Ordered implementation tasks

### C1.1 — Preview contracts and stable errors

Write failing strict-schema/dispatch tests, then add request/result contracts
for `register_problem_assets`, `put_subproblem_mmir`,
`confirm_subproblem_mmir`, and `export_subproblem`. Add the approved stable
errors and keep all existing M1a tools compatible. Regression: all M1a
contract, adapter, and STDIO tests.

### C1.2 — Read-only asset snapshots

Write failing hash/schema/path tests, then register content-addressed snapshots
for the five official benchmark assets. Mismatched assets remain usable as
ordinary assets but fail the official benchmark classification. Regression:
project-root confinement, read-only behavior, and no committed raw asset.

### C1.3 — Versioned MMIR confirmation

Write failing unconfirmed/stale-revision tests, then persist generated MMIR,
its static-equilibrium assumption, asset references, and explicit confirmation
of one immutable revision. `run_experiment` must return
`MMIR_NOT_CONFIRMED` before execution if confirmation is absent or stale.

### C1.4 — Isolated worker protocol

Write failing timeout/protocol/size/no-access tests, then add the minimal
short-lived execution envelope. The worker receives only versioned capability
input, deadline, and limits. Prove database/project-root access is absent,
whole process-tree timeout is 60 seconds, output is capped at 16 MiB, and no
automatic mathematical retry occurs.

### C1.5 — Coupled-heave production solver

Write failing golden-grid/equation/case tests, then implement
`dynamics.coupled_heave/0.1.0` with DOP853, `rtol=1e-9`, `atol=1e-11`.
Implement the linear and power-law damping cases as distinct
Experiments/Attempts sharing one confirmed MMIR and asset snapshots. Assert
exactly 898 samples at `0.2*i`, ending at 179.4 seconds.

### C1.6 — Independent validators

Write failing forged-result and convergence tests, then implement the linear
augmented-state matrix-exponential reference and power-law fixed-step RK4
references at 0.01 and 0.005 seconds. Require production/reference
`rtol=2e-4`, `atol=2e-6`, and normalized energy-balance closure `<=1e-3`.

### C1.7 — Fail-closed exports

Write failing blocked-export, workbook-shape, and provenance tests, then create
the two official workbooks, time-series figures, result card, and complete
provenance. Preserve the two-row official header, five columns, 898 finite data
rows, and exact 0.2-second spacing. Export only when both validations are
PASSED.

### C1.8 — Harness and real-host gate

Write failing C1 evidence-map tests, then extend the single verification entry
with `modeling verify --milestone c1`. It must exit zero with no required skip.
Capture a real official Codex host trace proving create, register, put/confirm
MMIR, two runs, two validations, and export via MCP with no shell calculation.

## C1 Hard Gate

PASS requires all C1 focused/regression suites, the complete M1a profile, worker
security/timeout evidence, both independent validations, exact workbook/grid
checks, asset provenance, and the real Codex MCP trace. A failure blocks the
deferred M1b route and must not be converted into a relaxed tolerance, skipped
check, implicit MMIR confirmation, solver/validator coupling, or shell
calculation.
