---
name: plaid-cfo-mcp
description: Read-only Personal CFO via Plaid MCP — accounts, transactions, investment holdings, liabilities. Use for traditional finance analytics separate from Web3 on-chain audit.
---

# Plaid CFO MCP

MCP server: `scripts/plaid_cfo_mcp_server.py`  
Config: `config/mcp/plaid-cfo-mcp.json`  
Agent: `.cursor/agents/personal-cfo-agent.md`

**Separate from Web3 orchestrator** — do not mix Plaid FIAT data with on-chain MCP findings in one report without explicit user request.

## Credentials (MCP env only)

| Variable | Purpose |
|----------|---------|
| `PLAID_CLIENT_ID` | Plaid dashboard |
| `PLAID_SECRET` | Plaid dashboard |
| `PLAID_ACCESS_TOKEN` | Item access token (after Link / connector) |
| `PLAID_ENV` | `sandbox` or `production` |

Perplexity "Personal CFO" connector uses the same Plaid backend — obtain tokens via Plaid Link or dashboard sandbox.

## Tool order

```
1. detect_plaid_config
2. plaid_accounts_list
3. plaid_transactions_list (days=30)
4. plaid_investments_holdings
5. plaid_liabilities_list
6. plaid_cfo_summary (one-shot)
```

## Non-emulation

- `skipped: true` when credentials missing — do not invent balances or transactions.
- Read-only — no payment initiation, no account modification.

## Artifacts

`artifacts/plaid-cfo/`
