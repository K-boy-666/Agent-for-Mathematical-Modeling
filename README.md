# Math Modeling MCP

This repository contains the locked Python 3.11 project for the local math
modeling MCP milestone work.

Install the project and its development tools:

```powershell
uv sync --locked --group dev
```

Inspect the command-line interface:

```powershell
uv run --locked --no-sync modeling --help
uv run --locked --no-sync modeling verify --help
```

The `modeling-mcp` script name is reserved for the production STDIO server.
Verification checks are registered in a later milestone task.
