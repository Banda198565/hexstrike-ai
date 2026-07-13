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

Verify readiness before live (Mac):

```bash
bash scripts/fastmcp_verify.sh --target 0xPAYROLL --run-dry-run
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

## Host roles

| Host | OS | Role |
|------|-----|------|
| **VPS** | AlmaLinux / RHEL | dry-run, verify, monitor, discovery, pipeline — **no live broadcast** |
| **Mac** | macOS | vault + KeyVaultSigner + **`HEXSTRIKE_TX_LIVE=1` broadcast** |

### AlmaLinux VPS bootstrap

```bash
# On VPS (as root)
cd /opt/hexstrike-ai
bash scripts/vps-almalinux-fastmcp-bootstrap.sh

# Or skip dnf/venv if already installed:
TARGET_ADDRESS=0xPAYROLL SKIP_DNF=1 SKIP_VENV=1 \
  bash scripts/vps-almalinux-fastmcp-bootstrap.sh
```

The Alma script **refuses** `HEXSTRIKE_TX_LIVE=1` and uses a lab vault key only.

### VPS recurring ops + systemd

```bash
# One-shot ops (verify + pipeline dry-run)
bash scripts/vps-fastmcp-ops.sh          # standard
bash scripts/vps-fastmcp-ops.sh --quick  # vault + nonce + verify
bash scripts/vps-fastmcp-ops.sh --full   # + combat verify + readiness

# Install timers (pipeline 15m + FastMCP ops 30m)
sudo bash scripts/install-pipeline-systemd.sh /opt/hexstrike-ai
```

### Full VPS bootstrap (Alma or Ubuntu)

```bash
cd /opt/hexstrike-ai && git pull
sudo bash scripts/vps-prod-bootstrap.sh
```

### CLI shortcuts

```bash
# VPS
./hexstrike ops --quick
./hexstrike fastmcp status
./hexstrike fastmcp verify --target 0xPAYROLL --run-dry-run
./hexstrike fastmcp pull-ops --standard
./hexstrike agent run pipeline --pipeline fastmcp-vps-ops

# Mac
./hexstrike fastmcp status
./hexstrike fastmcp gate --target 0xPAYROLL           # dry check
./hexstrike fastmcp live --target 0xPAYROLL --dry-run
CONFIRM=YES HEXSTRIKE_TX_LIVE=1 ./hexstrike fastmcp live --target 0xPAYROLL --live
```

## Security gate (fail-closed)

`scripts/security_gate.sh` runs before every live broadcast in `mac-fastmcp-live.sh`. It refuses live when:

- `HEXSTRIKE_HOST_ROLE=vps` or kernel is not Darwin
- Vault missing `bot` key
- **Signer address ≠ `KNOWN_BOT_ADDRESS`** (won't sign for non-owner)
- Target not in `authorized_recipients`
- Nonce `pending_gap` > 0
- Open IR incidents in `artifacts/incidents/*.open`
- Missing `HEXSTRIKE_TX_LIVE=1` or `CONFIRM=YES`

Override `KNOWN_BOT_ADDRESS` via env when the operator wallet changes.

### Mac → VPS sync FastMCP bundle

```bash
VPS_HOST=x.x.x.x bash scripts/mac-vps-sync-fastmcp.sh
```

### Mac live (operator)

```bash
export VAULT_PASSPHRASE='...'
export BOT_PRIVATE_KEY='0x...'
bash scripts/fastmcp_verify.sh --target 0xPAYROLL --run-dry-run
export HEXSTRIKE_TX_LIVE=1
bash scripts/fastmcp_live_cycle.sh --target 0xPAYROLL --add-recipient 0xPAYROLL --live
```

## Security

- **EntityGate** blocks unknown recipients before sign (see `config/hot-wallet-allowlist.json`)
- Override: `HEXSTRIKE_TX_ALLOW_UNKNOWN=1` (operator only)
- Live broadcast: `HEXSTRIKE_TX_LIVE=1` — **Mac only**, never Alma/VPS
- VPS may hold lab vault keys for dry-run; never persist real operator keys on VPS
