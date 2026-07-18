# config

Configuration and operating constraints for the Web3 orchestrator agent.

**Agent prompt:** `.cursor/agents/web3-orchestrator.md`  
**Discipline & boundaries:** `.cursor/agents/rules.md`  
**Global contract:** `AGENTS.md`  
**MCP servers:** `.cursor/mcp.json`

---

## Purpose

Configuration and operating constraints for the Web3 orchestrator agent.

## Defaults

- Use plan-first execution.
- Prefer static analysis before simulation.
- Use the minimal viable tool set.
- Escalate to deeper analysis only when evidence supports it.

## Required inputs

- Repository path or contract address.
- Target chain.
- Audit goal.
- Whether the target is deployed, local, or testnet.

## Behavior rules

- Ask one clarifying question at a time when needed.
- Never assume an implementation behind a proxy until verified.
- Never rewrite unrelated files.
- Prefer reproducible checks over speculative reasoning.
- Keep each run focused on a single security objective.

## MCP tool order (`.cursor/mcp.json`)

1. **solidity-audit** — Slither, SWC, parse_contract
2. **foundry** — forge build/test, cast, fork PoC
3. **chainstack** — RPC, indexer, on-chain context
4. **faro-fino** — second-opinion deep scan

Merge findings with source tags; dedupe before report.

## Output contract

- Summary first.
- Findings table second.
- Notes last.
- Include evidence for every claim.

## Secrets

API keys in MCP `env` only — never in agent prompts. See `.env.example` (`CHAINSTACK_API_KEY`, `ETH_RPC_URL`).

## Personal CFO (Plaid) — separate stack

Traditional finance read-only — **not** mixed with Web3 audit reports unless user asks.

| Item | Path |
|------|------|
| Agent | `.cursor/agents/personal-cfo-agent.md` |
| MCP | `plaid-cfo` in `.cursor/mcp.json` |
| Skill | `.cursor/skills/plaid-cfo-mcp/SKILL.md` |

Tool order: `detect_plaid_config` → accounts → transactions → holdings → liabilities → `plaid_cfo_summary`.

## Desktop target pool (тест ЦЕЛИ)

| Step | Command |
|------|---------|
| Sync from Mac | `scp -r ~/Desktop/тест\ ЦЕЛИ user@host:/workspace/data/pentest/targets/` |
| Local sync | `bash scripts/sync-desktop-targets.sh ~/Desktop/тест\ ЦЕЛИ` |
| Ingest | `python3 scripts/ingest-target-pool.py --root $SAMSON_TARGETS_DIR` |
| Dry-run | `python3 scripts/ingest-target-pool.py --root $SAMSON_TARGETS_DIR --dry-run` |

Default VPS path: `data/pentest/targets/` (seed: `web3-field-targets.txt`).  
Loader: `samson/core/target_loader.py` → `artifacts/target-pool/ingested-pool.json`.
