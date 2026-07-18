# Cursor MCP Audit Stack (4 servers)

Project-level config: [`.cursor/mcp.json`](../../.cursor/mcp.json)

Cursor loads this automatically for the workspace. Secrets stay in shell / `.env` — not in JSON.

## Servers

| Server | Role | Prerequisites |
|--------|------|---------------|
| **solidity-audit** | Primary static analysis (HexStrike native) | `python3`, Slither optional |
| **foundry** | `forge` / `cast` / `anvil` local verification | Node.js, Foundry |
| **chainstack** | RPC + indexer + web3 context | `uvx`, `CHAINSTACK_API_KEY` |
| **faro-fino** | Second-opinion deep scan | Docker, `faro-fino/mcp-server:latest` |

## Secrets (export or `.env`)

```bash
export CHAINSTACK_API_KEY="your_chainstack_key"
export ETH_RPC_URL="https://ethereum-mainnet.core.chainstack.com/your-endpoint"
# or Infura/Alchemy URL for faro-fino RPC context
```

Add to Cursor **Environment Secrets** for Cloud Agents (same var names).

## Agent tool order

```
1. solidity-audit   → parse_contract, slither_run_detectors, check_swc_patterns
2. foundry          → forge build, forge test (PoC / regression)
3. chainstack       → RPC metadata, logs, address context
4. faro-fino        → cross-check / deep scan (second opinion)
5. merge            → dedupe by (category, function, line); note source per server
```

See [`.cursor/agents/config.md`](../../.cursor/agents/config.md) § MCP stack (4-server).

## Alternative: external solidity-audit package

If you prefer [mariano-aguero/solidity-audit-mcp](https://github.com/mariano-aguero/solidity-audit-mcp) instead of HexStrike native:

```json
"solidity-audit": {
  "command": "uv",
  "args": ["run", "python", "-m", "solidity_audit_mcp"]
}
```

Use one static server — not both (duplicate Slither findings).

## Optional: unified HexStrike Web3 Audit (36 tools)

Replaces solidity-audit + partial chainstack RPC with one server:

`config/mcp/web3-audit-mcp.json` → `hexstrike-web3-audit`

## SSE / HTTP MCP

If a server exposes HTTP `/mcp` (e.g. FastAPI-MCP), add in Cursor Settings → MCP → URL instead of `command`/`args`. Keep stdio servers in `.cursor/mcp.json`.

## Verify

```bash
# HexStrike native unit tests
python3 scripts/test_solidity_audit_runner.py

# Foundry installed?
forge --version

# Chainstack key set?
test -n "$CHAINSTACK_API_KEY" && echo OK

# Faro Fino image
docker pull faro-fino/mcp-server:latest
```
