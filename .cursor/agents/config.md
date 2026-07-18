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
