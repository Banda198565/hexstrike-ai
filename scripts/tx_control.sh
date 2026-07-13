#!/usr/bin/env bash
# tx_control.sh — полный цикл транзакции под контролем HexStrike CLI
#
# Usage:
#   bash scripts/tx_control.sh 0xTARGET --value 0.001bnb --dry-run-only
#   bash scripts/tx_control.sh 0xTARGET --value 0.001bnb --live   # sign+broadcast (Mac with key)
#   bash scripts/tx_control.sh --rescue-only --gas-holder 0x... --value 0.01bnb
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HEXSTRIKE="${ROOT}/hexstrike"
[[ -x "$HEXSTRIKE" ]] || HEXSTRIKE="hexstrike"

TARGET=""
VALUE="0.001bnb"
GAS="21000"
DRY_ONLY=1
RESCUE_ONLY=0
GAS_HOLDER="${GAS_HOLDER_ADDRESS:-}"
WORKDIR="${TX_WORKDIR:-$ROOT/artifacts/tx/run-$(date -u +%Y%m%dT%H%M%SZ)}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --value) VALUE="$2"; shift 2 ;;
    --gas) GAS="$2"; shift 2 ;;
    --gas=*) GAS="${1#*=}"; shift ;;
    --gas-holder) GAS_HOLDER="$2"; shift 2 ;;
    --workdir) WORKDIR="$2"; shift 2 ;;
    --dry-run-only) DRY_ONLY=1; shift ;;
    --live) DRY_ONLY=0; shift ;;
    --rescue-only) RESCUE_ONLY=1; shift ;;
    0x*) TARGET="$1"; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$WORKDIR"
RAW="$WORKDIR/raw_tx.json"
SIGNED="$WORKDIR/signed_tx.json"
LOG="$WORKDIR/tx_control.log"

log() { echo "[tx_control] $*" | tee -a "$LOG"; }

log "=== HexStrike tx control ==="
log "workdir=$WORKDIR"

log "Step 1/6: sync MCP"
"$HEXSTRIKE" sync --mcp | tee -a "$LOG"

if [[ "$RESCUE_ONLY" -eq 1 ]]; then
  log "Step 6: rescue gas"
  [[ -n "$GAS_HOLDER" ]] || { echo "Set GAS_HOLDER_ADDRESS or --gas-holder" >&2; exit 1; }
  "$HEXSTRIKE" tx rescue --target "$GAS_HOLDER" --value "$VALUE" --gas "$GAS" \
    $( [[ "$DRY_ONLY" -eq 1 ]] && echo --dry-run ) | tee -a "$LOG"
  exit 0
fi

[[ -n "$TARGET" ]] || { echo "Usage: tx_control.sh 0xTARGET [--live]" >&2; exit 1; }

log "Step 2/6: send (dry-run build)"
SEND_ARGS=(tx send "$TARGET" --value "$VALUE" --gas "$GAS" --out "$RAW" --dry-run)
"$HEXSTRIKE" "${SEND_ARGS[@]}" | tee -a "$LOG"

if [[ "$DRY_ONLY" -eq 1 ]]; then
  log "Dry-run only — raw tx: $RAW"
  log "Next: hexstrike tx sign $RAW --debug"
  exit 0
fi

if [[ -z "${BOT_PRIVATE_KEY:-}" && -z "${SAFE_PRIVATE_KEY:-}" ]]; then
  log "ERROR: no BOT_PRIVATE_KEY / SAFE_PRIVATE_KEY — cannot sign on this host"
  exit 1
fi

log "Step 3/6: sign"
"$HEXSTRIKE" tx sign "$RAW" --debug --out "$SIGNED" | tee -a "$LOG"

log "Step 4/6: broadcast"
BC_OUT=$("$HEXSTRIKE" tx broadcast "$SIGNED" --force)
echo "$BC_OUT" | tee -a "$LOG"

HASH=$(echo "$BC_OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('hash',''))" 2>/dev/null || true)
if [[ -z "$HASH" ]]; then
  HASH=$(python3 -c "import json; print(json.load(open('$SIGNED')).get('hash',''))" 2>/dev/null || true)
fi

if [[ -n "$GAS_HOLDER" ]]; then
  log "Step 6: rescue gas (optional top-up)"
  "$HEXSTRIKE" tx rescue --target "$GAS_HOLDER" --value 0.01bnb --dry-run | tee -a "$LOG" || true
fi

if [[ -n "$HASH" && "$HASH" != None ]]; then
  log "Step 5/6: status $HASH"
  sleep 3
  "$HEXSTRIKE" tx status "$HASH" --json | tee -a "$LOG"
else
  log "WARN: no tx hash — skip status"
fi

log "DONE — artifacts in $WORKDIR"
