# AGENTS.md

## Cursor Cloud specific instructions

### What this project is
HexStrike AI is a Python cybersecurity automation platform with three entrypoints:
- `hexstrike_server.py` — Flask API server (the main application) that exposes 150+ tool/intelligence endpoints. Binds `0.0.0.0:8888` (override with `HEXSTRIKE_PORT` / `--port`). Health at `GET /health`.
- `hexstrike_mcp.py` — FastMCP stdio client that proxies MCP tool calls to the API server (`--server http://127.0.0.1:8888`). It stays running as a stdio server; it is normally launched by an MCP-capable AI client, not by hand.
- `hexstrike_cli.py` — thin CLI over the API server (e.g. `python hexstrike_cli.py technology-detect example.com`, `... telemetry`).

### Running (dev)
- The update script creates a virtualenv at `hexstrike-env/` and installs `requirements.txt`. Always use that interpreter: `./hexstrike-env/bin/python`.
- Start the server: `./hexstrike-env/bin/python hexstrike_server.py` (add `--debug` for verbose). Verify: `curl -s http://localhost:8888/health`.
- Quick end-to-end smoke test (no external tools needed):
  `curl -s -X POST http://localhost:8888/api/intelligence/analyze-target -H 'Content-Type: application/json' -d '{"target":"example.com","analysis_type":"comprehensive"}'`

### Non-obvious caveats
- The 150+ external security tools (nmap, nuclei, sqlmap, ghidra, etc.) are NOT installed and are intentionally out of scope for the dev environment. `/health` will show most `tools_status` as `false` and `all_essential_tools_available: false` — this is expected. The core framework, `/api/intelligence/*`, `/api/cache/*`, `/api/telemetry`, and other pure-Python endpoints still work. Any endpoint that shells out to a missing tool will just report the tool as unavailable.
- `import angr` fails at import time in this environment (pycparser 3.x removed the `CLexer.filename` setter). This does NOT affect the server: the server never imports `angr` at module load — it only runs angr via generated subprocess scripts (the `/api/tools/angr` endpoint). Everything else, including `from pwn import *`, imports fine.
- There is no automated test suite and no lint config committed in the repo (only third-party tests live inside `hexstrike-env/`). "Linting" is limited to `python -m py_compile` / `ast.parse` syntax checks.
- The three source files are large (`hexstrike_server.py` is ~700KB); prefer targeted search over full reads.
