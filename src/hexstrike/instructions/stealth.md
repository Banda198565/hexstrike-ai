# Stealth Transport — Operational Protocol

## Role
Mask outbound RPC/API traffic for operator OPSEC — UA rotation, jitter, optional proxy.

## Scope
- All `core.monitor` JSON-RPC calls
- `mcp_rpc_gateway`, `mcp_shodan`, `mcp_blockscout_api` HTTP requests
- `skill.recon_osint` passive probes

## Configuration
| Env var | Default | Purpose |
|---------|---------|---------|
| `HEXSTRIKE_STEALTH` | `1` | Enable jitter + UA rotation |
| `HEXSTRIKE_PROXY` | — | HTTP(S) proxy URL |
| `HTTPS_PROXY` | — | Fallback proxy |

## Constraints
- Read-only recon — no active exploitation
- Do not disable TLS verification in production
- Log stealth status via `ContextBus` on transport errors

## MCP Bindings
Used as library by modules — not a standalone agent dispatch target.
