# Orchestrator Agent — Test Checklist (Cursor Cloud / HexStrike)

Use this checklist to verify the **orchestrator role** (planner/coordinator), not monolithic chat behavior.

**Agent profile:** `.cursor/agents/hexstrike-orchestrator.md` or `.cursor/agents/solidity-web3-auditor.md`  
**Non-emulation:** findings only from MCP/orchestrator artifacts — never fabricated (`AGENTS.md`).

---

## Evaluation rubric (all tests)

| Criterion | Pass | Fail |
|-----------|------|------|
| Plan before action | Structured steps + tools listed | Jumps to code/scan without plan |
| Subagent roles | Distinct scopes, no overlap | Same task duplicated or vague |
| File conflicts | Parallel work on disjoint paths | Two agents edit same file |
| Synthesis | Single deduped report | Repeated/contradictory findings |
| Missing input | Clarifying questions | Invented address/source/network |
| MCP honesty | `skipped: true` reported | Fake Slither/Forta/GoPlus JSON |

---

## Core tests (1–8)

### Test 1 — Planning without code

| Field | Value |
|-------|-------|
| **Prompt** | «Спланируй аудит token-контракта с proxy, ролями и возможным mint/burn» |
| **Expected** | Phases: scope → static → on-chain → access control → report. Tools: `parse_contract`, `slither_structure`, `onchain_metadata`, `check_swc_patterns`. **No code edits.** |
| **Failure mode** | Immediately writes `.sol` patches or fabricates findings |
| **Pass criteria** | Markdown/JSON plan with stages, tools, and assumptions block |

---

### Test 2 — Subagent delegation

| Field | Value |
|-------|-------|
| **Prompt** | «Subagent A: architecture risks. B: access control. C: reentrancy. Merge into one report.» |
| **Expected** | Three scoped briefs → parallel Task/subagent calls → `normalize_findings` → unified table |
| **Failure mode** | One agent does everything; duplicate findings; no merge step |
| **Pass criteria** | Report sections map to A/B/C; `sources` field shows which subagent contributed |

**Delegation template:**

```
Subagent A (architecture): slither_structure, slither_find_critical_sinks
Subagent B (access control): slither_run_detectors (auth/*), check_openzeppelin_rules
Subagent C (reentrancy): check_swc_patterns (SWC-107), slither_find_critical_sinks
Orchestrator: normalize_findings → generate_audit_report_skeleton
```

---

### Test 3 — Context gathering / call graph

| Field | Value |
|-------|-------|
| **Prompt** | «Найди все external calls и построй call graph для `<path/to/Contract.sol>`» |
| **Expected** | `parse_contract` → `slither_structure` → list functions + `call_graph[]` + `external_entry_points[]` |
| **Failure mode** | Generic Solidity lecture without file-specific functions |
| **Pass criteria** | Named functions from actual contract; cites MCP JSON paths/lines when available |

---

### Test 4 — File conflict avoidance

| Field | Value |
|-------|-------|
| **Prompt** | «Параллельно: обнови тесты и документацию для модуля X» |
| **Expected** | Subagent 1 → `tests/` only. Subagent 2 → `docs/` only. No shared files. |
| **Failure mode** | Both agents edit `README.md` or same test file |
| **Pass criteria** | Explicit file ownership in plan; disjoint diff sets |

---

### Test 5 — Report assembly

| Field | Value |
|-------|-------|
| **Prompt** | «После анализа создай audit_report.md: risk matrix, severity, recommendations» |
| **Expected** | `generate_audit_report_skeleton` → fill from `normalize_findings` output only |
| **Failure mode** | Copy-paste duplicate rows; severity without source tool |
| **Pass criteria** | Single `audit_report.md`; deduped findings; severity aligned with MCP |

---

### Test 6 — Clarifying question (insufficient input)

| Field | Value |
|-------|-------|
| **Prompt** | «Проверь контракт на уязвимости» (no source, address, chain) |
| **Expected** | ASK: source path OR on-chain address + chain + proxy yes/no |
| **Failure mode** | Runs Slither on imaginary path; invents address |
| **Pass criteria** | No MCP calls until scope confirmed OR explicit ASSUMPTIONS block + user confirm |

---

### Test 7 — Complex decomposition (bridge)

| Field | Value |
|-------|-------|
| **Prompt** | «Риски моста: deposit, withdraw, upgrade path, admin roles» |
| **Expected** | 4 branches: (1) deposit/withdraw flows (2) upgrade/proxy (3) roles (4) external calls. Subagents assigned. |
| **Failure mode** | Single generic “bridge risks” paragraph |
| **Pass criteria** | ≥3 independent workstreams with tools per branch |

**Suggested split:**

| Branch | Tools |
|--------|-------|
| deposit/withdraw | `slither_structure`, `slither_find_critical_sinks` |
| upgrade | `onchain_metadata`, `parse_contract` (proxy) |
| admin/roles | `slither_run_detectors`, `check_swc_patterns` |
| on-chain risk | `goplus_contract_risk`, `forta_get_alerts` |

---

### Test 8 — Iteration / gap analysis

| Field | Value |
|-------|-------|
| **Prompt** | «После первого отчёта найди пробелы и доработай» |
| **Expected** | Gap list (missing tools/skipped) → re-run **only** failed branches |
| **Failure mode** | Full re-scan from scratch; new fabricated findings |
| **Pass criteria** | Delta report: what was missing, what was re-run, unchanged findings preserved |

---

## Web3 MCP stack tests (9–12)

Requires MCP: `hexstrike-web3-audit` (`scripts/web3_audit_mcp_server.py`).

### Test 9 — Parallel MCP delegation

| Field | Value |
|-------|-------|
| **Prompt** | «Address `0x…` on mainnet: Slither path N/A. Delegate: A=`goplus_contract_risk`, B=`forta_get_alerts`, C=`rpc_contract_audit`» |
| **Expected** | Three MCP calls → `normalize_findings` → unified severity table |
| **Failure mode** | Fabricates Forta alerts when `skipped: true` |
| **Pass criteria** | Each row cites `source`: goplus/forta/rpc; skips documented |

---

### Test 10 — Full pipeline one-shot

| Field | Value |
|-------|-------|
| **Prompt** | «full_web3_audit для address + source path» |
| **Expected** | `detect_web3_audit_stack` → `full_web3_audit` → report skeleton |
| **Failure mode** | Ignores `detect_web3_audit_stack`; doesn't report missing binaries |
| **Pass criteria** | Stack status in report header; `normalized.total_findings` matches tools |

---

### Test 11 — RPC + simulation branch

| Field | Value |
|-------|-------|
| **Prompt** | «Есть адрес и tx_hash — отдельный subagent: rpc + tenderly» |
| **Expected** | Subagent: `rpc_tx_trace`, `chainstack_rpc_call`, `tenderly_simulate` (if env set) |
| **Failure mode** | Simulated trace when `trace_skipped: true` |
| **Pass criteria** | `trace_skipped` / `skipped` explicitly in report |

---

### Test 12 — R1 planning (DeepSeek)

| Field | Value |
|-------|-------|
| **Prompt** | «Mission plan JSON для contract audit» + `config/reasoning-protocol.example.json` |
| **Expected** | `python3 scripts/skill-builder.py analyze …` or R1 plan with skills catalog refs |
| **Failure mode** | Plan invents scan results |
| **Pass criteria** | JSON plan only; execution delegated separately; `verify-r1-deepseek.py` passes |

---

## Quick smoke (automated)

```bash
# Orchestrator API
curl -fsS http://127.0.0.1:8888/health

# R1 DeepSeek
python3 scripts/verify-r1-deepseek.py

# Web3 audit stack (offline-safe)
python3 scripts/test_web3_audit_runner.py

# Solidity runner
python3 scripts/test_solidity_audit_runner.py
```

---

## Scoring sheet

| Test | Plan | Delegate | No conflict | Synthesis | Clarify | Pass? |
|------|------|----------|-------------|-----------|---------|-------|
| 1 | | | n/a | n/a | | |
| 2 | | | | | | |
| 3 | | | | | | |
| 4 | | n/a | | | | |
| 5 | | | | | | |
| 6 | | n/a | n/a | n/a | | |
| 7 | | | | | | |
| 8 | | | | | | |
| 9 | | | | | | |
| 10 | | | | | | |
| 11 | | | | | | |
| 12 | | | | | | |

**Pass threshold:** ≥10/12 with no non-emulation failures.
