# M1a-0 Codex MCP feasibility spike

This disposable spike has a 48-hour go/no-go rule: within the timebox, a trusted
Codex session must start this STDIO MCP server, call `root_finding` once, and
return a verified finite result for `x*x-2`. Its generated evidence is kept in
`build/feasibility/m1a-0/`.

The sole 2026-07-23 host-evidence remediation supersedes only the failed
Attempt 1/2 host gate. It accepts raw official Codex CLI JSONL or a
platform-generated Codex Desktop/IDE rollout export and normalizes the selected
thread/turn to `m1a0-host-evidence/1`. A Desktop/IDE fork-all export must be
scoped with its exact `turn_id`; inherited history is not counted as activity
in that turn.

Run the direct and generic STDIO checks with:

```powershell
uv lock
uv sync --locked --group dev
uv run --locked --no-sync pytest spikes/m1a_0/test_spike.py -q
```

For the real Codex smoke, materialize the ignored project-local configuration
from the portable template, establish normal project trust in Codex, then run:

```powershell
uv lock --check
uv run --locked --no-sync pytest spikes/m1a_0/test_spike.py -q
uv run --locked --no-sync python -m compileall -q spikes/m1a_0
uv run --locked --no-sync python spikes/m1a_0/configure_codex.py
codex mcp list
$prompt = 'Use only the modeling_spike MCP server and do not run shell commands. Call root_finding exactly once with equation x*x-2, lower 0, upper 2, and tolerance 1e-10. Return the tool result without doing your own calculation.'
codex exec --ephemeral --json --sandbox read-only $prompt | Tee-Object -FilePath 'build/feasibility/m1a-0/attempt-2/codex-transcript.jsonl'
uv run --locked --no-sync python spikes/m1a_0/verify_codex_transcript.py build/feasibility/m1a-0/attempt-2/codex-transcript.jsonl
```

Normalize and verify a platform-generated Desktop/IDE rollout with:

```powershell
uv run --locked --no-sync python spikes/m1a_0/verify_codex_transcript.py `
  RAW-ROLLOUT.jsonl --source task-export --turn-id TURN-ID `
  --normalized-output NORMALIZED.json
```

The normalized record includes the Codex host family/surface, selected
thread-or-turn ID, one server/tool/arguments/structured result, the SHA-256 of
the complete raw evidence file, MCP-call count, and shell-call count. PASS
requires exactly one `modeling_spike/root_finding` call with the fixed
arguments and zero shell/command calls.

`configure_codex.py` replaces the template marker with this checkout's
absolute path and writes `.codex/config.toml` atomically. Verify the saved
JSONL transcript with:

```powershell
uv run --locked --no-sync python spikes/m1a_0/verify_codex_transcript.py build/feasibility/m1a-0/attempt-2/codex-transcript.jsonl
```

This is not production code and must not be reused by or imported into any
future formal package. A failed feasibility gate blocks A1; it must not lead to
a custom MCP protocol or a host-specific core abstraction.
