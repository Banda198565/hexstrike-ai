# config

Configuration and operating constraints for the Web3 orchestrator agent.

**Agent prompt:** `.cursor/agents/web3-orchestrator.md`  
**Discipline & boundaries:** `.cursor/agents/rules.md`  
**Global contract:** `AGENTS.md`  
**MCP servers:** `.cursor/mcp.json`

---

## Cloud Agent vs local orchestrator

| Layer | What it is | Source of truth |
|-------|------------|-----------------|
| `cursor.com/agents/bc-…` | One Cloud Agent **run** (session, branch, model) | Ephemeral — not versioned |
| `.cursor/agents/*.md` | Agent **prompt** (role, playbooks, output) | Git — this repo |
| `.cursor/mcp.json` | MCP server wiring for the **workspace** | Git — loaded by Cursor IDE / Cloud when repo is attached |
| `scripts/run-orchestrator-*.py` | Automated health + phased tests | Git — run in CI or before prod audits |

**Rule:** Do not infer orchestrator behavior from a Cloud Agent URL alone. The web/mobile card shows run status, not your rules or MCP stack. Work from the **repo checkout** where `.cursor/` lives (IDE or Cloud Agent bound to this repository).

Before any prod audit: confirm the run uses **this repo** and MCP servers are green (see Health checks below).

---

## Operating modes

Default if user does not specify: **test**.

| Mode | Trigger | Allowed | Forbidden |
|------|---------|---------|-----------|
| **test** | User says "test", CTF, `scripts/sandbox/contracts/`, local `.sol` only | Static analysis, read-only RPC on testnets, fork sims in Foundry | Mainnet write txs; edits to prod configs; audit of undeclared live funds without confirm |
| **prod** | User explicitly says "prod", "mainnet", "live", or gives a deployed address + chain | Read-only RPC, traces, events, metadata, static analysis on verified source | Any tx broadcast; exploit payloads; unconfirmed file edits; skipping MCP health |

**Mode header (required in every report):**

```
Mode: test | prod
Target: <path or 0x…>
Chain: <name or local>
MCP stack status: <servers ok / degraded list>
```

Switch to **prod** only when scope is confirmed. In prod, all on-chain ops are **read-only** unless user explicitly approves a gated PoC in an isolated fork.

---

## Defaults

- Use plan-first execution.
- Prefer static analysis before simulation.
- Use the minimal viable tool set.
- Escalate to deeper analysis only when evidence supports it.
- Start in **test** mode unless user declares prod/live scope.

## Required inputs

- Repository path or contract address.
- Target chain.
- Audit goal.
- Whether the target is deployed, local, or testnet.
- **Mode:** test or prod (ask if unclear).

## Behavior rules

- Ask one clarifying question at a time when needed.
- Never assume an implementation behind a proxy until verified.
- Never rewrite unrelated files.
- Prefer reproducible checks over speculative reasoning.
- Keep each run focused on a single security objective.
- On MCP failure: degrade gracefully — continue with available tools; never fabricate skipped output.

## MCP tool order (`.cursor/mcp.json`)

**Gated orchestrator (primary transport boundary):**

| Tool | Purpose |
|------|---------|
| `rpc_get_block` | Block metadata (read-only) |
| `rpc_get_contract_state` | Storage slots (read-only) |
| `rpc_get_events` | Event logs with range cap |
| `rpc_trace_transaction` | Tx trace frames |
| `rpc_simulate_call` | eth_call simulation only |
| `fs_list_dir` / `fs_read_file` | Read repo sources/config |
| `fs_create_report_file` | Write reports to `reports/` or `artifacts/web3-audit/` |
| `fs_read_report_index` | List existing reports |
| `fs_edit_file` | dry_run diff preview only (default) |

Config: `config/gated-mcp.json`. Server: `scripts/gated_orchestrator_mcp_server.py`.

**Do not** use raw `eth_sendTransaction` or edit source files outside gated tools. At audit end, call `fs_create_report_file`.

Extended stack (when needed):

1. **gated-orchestrator** — RPC read + FS boundary (default for orchestrator)
2. **solidity-audit** — Slither, SWC, parse_contract
3. **foundry** — forge build/test, cast, fork PoC
4. **chainstack** — RPC, indexer, on-chain context
5. **faro-fino** — second-opinion deep scan

Merge findings with source tags; dedupe before report.

### MCP health checks (run before prod work)

```bash
# Phased suite: MCP scripts + Bank.sol smoke + rules + BSC targets
python3 scripts/run-orchestrator-phased-tests.py

# Backend runner unit tests (offline-safe)
bash scripts/run-orchestrator-smoke-tests.sh
```

| Server | Minimum viable | Degraded if missing |
|--------|----------------|---------------------|
| solidity-audit | **required** — primary static | Stop — cannot complete audit plan |
| foundry | optional — local PoC | Label findings "hypothesis — no fork confirm" |
| chainstack | optional — uses public RPC fallback | Note `source: public_rpc` in report |
| faro-fino | optional — second opinion | Skip with `skipped: true` |

Agent must echo stack status in report header. If a tool returns `skipped: true` or `success: false`, include it in **Notes → MCP gaps** — do not invent replacement data.

## Observability & audit log

Every orchestrator run that invokes MCP must leave a trace:

| Artifact | Path | Contents |
|----------|------|----------|
| Run JSON | `artifacts/web3-audit/<run-id>.json` | tools called, params (redacted), raw paths, normalized findings |
| Report MD | `artifacts/web3-audit/<run-id>.md` or `reports/` | human summary |
| MCP raw | `artifacts/solidity-audit/`, `artifacts/web3-rpc/` | server-written; reference by path |

Log per tool call (in report **Appendix** or JSON):

- `tool`, `server`, `target`, `chain`, `success`, `skipped`, `finding_count`, `raw_report_path`

Severity decisions: one line per critical/high finding — **why** this severity (evidence source, not guess).

## Output contract

- Mode header first.
- MCP stack status second.
- Summary third.
- Findings table fourth.
- Notes + MCP gaps last.
- Include evidence for every claim.

## Secrets

API keys in MCP `env` only — never in agent prompts. See `.env.example` (`CHAINSTACK_API_KEY`, `ETH_RPC_URL`).

Set in Cursor **Environment Secrets** for Cloud Agents (same var names as local shell).

## Personal CFO (Plaid) — separate stack

Traditional finance read-only — **not** mixed with Web3 audit reports unless user asks.

| Item | Path |
|------|------|
| Agent | `.cursor/agents/personal-cfo-agent.md` |
| MCP | `plaid-cfo` in `.cursor/mcp.json` |
| Skill | `.cursor/skills/plaid-cfo-mcp/SKILL.md` |

## Desktop target pool (тест ЦЕЛИ)

| Step | Command |
|------|---------|
| Sync from Mac | `scp -r ~/Desktop/тест\ ЦЕЛИ user@host:/workspace/data/pentest/targets/` |
| Local sync | `bash scripts/sync-desktop-targets.sh ~/Desktop/тест\ ЦЕЛИ` |
| Ingest | `python3 scripts/ingest-target-pool.py --root $SAMSON_TARGETS_DIR` |
| Dry-run | `python3 scripts/ingest-target-pool.py --root $SAMSON_TARGETS_DIR --dry-run` |

Default VPS path: `data/pentest/targets/` (seed: `web3-field-targets.txt`).

## Exploitation extension (Playbook D — sandbox only)

Defensive PoC validation for local contracts. **Not** for live targets, RCE, or mainnet broadcast.

| Item | Path |
|------|------|
| Config | `config/exploitation-extension.json` |
| Gates | `scripts/sandbox/exploitation_gates.py` |
| Runner | `scripts/sandbox/exploitation-extension.py` |
| PoC tests | `scripts/sandbox/contracts/test/*.t.sol` |
| Artifacts | `artifacts/sandbox/exploitation-extension/` |

**Requirements:** `HEXSTRIKE_SANDBOX=1`, target under `scripts/sandbox/contracts/`.

```bash
# Gate unit tests
python3 scripts/sandbox/test_exploitation_gates.py

# Full extension (static + chain plan + optional forge PoC)
HEXSTRIKE_SANDBOX=1 python3 scripts/sandbox/exploitation-extension.py --skip-forge

# With Foundry PoC when forge is installed
HEXSTRIKE_SANDBOX=1 python3 scripts/sandbox/exploitation-extension.py
```

Phased suite phase 6 runs gate + extension checks automatically.
