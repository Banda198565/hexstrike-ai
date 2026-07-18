---
name: solidity-audit-mcp
description: Smart contract security audit via HexStrike Solidity Audit MCP. Use when analyzing Solidity/EVM contracts with Slither, Mythril, SWC patterns, OpenZeppelin heuristics, or read-only on-chain bytecode. Real tool output only — never fabricate findings.
---

# Solidity Audit MCP

Audit smart contracts through **HexStrike Solidity Audit MCP** (`scripts/solidity_audit_mcp_server.py`).

## MCP config

- `config/mcp/solidity-audit-mcp.json`
- Registry: `config/mcp/solidity-audit-tools.registry.json`

## Recommended audit order

1. `detect_audit_tools` — what is installed locally
2. `parse_contract` — pragma, contracts, imports
3. `run_static_analysis_slither` — primary static analysis
4. `check_swc_patterns` — SWC mapping + source heuristics
5. `check_openzeppelin_rules` — OZ import/guard hygiene
6. `run_bytecode_scan_mythril` — optional deep scan (slow)
7. `fetch_onchain_data` — read-only bytecode if address known
8. Or `full_audit` — runs parse → slither → swc → oz in one call

## Non-emulation

- Empty `findings[]` means tools found nothing or tool skipped — **do not invent CVEs**
- `skipped: true` + `skip_reason` → tell user to install tool, do not simulate output
- On-chain tool is **read-only** (`eth_getCode`) — no private keys, no txs
- Audit reports → `artifacts/solidity-audit/` — not attack campaign logs

## Cursor agent integration

Use with **HexStrike Orchestrator** agent. Execution policy remains in orchestrator; MCP returns real binary/RPC output only.

## Related catalog skills

- `evm_contract_analyze` — RPC contract model
- `vuln_pattern_matcher` — pattern matching in reasoning plans
