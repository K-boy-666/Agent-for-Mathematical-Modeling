# CUMCM-2022-A-Q1 contest vertical slice — approved design addendum

- Date: 2026-07-23
- Status: approved
- Authority: addendum to `2026-07-16-math-modeling-mcp-design.md`
- Route: `M1a-0R → M1a → C1 → deferred M1b`

## 1. Governance and scope

M1a-0R is the only remediation authorized after preserved M1a-0 Attempts 1
and 2. It has a 14,400-second deadline from its immutable start record. PASS
requires both the generic real MCP child-process round trip and one raw
platform-generated record from an official Codex CLI, Desktop, or IDE surface.
The host record must prove exactly one `modeling_spike/root_finding` call with
the approved arguments, no shell or command calls, and the independently
recomputed residual contract. PASS permits the first baseline commit; A1 starts
later and must not reuse Spike code.

C1 starts only after A1–A12 and the M1a Hard Gate. It is a product-validation
preview for CUMCM 2022 Problem A, Question 1. It deliberately pulls forward
only the necessary M2/M2.5/M3/M4 behavior. It does not claim complete RFC 8785
conformance, stable 1.0 contracts, Windows/Ubuntu release evidence, complete
crash-window injection, External Plugin support, a general workflow engine, or
full autonomous modeling. Those remain in the deferred roadmap.

## 2. Public preview contract

C1 adds four preview tools:

```text
register_problem_assets
put_subproblem_mmir
confirm_subproblem_mmir
export_subproblem
```

It continues to use `create_project`, `get_project_status`,
`list_capabilities`, `run_experiment`, and `validate_experiment`. Codex
generates MMIR, but execution is forbidden until the user explicitly confirms
the exact revision. The linear and power-law damping cases are separate
Experiments/Attempts that share the confirmed MMIR revision and immutable asset
snapshots.

## 3. Mathematical contract

Capability ID: `dynamics.coupled_heave/0.1.0`.

```text
(m_f+m_a) x_f'' + B x_f' + K_h x_f
  + k(x_f-x_o) + D(x_f'-x_o') = F cos(omega t)

m_o x_o'' + k(x_o-x_f) + D(x_o'-x_f') = 0

K_h = rho g pi r^2
```

Parameters:

```text
omega=1.4005 s^-1    m_a=1335.535 kg
B=656.3616 N s/m     F=6250 N
m_f=4866 kg          m_o=2433 kg
r=1 m                rho=1025 kg/m^3
g=9.8 m/s^2          k=80000 N/m
```

Damping cases:

```text
linear:    D(q)=10000 q
power_law: D(q)=10000 |q|^0.5 q
```

Coordinates are deviations from static equilibrium. Gravity, spring natural
length, and static preload cancel in the increment equations. This assumption
must be present in both confirmed MMIR and exported provenance.

The production solver is `solve_ivp(method="DOP853")` with `rtol=1e-9`,
`atol=1e-11`, and a 60-second worker hard timeout. Output times are exactly
`t_i=0.2*i`, `i=0..897`: 898 rows ending at 179.4 seconds. The non-grid exact
40-period endpoint must not be appended.

## 4. Independent validation

- Linear damping uses an augmented-state matrix exponential.
- Power-law damping uses independent fixed-step RK4 at both 0.01 and 0.005 s.
- Production/reference comparison uses `rtol=2e-4`, `atol=2e-6`.
- Normalized energy-balance closure error is at most `1e-3`.
- Solver and validator do not import one another.

## 5. Assets and exports

Official assets are user-local, read-only, content addressed, and never
committed. The verified-source SHA-256 values are:

```text
A题.pdf         E29940EB9EB9382DEB8ECCB459C73CC47F0080483B8B75F9977830C987162253
附件3.xlsx      50A5DD70F04DFB0A57FB2602422DC7999B30AAD54DDC02353F5B8F01423FD612
附件4.xlsx      C8EFF812F5980D955B4F0E587C5F7A357B2571D8D903FCB4913FBA77C7354D6D
result1-1.xlsx  83ED6E0F2EBCDBDCB53E99A3BFEBFBD8DC16141F91396EBA8806E781D7809C7A
result1-2.xlsx  CC0ABBCEFF32F425E738A3D9C0534FC3FBAB4B2A1D2D86B8DC4D51229FB820BF
```

A mismatched file may be registered as an ordinary project asset but cannot
pass the official C1 benchmark gate. Required exports are `result1-1.xlsx`,
`result1-2.xlsx`, time-series figures, a 10/20/40/60/100-second result card,
and parameter, assumption, run, validation, and asset provenance.
`export_subproblem` fails closed unless both validations are PASSED.

## 6. Reliability and acceptance

The parent owns SQLite, locks, states, and artifact publication. Each
short-lived worker receives no database or project-root access. The hard
timeout is 60 seconds, maximum output is 16 MiB, and mathematical execution is
never retried automatically.

Stable errors cover asset missing/hash/schema failures, `MMIR_NOT_CONFIRMED`,
unsupported capability version, numerical failure, worker timeout/protocol
failure, validation failure, and export blocked. `modeling verify --milestone
c1` must exit zero with no required skip. Each Excel export preserves the
official two-row header and contains exactly 898 finite data rows, five
columns, and exact 0.2-second spacing. A real Codex host must complete create,
register, put/confirm MMIR, two runs, two validations, and export through MCP,
without shell calculation.
