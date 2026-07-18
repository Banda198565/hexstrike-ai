---
name: gated-orchestrator-mcp
description: Gated MCP for R1 orchestrator transport — read-only RPC and controlled filesystem. Use for all on-chain reads and report writes in web3-orchestrator workflows.
---

# Gated Orchestrator MCP

Primary **transport boundary** — R1 orchestrates; MCP enforces permissions.

## Server

| Item | Path |
|------|------|
| MCP server | `scripts/gated_orchestrator_mcp_server.py` |
| Config | `config/gated-mcp.json` |
| Cursor wiring | `.cursor/mcp.json` → `gated-orchestrator` |

## RPC tools (read-only)

| Tool | RPC method | Notes |
|------|------------|-------|
| `rpc_get_block` | eth_getBlockByNumber | Keys from MCP env only |
| `rpc_get_contract_state` | eth_getStorageAt | Per slot_keys |
| `rpc_get_events` | eth_getLogs | max 5000 block range, 500 events |
| `rpc_trace_transaction` | debug_traceTransaction | Returns frames[] |
| `rpc_simulate_call` | eth_call | Never broadcasts |

Forbidden server-side: `eth_sendTransaction`, `eth_sendRawTransaction`, `personal_sign`.

## Filesystem tools

| Tool | Mode | Allowlist |
|------|------|-----------|
| `fs_list_dir` | read | config/gated-mcp.json read_roots |
| `fs_read_file` | read | contracts/, config/, reports/, artifacts/web3-audit/ |
| `fs_create_report_file` | write | reports/, artifacts/web3-audit/ only |
| `fs_read_report_index` | read | reports/ |
| `fs_edit_file` | dry_run default | apply needs HEXSTRIKE_FS_APPLY=1 + edit_roots |

Immutable (blocked): `artifacts/workflow/traces/`, `attack_logs/`, `nuclei_steps/`.

## Orchestrator rule

At end of every audit report run:

```
fs_create_report_file(
  directory="artifacts/web3-audit",
  filename="<run-id>.md",
  content=<full report markdown>,
  overwrite=false
)
```

## Tests

```bash
python3 scripts/test_gated_mcp_runner.py
python3 -m py_compile scripts/gated_orchestrator_mcp_server.py
```
