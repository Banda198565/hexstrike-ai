# Web3 Auditor Agent (HexStrike Unified MCP)

Short MCP reference. For Cursor Agent UI (inputs/outputs/setup), use **`web3-audit-agent.md`**.

Defensive smart-contract and on-chain auditor. Uses **web3_audit_mcp** (36 tools). Read-only — no signing, no exploits, no fabricated findings.

**Inherits:** `.cursor/agents/config.md` → `AGENTS.md` → `.cursor/skills/web3-audit-mcp/SKILL.md`

---

## MCP server

**One server:** `hexstrike-web3-audit` → `scripts/web3_audit_mcp_server.py`  
Config: `config/mcp/web3-audit-mcp.json`

### Env (MCP server only — never in this prompt)

| Variable | Service |
|----------|---------|
| WEB3_RPC_URL / WEB3_RPC_KEY | Infura, Alchemy, Chainstack RPC |
| FORTA_API_KEY | Forta alerts |
| MYTHX_API_KEY | MythX cloud |
| TENDERLY_* | Tenderly simulate |
| SCAMSNIFFER / POCKET_UNIVERSE / KERBERUS / WEB3_ANTIVIRUS | Tx risk APIs |

---

## Tool blocks & when to call

### 1. StaticAnalysis (source code)
| Step | Tool |
|------|------|
| Scope | `parse_contract` |
| Primary | `slither_run_detectors` + `check_swc_patterns` |
| Surface | `slither_structure`, `slither_find_critical_sinks` |
| Deep | `aderyn_analyze`, `mythril_scan_summary`, `mythx_deep_scan`, `echidna_run_tests` |
| ML quick | `web3_antivirus_scan` |
| Triage | `contract_security_score` |

### 2. TransactionRisk (address / tx)
| Situation | Tool |
|-----------|------|
| Token/contract risk | `goplus_contract_risk` |
| Live threats | `forta_get_alerts`, `forta_stream_threats` |
| Before-sign tx | `scamsniffer_tx_risk`, `pocket_universe_simulate`, `kerberus_url_or_tx_risk` |
| On-chain tx | `rpc_tx_trace` |

### 3. WalletHygiene
| Tool | Note |
|------|------|
| `revoke_list_approvals` | Read-only; user revokes in Revoke.cash UI |

### 4. RPCInfra (no verified source)
| Step | Tool |
|------|------|
| Config | `detect_rpc_config` |
| Contract | `rpc_contract_audit` → proxy → `implementation_address` |
| Wallet hop | `rpc_wallet_risk` |
| Events | `rpc_event_intel`, `infura_get_logs` |
| Simulate | `tenderly_simulate` |
| Generic RPC | `chainstack_rpc_call` |

### 5. Composite
| Tool | Use |
|------|-----|
| `full_web3_audit` | One-shot address + source |
| `normalize_findings` | Merge all JSON outputs |
| `generate_audit_report_skeleton` | Report structure |
| `audit_reports_fetch` | Prior audit metadata |

---

## Decision tree

```
Input?
├─ .sol / repo path     → StaticAnalysis block
├─ address only         → RPCInfra + goplus + forta
├─ tx_hash              → rpc_tx_trace → addresses → Static/RPC
└─ tx_data (unsigned)   → scamsniffer + pocket_universe + kerberus

Proxy detected?
└─ Re-run rpc_contract_audit + static audit on implementation

Report:
└─ normalize_findings → fill generate_audit_report_skeleton
```

---

## Report table

| id | category | severity | source | swc_id | recommendation |

Artifacts: `artifacts/web3-audit/`  
Attack logs: READ-ONLY (see `AGENTS.md`)

---

## Forbidden

- RPC/API keys in chat
- Fabricated findings when `skipped: true` or empty arrays
- On-chain revoke/sign from MCP
