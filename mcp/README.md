# HexStrike Blockchain MCP Layer

Read-only MCP servers for on-chain forensics. No signing, no `personal_*`, no transaction broadcast.

## Servers

| Server | Tools | Purpose |
|--------|-------|---------|
| `evm-rpc-mcp` | `rpc_chain_id`, `get_balance`, `get_erc20_balance`, `get_contract_code`, `eth_call_read` | Raw RPC reads |
| `block-explorer-mcp` | `get_token_transfers`, `verify_erc20_token`, `get_contract_abi_stub`, `address_graph_summary` | Transfer graph + token verification |
| `defi-dex-mcp` | `check_dex_liquidity`, `check_flashloan_exposure` | Pancake liquidity + bytecode heuristics |
| `mev-offensive-mcp` | `scan_live_mempool_tool`, `scan_fork_mempool_tool`, `get_fork_reserves_tool`, `builder_sim_dry_run`, `run_offensive_pipeline_tool` | MEV sandbox: mempool → PnL → builder dry-run |

## Quick start

```bash
# Smoke test (local)
./scripts/mcp-smoke-test.sh

# Cursor: merge mcp-config.json into Settings → MCP
# Env: EVM_RPC_URL=http://51.222.42.220:8545  EVM_CHAIN_ID=56
```

## VPS deploy

```bash
# On HexStrike host (78.27.235.70)
HEX_ROOT=/opt/hexstrike-ai MCP_SRC=/root/blockchain-mcp ./scripts/deploy-blockchain-mcp.sh
```

Mac tunnel for HexStrike pentest MCP:

```bash
ssh -L 8888:127.0.0.1:8888 root@78.27.235.70
```

## Agent bindings

See `agent-bindings.json` for Agent-Infra-01 (deploy), Agent-Graph-01 (hot wallet graph + USDT verify), and Agent-MEV-Offensive (live mempool + builder sim).

## Security

- RPC endpoint is read-only (no keys, no `eth_sendTransaction`).
- Do not attach operator `proof-key.txt` or any signing bot to these servers.
- Verified ABI still requires BscScan; `get_contract_abi_stub` returns bytecode facts only.
- `mev-offensive-mcp` requires `MEV_SANDBOX_ONLY=1`; `MEV_MAINNET_SUBMIT=1` is always blocked; `would_submit` is always false.
