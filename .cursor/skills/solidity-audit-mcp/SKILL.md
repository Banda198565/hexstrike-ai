---
name: solidity-audit-mcp
description: Smart contract static analysis via HexStrike Solidity Audit MCP (Slither, Aderyn, SWC, Mythril, on-chain metadata). Use for Solidity audit/red-team workflows. Real tool output only — never fabricate findings.
---

# Solidity Audit MCP

MCP server: `scripts/solidity_audit_mcp_server.py`  
Registry: `config/mcp/solidity-audit-tools.registry.json`

## Auditor agent workflow (mandatory order)

1. **`parse_contract`** — compiler version, contracts, inheritance, modifiers, events, public/external functions, `detected_framework`
2. **`slither_run_detectors`** + **`check_swc_patterns`** — primary static findings + SWC `issues[]`
3. **`slither_structure`** — attack surface: state variables, call graph, external entry points
4. **`aderyn_analyze`** — if Aderyn installed; invariant-style `violations[]`
5. **Deployed address only:** **`onchain_metadata`** + **`mythril_scan_summary`** (bytecode/address)
6. **`normalize_findings`** — merge Slither/SWC/Aderyn/Mythril JSON into deduped list
7. **`contract_security_score`** — triage grade A–F for repo sorting
8. **`generate_audit_report_skeleton`** — fill final report sections from normalized findings

Optional: `compile_and_abi` (Foundry project), `check_openzeppelin_rules`, `full_audit`

## Core tools (spec v1.2)

| Tool | Output keys |
|------|-------------|
| `parse_contract` | `compiler_version`, `contracts[]`, `detected_framework` |
| `slither_run_detectors` | `detectors[]` (id, severity, locations, swc_refs) |
| `slither_structure` | `contracts[]`, `call_graph[]`, `external_entry_points[]` |
| `check_swc_patterns` | `issues[]` (swc_id, exploit_scenario_short) |
| `aderyn_analyze` | `violations[]` (rule_id, property, status) |
| `mythril_scan_summary` | `issues[]` (exploitability_estimate) |
| `contract_security_score` | `score`, `grade`, `metrics`, `top_risks` |
| `onchain_metadata` | `is_proxy`, `implementation_address`, `verified_source` |
| `compile_and_abi` | `abi`, `bytecode`, `deployed_bytecode` |
| `generate_audit_report_skeleton` | `sections` |
| `normalize_findings` | `deduped_findings[]` |

## Report format

After MCP tools return, write human report as table:

| id | category | severity | swc_id | exploitability | recommendation |
|----|----------|----------|--------|----------------|----------------|

Use only data from MCP JSON — if `skipped: true`, state tool missing; do not invent rows.

## Non-emulation

- Empty `findings` / `detectors` / `issues: []` = clean or tool unavailable
- `score: 100` with empty findings = no fabricated risk
- `onchain_metadata` / `fetch_onchain_data` = read-only RPC only

## Output artifacts

`artifacts/solidity-audit/` — tool reports (not attack campaign logs)
