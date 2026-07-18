---
name: web3-rpc-mcp
description: Read-only Web3 RPC scanner via HexStrike MCP. RPC keys live in MCP server env, not agent prompts. Use for contract audit, tx trace, wallet risk, event intel on EVM chains.
---

# Web3 RPC MCP

MCP server: `scripts/web3_rpc_mcp_server.py`  
Config: `config/mcp/web3-rpc-mcp.json`  
Registry: `config/mcp/web3-rpc-tools.registry.json`

## Credential model (critical)

- `WEB3_RPC_URL` + `WEB3_RPC_KEY` → set in **MCP server `env`** (Cursor `mcp.json`)
- Per-chain overrides: `WEB3_RPC_URL_POLYGON`, `WEB3_RPC_KEY_BSC`, etc.
- Agent sees tools + redacted `rpc_url_redacted` — **never** paste keys into prompts
- Fallback: `config/web3-rpc-chains.json` public nodes or `config/rpc_config.json` if env unset

## Agent strategy

```
1. detect_rpc_config          — confirm RPC reachable before scans
2. rpc_contract_audit         — unknown contract address (bytecode, proxy, opcodes)
3. rpc_wallet_risk            — EOA or contract address triage
4. rpc_tx_trace               — suspicious tx hash (delegatecall, revert, log volume)
5. rpc_event_intel            — mint/transfer anomalies for contract over block range
```

Decision tree:

| Situation | Tool |
|-----------|------|
| New contract address, no source | `rpc_contract_audit` |
| Wallet funded attack / drainer hop | `rpc_wallet_risk` → then `rpc_tx_trace` on funding tx |
| Confirmed exploit tx | `rpc_tx_trace` first |
| Token mint/withdraw spike | `rpc_event_intel` with Transfer topic |
| Proxy at address | `rpc_contract_audit` → re-run on `implementation_address` |

Combine with **Solidity Audit MCP** when verified source is available (`onchain_metadata` + `parse_contract`).

## Tools

| Tool | Input | Output |
|------|-------|--------|
| `detect_rpc_config` | — | chain status, redacted URLs, `has_api_key` |
| `rpc_contract_audit` | address, chain | findings[], proxy, dangerous opcodes |
| `rpc_tx_trace` | tx_hash, chain | suspicious_steps[], trace_skipped |
| `rpc_wallet_risk` | address, chain | risk_flags[], risk_score |
| `rpc_event_intel` | address, chain, topic?, blocks | topic_summary[], anomalies[] |

## Non-emulation

- Read-only JSON-RPC — no signing, no transactions
- Empty findings = clean or RPC limitation — do not invent issues
- `trace_skipped: true` = debug module unavailable — state explicitly
- Full scam-label graph needs explorer API — RPC gives heuristics only

## Artifacts

`artifacts/web3-rpc/` — scan reports (not attack campaign logs)
