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

# Auto bootstrap: init vault + import BOT_PRIVATE_KEY on first run
combat = FastMCPCombat(auto_bootstrap_vault=True)

result = combat.execute_live_tx(
    target="0xPAYROLL",
    value="0.001bnb",
    token=None,
    allow_unknown=False,
)
# build → gate → sign → relay → watch → archive_logs
```

Or run the unified shell pipeline (recommended on Mac):

```bash
export VAULT_PASSPHRASE='...'
export BOT_PRIVATE_KEY='0x...'

# Dry-run (default — broadcast blocked)
bash scripts/fastmcp_live_cycle.sh --target 0xPAYROLL --add-recipient 0xPAYROLL

# Live broadcast
export HEXSTRIKE_TX_LIVE=1
bash scripts/fastmcp_live_cycle.sh --target 0xPAYROLL --live
```

Or the Python example directly:

```bash
export VAULT_PASSPHRASE='...'
export BOT_PRIVATE_KEY='0x...'
python3 scripts/run_fastmcp_combat_live.py --target 0xPAYROLL --add-recipient 0xPAYROLL
export HEXSTRIKE_TX_LIVE=1
python3 scripts/run_fastmcp_combat_live.py --target 0xPAYROLL
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
