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
| `config/workflow/campaign-trace.schema.json` | Attack log for skill-builder |
| `config/skill-builder-prompt.md` | R1 generalization prompt (attack log) |
| `config/skill-builder-nuclei-prompt.md` | R1 Nuclei findings interpretation |
| `config/workflow/nuclei-step-log.example.json` | Example vuln_scan step (schema, not live) |
| `scripts/skill-builder.py` | trace / nuclei step → R1 → SKILL.md + MCP stub |

## Skill-builder (auto skillify)

After **successful** campaigns (live logs in `artifacts/workflow/traces/` — read-only for Cursor):

```bash
# Campaign trace → skill
python3 scripts/skill-builder.py demo-trace          # copies EXAMPLE to artifacts — not a live run
python3 scripts/skill-builder.py build <trace.json>
python3 scripts/skill-builder.py pending            # process pending_skillify queue

# Nuclei vuln_scan step → discovery skill
python3 scripts/skill-builder.py demo-nuclei-step     # copies EXAMPLE — not a live run
python3 scripts/skill-builder.py build-nuclei <nuclei_step_log.json>
python3 scripts/skill-builder.py analyze-nuclei <nuclei_step_log.json>
```

Pipeline: log (read-only) → R1 → skill JSON → `.cursor/skills/generated/<id>/` + MCP stub + `catalog.json`.
**Never write back into log directories.**

R1 rules for Nuclei skill-builder: use only `output.findings[]` from the step log; empty → `interesting_findings: []`.


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
  "_note": "SCHEMA EXAMPLE — not a live target or scan result",
  "step_id": 1,
  "skill_id": "pentest_recon",
  "depends_on": [],
  "input": {
    "targets": [{ "host": "{{target_host}}", "ports": "top-1000" }],
    "tools": ["nmap", "httpx"],
    "authorization_ref": "{{authorization_ref}}"
  },
  "rationale": "Passive port/service map before chain building",
  "expected_artifact": "artifacts/recon-{{campaign_id}}.json"
}
```

## Do not

- Execute nmap, metasploit, GSM AT commands, or on-chain txs from Cursor
- Edit live attack logs (`artifacts/workflow/*`, `logs/**`, `**/atk-*.json`) — read-only
- Present `demo-*` CLI output or `*.example.json` files as live campaign results
- Fabricate `findings[]`, loot, or session data without MCP/orchestrator artifacts
- Add Cursor-side topic filtering — policy is in orchestrator
- Return free-text plans without JSON schema
