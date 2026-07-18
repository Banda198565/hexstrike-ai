---
name: web3-audit-mcp
description: Unified Web3 audit MCP — static analysis (Slither/Mythril/Echidna), transaction risk (Forta/GoPlus/ScamSniffer), wallet hygiene, RPC/infra. All API keys in MCP env. Use for full smart-contract and on-chain audit workflows.
---

# Web3 Audit MCP (Unified)

MCP server: `scripts/web3_audit_mcp_server.py`  
Registry: `config/mcp/web3-audit-tools.registry.json`  
Config: `config/mcp/web3-audit-mcp.json`

Replaces separate Solidity + Web3 RPC MCP servers when you want one tool surface (36 tools).

## Blocks

| Block | Tools | Backend |
|-------|-------|---------|
| **StaticAnalysis** | Slither, SWC, Aderyn, Mythril, MythX, Echidna, Web3 Antivirus | Local binaries + cloud API keys |
| **TransactionRisk** | Forta, GoPlus, ScamSniffer, Pocket Universe, Kerberus | API keys in env |
| **WalletHygiene** | revoke_list_approvals | Read-only + Revoke.cash link |
| **RPCInfra** | rpc_*, chainstack_*, tenderly_*, alchemy_*, infura_* | WEB3_RPC_URL/KEY |
| **Composite** | full_web3_audit, normalize_findings, detect_web3_audit_stack | Orchestrates blocks |

## Agent workflow (full audit)

```
1. detect_web3_audit_stack
2. Source path  → parse_contract → slither_run_detectors → check_swc_patterns → slither_structure
   Address only → rpc_contract_audit → onchain_metadata → goplus_contract_risk
3. aderyn_analyze / mythril_scan_summary (optional)
4. forta_get_alerts + rpc_wallet_risk (address)
5. rpc_tx_trace (if tx_hash) + scamsniffer_tx_risk / pocket_universe_simulate (if tx_data)
6. normalize_findings → generate_audit_report_skeleton
```

## Credential rules

- Never embed keys in prompts — only `mcp.json` env
- GoPlus works without key (public API)
- `skipped: true` = configure env or install binary — do not invent findings

## Non-emulation

Same as `solidity-audit-mcp` and `web3-rpc-mcp` skills — real tool output only.

## Artifacts

`artifacts/web3-audit/`
