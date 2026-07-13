#!/usr/bin/env bash
# fastmcp_live_cycle.sh — unified FastMCPCombat live pipeline (Mac operator)
#
# Vault → sync → verify → nonce → allowlist → rescue → build → sign → relay → watch → archive
#
# Usage:
#   # Dry-run (default — no broadcast):
#   bash scripts/fastmcp_live_cycle.sh --target 0xPAYROLL --add-recipient 0xPAYROLL
#
#   # Live broadcast (Mac with operator keys only):
#   export VAULT_PASSPHRASE='your-passphrase'
#   export BOT_PRIVATE_KEY='0xYOUR_REAL_KEY'
#   export HEXSTRIKE_TX_LIVE=1
#   bash scripts/fastmcp_live_cycle.sh --target 0xPAYROLL --live
#
#   # Or pass target via env:
#   TARGET_ADDRESS=0xPAYROLL bash scripts/fastmcp_live_cycle.sh --live
#
# Env: RPC_URL, CHAIN_ID, BOT_ADDRESS|PUBLIC_ADDRESS, BOT_PRIVATE_KEY, VAULT_PASSPHRASE,
#      GAS_HOLDER_ADDRESS, SAFE_ADDRESS, SAFE_PRIVATE_KEY, HEXSTRIKE_TX_LIVE
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HEXSTRIKE="${ROOT}/hexstrike"
[[ -x "$HEXSTRIKE" ]] || HEXSTRIKE="hexstrike"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
TX_LOGS="${ROOT}/tx_logs/${RUN_ID}"
LOG="${TX_LOGS}/fastmcp_live_cycle.log"

TARGET="${TARGET_ADDRESS:-${TARGET_WALLET:-}}"
VALUE="${TX_VALUE:-0.001bnb}"
TOKEN=""
AMOUNT=""
ADD_RECIPIENT=""
ALLOW_UNKNOWN=0
LIVE=0
SKIP_SYNC=0
SKIP_VAULT=0
SKIP_VERIFY=0
SKIP_RESCUE=0
SKIP_NONCE=0
FORCE_VAULT_STORE=0

usage() {
  cat <<'EOF'
Usage: bash scripts/fastmcp_live_cycle.sh [options] [0xTARGET]

Options:
  --target 0xADDR          Recipient (or set TARGET_ADDRESS)
  --value 0.001bnb         Native value (default)
  --token 0xCONTRACT       ERC20 token contract
  --amount 1.5             Token amount when --token set
  --add-recipient 0xADDR   Add to hot-wallet allowlist before cycle
  --allow-unknown          Bypass EntityGate allowlist check
  --dry-run                Force dry-run (no broadcast)
  --live                   Enable live broadcast (requires HEXSTRIKE_TX_LIVE=1 or sets it)
  --skip-sync              Skip hexstrike sync --mcp
  --skip-vault             Skip vault init/store-key bootstrap
  --skip-verify            Skip verify-combat-integration.sh
  --skip-rescue            Skip GAS_HOLDER rescue check
  --skip-nonce             Skip nonce recovery probe
  --force-vault-store      Re-import BOT_PRIVATE_KEY into vault even if bot exists
  -h, --help               Show this help

Phases: VAULT → SYNC → VERIFY → NONCE → ALLOWLIST → RESCUE → CYCLE → ARCHIVE
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target|--target=*)
      [[ "$1" == *=* ]] && TARGET="${1#*=}" || { TARGET="$2"; shift; }
      shift
      ;;
    --value|--value=*)
      [[ "$1" == *=* ]] && VALUE="${1#*=}" || { VALUE="$2"; shift; }
      shift
      ;;
    --token|--token=*)
      [[ "$1" == *=* ]] && TOKEN="${1#*=}" || { TOKEN="$2"; shift; }
      shift
      ;;
    --amount|--amount=*)
      [[ "$1" == *=* ]] && AMOUNT="${1#*=}" || { AMOUNT="$2"; shift; }
      shift
      ;;
    --add-recipient|--add-recipient=*)
      [[ "$1" == *=* ]] && ADD_RECIPIENT="${1#*=}" || { ADD_RECIPIENT="$2"; shift; }
      shift
      ;;
    --allow-unknown) ALLOW_UNKNOWN=1; shift ;;
    --dry-run) LIVE=0; shift ;;
    --live) LIVE=1; shift ;;
    --skip-sync) SKIP_SYNC=1; shift ;;
    --skip-vault) SKIP_VAULT=1; shift ;;
    --skip-verify) SKIP_VERIFY=1; shift ;;
    --skip-rescue) SKIP_RESCUE=1; shift ;;
    --skip-nonce) SKIP_NONCE=1; shift ;;
    --force-vault-store) FORCE_VAULT_STORE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    0x*) TARGET="$1"; shift ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 1 ;;
  esac
done

mkdir -p "$TX_LOGS"
exec > >(tee -a "$LOG") 2>&1

echo "════════════════════════════════════════════════════════"
echo " FastMCPCombat live cycle"
echo " RUN_ID: $RUN_ID"
echo " ROOT:   $ROOT"
echo " LOG:    $LOG"
echo "════════════════════════════════════════════════════════"

# === INIT ===
echo ""
echo "=== INIT ==="
if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ROOT}/.env"
  set +a
fi

PUBLIC_ADDRESS="${PUBLIC_ADDRESS:-${BOT_ADDRESS:-${FUNDER_ADDRESS:-}}}"
GAS_HOLDER="${GAS_HOLDER_ADDRESS:-${GAS_HOLDER:-}}"

[[ -n "${RPC_URL:-}" ]] || { echo "[INIT] FAIL: RPC_URL not set"; exit 1; }
[[ -n "$TARGET" ]] || { echo "[INIT] FAIL: --target or TARGET_ADDRESS required"; exit 1; }

if [[ "$LIVE" -eq 1 ]]; then
  export HEXSTRIKE_TX_LIVE=1
fi

MODE="dry-run"
[[ "${HEXSTRIKE_TX_LIVE:-}" == "1" && "$LIVE" -eq 1 ]] && MODE="live"
[[ "$LIVE" -eq 0 ]] && MODE="dry-run"

echo "[INIT] RPC:     ${RPC_URL}"
echo "[INIT] Chain:   ${CHAIN_ID:-unset}"
echo "[INIT] Wallet:  ${PUBLIC_ADDRESS:-unset}"
echo "[INIT] Target:  $TARGET"
echo "[INIT] Value:   $VALUE"
echo "[INIT] Mode:    $MODE"
echo "[INIT] Vault:   ${VAULT_PASSPHRASE:+set}${VAULT_PASSPHRASE:-unset}"

# === VAULT ===
if [[ "$SKIP_VAULT" -eq 0 ]]; then
  echo ""
  echo "=== VAULT ==="
  if [[ -z "${VAULT_PASSPHRASE:-}" ]]; then
    echo "[VAULT] VAULT_PASSPHRASE not set — skip init/store (FastMCPCombat may skip bootstrap)"
  else
    echo "[VAULT] Init keystore (RAM-disk preferred)..."
    "$HEXSTRIKE" vault init || true

    VAULT_STATUS=$("$HEXSTRIKE" vault status 2>/dev/null || echo '{}')
    echo "$VAULT_STATUS"

    if [[ -n "${BOT_PRIVATE_KEY:-}" ]]; then
      NEED_STORE=1
      if [[ "$FORCE_VAULT_STORE" -eq 0 ]]; then
        if echo "$VAULT_STATUS" | python3 -c "
import json, sys
d = json.load(sys.stdin)
keys = [k.lower() for k in d.get('keys', [])]
sys.exit(0 if 'bot' in keys else 1)
" 2>/dev/null; then
          NEED_STORE=0
          echo "[VAULT] Key 'bot' already in vault — skip store-key (use --force-vault-store to re-import)"
        fi
      fi
      if [[ "$NEED_STORE" -eq 1 ]]; then
        echo "[VAULT] Import BOT_PRIVATE_KEY → vault store-key bot..."
        "$HEXSTRIKE" vault store-key bot
      fi
    else
      echo "[VAULT] BOT_PRIVATE_KEY not in env — sign will use existing vault key or fail"
    fi

    echo "[VAULT] Signer readiness:"
    "$HEXSTRIKE" vault status
  fi
else
  echo ""
  echo "=== VAULT (skipped) ==="
fi

# === SYNC ===
if [[ "$SKIP_SYNC" -eq 0 ]]; then
  echo ""
  echo "=== SYNC ==="
  echo "[SYNC] MCP bindings + skills..."
  "$HEXSTRIKE" sync --mcp
else
  echo ""
  echo "=== SYNC (skipped) ==="
fi

# === VERIFY ===
if [[ "$SKIP_VERIFY" -eq 0 ]]; then
  echo ""
  echo "=== VERIFY ==="
  if bash "$ROOT/scripts/verify-combat-integration.sh" "$ROOT"; then
    echo "[VERIFY] Combat integration PASS"
  else
    echo "[VERIFY] WARN: verify-combat-integration.sh failed — continuing"
  fi
else
  echo ""
  echo "=== VERIFY (skipped) ==="
fi

# === NONCE ===
if [[ "$SKIP_NONCE" -eq 0 && -n "$PUBLIC_ADDRESS" ]]; then
  echo ""
  echo "=== NONCE ==="
  NONCE_JSON=$("$HEXSTRIKE" tx nonce --address="$PUBLIC_ADDRESS" 2>/dev/null || echo '{}')
  echo "$NONCE_JSON"
  echo "$NONCE_JSON" > "${TX_LOGS}/nonce.json"
  GAP=$(echo "$NONCE_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('gap', d.get('pending_gap', 0)))" 2>/dev/null || echo "0")
  if [[ "${GAP:-0}" != "0" && "${GAP:-0}" != "None" ]]; then
    echo "[NONCE] WARN: pending gap detected ($GAP) — review before live broadcast"
  else
    echo "[NONCE] OK — no pending gap"
  fi
else
  echo ""
  echo "=== NONCE (skipped) ==="
fi

# === ALLOWLIST ===
echo ""
echo "=== ALLOWLIST ==="
RECIPIENT="${ADD_RECIPIENT:-$TARGET}"
if [[ -n "$ADD_RECIPIENT" || "$ALLOW_UNKNOWN" -eq 0 ]]; then
  python3 - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, "${ROOT}/src")
from hexstrike.mcp.fastmcp import AllowlistManager

mgr = AllowlistManager()
data = mgr.load()
recipients = {a.lower() for a in data.get("authorized_recipients", [])}
target = "${TARGET}".lower()
add = "${ADD_RECIPIENT}".lower() if "${ADD_RECIPIENT}" else ""

if add and add not in recipients:
    mgr.add_recipient("${ADD_RECIPIENT}")
    print(f"[ALLOWLIST] Added recipient ${ADD_RECIPIENT}")
elif target not in recipients:
    print(json.dumps({
        "warning": "target not in allowlist",
        "target": "${TARGET}",
        "hint": f"run with --add-recipient ${TARGET} or --allow-unknown",
    }, indent=2))
else:
    print(f"[ALLOWLIST] Target ${TARGET} authorized")
PY
else
  echo "[ALLOWLIST] --allow-unknown set — gate bypass enabled"
fi

# === RESCUE ===
if [[ "$SKIP_RESCUE" -eq 0 ]]; then
  echo ""
  echo "=== RESCUE ==="
  RESCUE_JSON=$(python3 - <<PY
import json, sys
from pathlib import Path
sys.path.insert(0, "${ROOT}/src")
sys.path.insert(0, "${ROOT}/scripts")
from api_auth import load_dotenv
from hexstrike.mcp.fastmcp import FastMCPCombat

load_dotenv(Path("${ROOT}") / ".env")
combat = FastMCPCombat(auto_bootstrap_vault=False)
print(json.dumps(combat.package.rescue_check(), indent=2))
PY
)
  echo "$RESCUE_JSON"
  echo "$RESCUE_JSON" > "${TX_LOGS}/rescue_check.json"

  NEED=$(echo "$RESCUE_JSON" | python3 -c "import json,sys; d=json.load(sys.stdin); print(1 if d.get('need_rescue') else 0)" 2>/dev/null || echo "0")
  if [[ "$NEED" == "1" ]]; then
    echo "[RESCUE] GAS_HOLDER below minimum — attempting SAFE → GAS_HOLDER top-up"
    if [[ "$MODE" == "live" && -n "${SAFE_PRIVATE_KEY:-}" ]]; then
      HEXSTRIKE_TX_LIVE=1 "$HEXSTRIKE" tx rescue --target="${GAS_HOLDER}" --value="${RESCUE_VALUE:-0.01bnb}" --gas="${TX_GAS:-21000}"
    else
      "$HEXSTRIKE" tx rescue --target="${GAS_HOLDER:-0x0}" --value="${RESCUE_VALUE:-0.01bnb}" --gas="${TX_GAS:-21000}" --dry-run 2>/dev/null || \
        echo "[RESCUE] Dry-run only (no SAFE_PRIVATE_KEY or not live mode)"
    fi
  else
    echo "[RESCUE] Balance sufficient — no top-up needed"
  fi
else
  echo ""
  echo "=== RESCUE (skipped) ==="
fi

# === CYCLE (FastMCPCombat) ===
echo ""
echo "=== CYCLE ==="
CYCLE_ARGS=(--target "$TARGET" --value "$VALUE")
[[ -n "$TOKEN" ]] && CYCLE_ARGS+=(--token "$TOKEN")
[[ -n "$AMOUNT" ]] && CYCLE_ARGS+=(--amount "$AMOUNT")
[[ -n "$ADD_RECIPIENT" ]] && CYCLE_ARGS+=(--add-recipient "$ADD_RECIPIENT")
[[ "$ALLOW_UNKNOWN" -eq 1 ]] && CYCLE_ARGS+=(--allow-unknown)

if [[ "$MODE" == "dry-run" ]]; then
  CYCLE_ARGS+=(--dry-run)
  echo "[CYCLE] Dry-run: build → gate → sign → archive (broadcast blocked)"
else
  if [[ -z "${BOT_PRIVATE_KEY:-}" && -z "${VAULT_PASSPHRASE:-}" ]]; then
    echo "[CYCLE] FAIL: live mode requires BOT_PRIVATE_KEY or vault with VAULT_PASSPHRASE"
    exit 1
  fi
  echo "[CYCLE] LIVE: build → gate → sign → relay → watch → archive"
fi

CYCLE_JSON=$(python3 "$ROOT/scripts/run_fastmcp_combat_live.py" "${CYCLE_ARGS[@]}")
echo "$CYCLE_JSON"
echo "$CYCLE_JSON" > "${TX_LOGS}/fastmcp_cycle.json"

SUCCESS=$(echo "$CYCLE_JSON" | python3 -c "import json,sys; print(1 if json.load(sys.stdin).get('success') else 0)" 2>/dev/null || echo "0")
TX_HASH=$(echo "$CYCLE_JSON" | python3 -c "
import json, sys
d = json.load(sys.stdin)
h = d.get('broadcast', {}).get('hash') or d.get('sign', {}).get('hash') or d.get('watch', {}).get('hash') or ''
print(h)
" 2>/dev/null || true)

# === ARCHIVE ===
echo ""
echo "=== ARCHIVE ==="
python3 - <<PY
import json
from pathlib import Path

summary = {
    "run_id": "${RUN_ID}",
    "mode": "${MODE}",
    "target": "${TARGET}",
    "value": "${VALUE}",
    "success": bool(int("${SUCCESS}")),
    "tx_hash": "${TX_HASH}",
    "tx_logs_dir": "${TX_LOGS}",
    "log": "${LOG}",
}
Path("${TX_LOGS}/fastmcp_live_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
latest = Path("${ROOT}/tx_logs/latest")
latest.mkdir(parents=True, exist_ok=True)
(latest / "fastmcp_live_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
PY

# Copy any FastMCPCombat archive from same run_id if present
FASTMCP_DIR="${ROOT}/tx_logs/${RUN_ID}"
if [[ -d "$FASTMCP_DIR" ]]; then
  cp -a "$FASTMCP_DIR"/* "$TX_LOGS/" 2>/dev/null || true
fi

echo ""
if [[ "$SUCCESS" == "1" ]]; then
  echo "[DONE] FastMCPCombat cycle OK — artifacts → ${TX_LOGS}/"
  if [[ -n "$TX_HASH" && "$TX_HASH" != "None" ]]; then
    echo "[DONE] tx hash: $TX_HASH"
  fi
  exit 0
fi

echo "[DONE] FastMCPCombat cycle FAILED — see ${LOG}"
exit 1
