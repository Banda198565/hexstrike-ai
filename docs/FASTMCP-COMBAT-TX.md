# Architecture reference — combat FastMCP package

Modular layout under `src/hexstrike/mcp/fastmcp/`:

| Module | Class | Methods |
|--------|-------|---------|
| `tx_builder.py` | **TxBuilder** | `build_native()`, `build_erc20()`, `estimate_gas()` |
| `tx_signer.py` | **TxSigner** | `sign_raw()`, `verify_signature()`, `load_key()` |
| `receipt_watcher.py` | **ReceiptWatcher** | `poll_status()`, `watch()`, `log_receipt()`, `retry_failed()` |
| `relay_manager.py` | **RelayManager** | `send_via_relay()`, `check_latency()`, `fallback_rpc()` |
| `vault_handler.py` | **VaultHandler** | `init_vault()`, `store_key()`, `retrieve_key()`, `list_keys()` |
| `allowlist_manager.py` | **AllowlistManager** | `load()`, `add_recipient()`, `add_contract()`, `is_authorized()` |
| `entity_gate.py` | **EntityGate** | `evaluate()`, `assert_allowed()` |
| `tx_package.py` | **TxPackage** / **FastMCPCombat** | `execute_cycle()`, `execute_live_tx()`, `rescue_check()`, `archive_logs()` |

## Usage (Python)

```python
from hexstrike.mcp.fastmcp import FastMCPCombat

mcp = FastMCPCombat()
result = mcp.execute_live_tx("0xTARGET", "0.001bnb")  # dry-run if HEXSTRIKE_TX_LIVE unset
```

## MCP tools (via hexstrike_mcp.py)

Registered by `register_mcp_tx_tools()`:

- `tx_build`, `tx_sign`, `tx_broadcast`, `tx_watch`
- `tx_execute_cycle`, `tx_rescue_check`, `tx_nonce`
- `entity_gate_evaluate`, `allowlist_add_recipient`, `allowlist_add_contract`, `allowlist_list`
- `vault_status`, `vault_init`, `vault_signer_ready`
- `relay_latency_probe`

## Security

- **EntityGate** blocks unknown recipients before sign (see `config/hot-wallet-allowlist.json`)
- Override: `HEXSTRIKE_TX_ALLOW_UNKNOWN=1` (operator only)
- Live broadcast: `HEXSTRIKE_TX_LIVE=1`
