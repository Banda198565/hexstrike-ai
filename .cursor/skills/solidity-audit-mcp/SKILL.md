---
name: solidity-audit-mcp
description: Smart contract static analysis via HexStrike Solidity Audit MCP (Slither, Aderyn, SWC, OZ heuristics). Use for Solidity audit workflows in Cursor. Real tool output only — never fabricate findings.
---

# Solidity Audit MCP

MCP server: `scripts/solidity_audit_mcp_server.py`  
Config: `config/mcp/solidity-audit-mcp.json`

## Recommended audit order (static analysis)

1. `detect_audit_tools` — slither / aderyn / mythril installed?
2. `parse_contract` — pragma, contracts, imports
3. `slither_run_detectors` — primary static analysis
4. `slither_functions` — external entry points
5. `check_swc_patterns` — SWC mapping
6. `slither_critical_sinks` — high-impact sinks for manual review
7. `check_openzeppelin_rules` — OZ hygiene heuristics
8. `run_aderyn` — optional formal-style patterns (if installed)
9. `list_vulnerabilities` — deduplicated list + `security_score`
10. `scan_contract` — one-shot aggregate (steps 2–8 summary)

Optional (heavy): `run_bytecode_scan_mythril`, `full_audit`

## Report format for Cursor agent

After MCP tools return, write human report as table:

| category | severity | swc_id | exploitability_hint | recommendation |
|----------|----------|--------|---------------------|----------------|

Use only data from MCP JSON — if `skipped: true`, state tool missing; do not invent rows.

## Non-emulation

- Empty `findings` / `vulnerabilities: []` = clean or tool unavailable
- `security_score: 0` with empty list = no fabricated risk
- `fetch_onchain_data` = read-only RPC

## Output artifacts

`artifacts/solidity-audit/` — tool reports (not attack campaign logs)
