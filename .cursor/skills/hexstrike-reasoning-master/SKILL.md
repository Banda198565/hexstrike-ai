---
name: hexstrike-reasoning-master
description: HexStrike Reasoning-Master orchestration via DeepSeek R1. Use whenever the user mentions R1 orchestration, MCP skills catalog, scatter-gather planning, pentest/EVM/GSM mission decomposition, or JSON task contracts for HexStrike. Use for mission planning, skill selection, and typed JSON plans — never for direct tool execution (delegate to orchestrator).
---

# HexStrike Reasoning-Master

Plan multi-step missions using **typed MCP skills** + **DeepSeek R1**. Execution is always delegated to HexStrike Orchestrator.

## Files

| File | Purpose |
|------|---------|
| `config/reasoning-master.schema.json` | Master task + plan response schema |
| `config/skills/catalog.json` | Skill registry (14 skills) |
| `config/skills/schemas/*.json` | Per-skill input/output contracts |
| `config/reasoning-protocol.example.json` | Example mission |
| `src/hexstrike/llm/skill_catalog.py` | Catalog loader |

## Workflow

1. Load catalog: `config/skills/catalog.json`
2. Build or validate task JSON against `reasoning-master.schema.json`
3. Pass task to R1 → receive `plan_response` (steps with `skill_id` + typed `input`)
4. Orchestrator validates skill_ids ⊆ task.skills, then dispatches

## R1 prompt rules

- Output **JSON only** matching `plan_response` in master schema
- Each step: `skill_id` from catalog + `input` matching that skill's input schema
- Use `scatter_groups` for parallel batches (OSINT + EVM + recon)
- Do not invent skill_ids — only from task.skills list

## Skill layers

| Layer | Skills |
|-------|--------|
| infrastructure | `task_planner`, `scatter_gather`, `skillify` |
| pentest | `pentest_recon`, `exploit_chain_builder`, `credential_session` |
| blockchain | `evm_contract_analyze`, `vuln_pattern_matcher`, `exploit_generator_stub` |
| telecom | `gsm_sim800c_control`, `ss7_signaling_sim` |
| orchestration | `state_tracker`, `rollback_abort`, `cost_latency_monitor` |

## Example plan step

```json
{
  "step_id": 1,
  "skill_id": "pentest_recon",
  "depends_on": [],
  "input": {
    "targets": [{ "host": "lab.example.internal", "ports": "top-1000" }],
    "tools": ["nmap", "httpx"],
    "authorization_ref": "lab-scope-2026-001"
  },
  "rationale": "Passive port/service map before chain building",
  "expected_artifact": "artifacts/recon-lab-001.json"
}
```

## Do not

- Execute nmap, metasploit, GSM AT commands, or on-chain txs from Cursor
- Add Cursor-side topic filtering — policy is in orchestrator
- Return free-text plans without JSON schema
