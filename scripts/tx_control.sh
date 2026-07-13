#!/usr/bin/env bash
# tx_control.sh — боевой автономный цикл транзакции HexStrike CLI
#
# Usage:
#   bash scripts/tx_control.sh --dry-run-only
#   bash scripts/tx_control.sh --live
#   TARGET_ADDRESS=0x... bash scripts/tx_control.sh --live
#
# Env (.env): RPC_URL, CHAIN_ID, BOT_ADDRESS|PUBLIC_ADDRESS, BOT_PRIVATE_KEY,
#             GAS_HOLDER_ADDRESS, SAFE_ADDRESS, SAFE_PRIVATE_KEY
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

HEXSTRIKE="${ROOT}/hexstrike"
[[ -x "$HEXSTRIKE" ]] || HEXSTRIKE="hexstrike"

RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
TX_LOGS="${ROOT}/tx_logs/${RUN_ID}"
WORKDIR="${TX_WORKDIR:-${ROOT}/artifacts/tx/run-${RUN_ID}}"

TARGET="${TARGET_ADDRESS:-}"
VALUE="${TX_VALUE:-0.001bnb}"
GAS="${TX_GAS:-21000}"
RESCUE_VALUE="${RESCUE_VALUE:-0.01bnb}"
RESCUE_MIN_BNB="${RESCUE_MIN_BNB:-0.005}"
DRY_ONLY=1
SKIP_SYNC=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --value|--value=*) [[ "$1" == *=* ]] && VALUE="${1#*=}" || { VALUE="$2"; shift; }; shift ;;
    --gas|--gas=*) [[ "$1" == *=* ]] && GAS="${1#*=}" || { GAS="$2"; shift; }; shift ;;
    --dry-run-only) DRY_ONLY=1; shift ;;
    --live) DRY_ONLY=0; shift ;;
    --skip-sync) SKIP_SYNC=1; shift ;;
    --workdir) WORKDIR="$2"; shift 2 ;;
    0x*) TARGET="$1"; shift ;;
    *) echo "Unknown arg: $1" >&2; exit 1 ;;
  esac
done

mkdir -p "$WORKDIR" "$TX_LOGS"
RAW="${WORKDIR}/raw_tx.json"
SIGNED="${WORKDIR}/signed_tx.json"
LOG="${WORKDIR}/tx_control.log"
SUMMARY="${WORKDIR}/summary.json"

exec > >(tee -a "$LOG") 2>&1

archive_logs() {
  cp -a "$LOG" "$TX_LOGS/" 2>/dev/null || true
  cp -a "$RAW" "$SIGNED" "$SUMMARY" "$TX_LOGS/" 2>/dev/null || true
  cp -a "${ROOT}/artifacts/tx/"*.json "$TX_LOGS/" 2>/dev/null || true
  echo "[ARCHIVE] logs → ${TX_LOGS}/"
}

trap archive_logs EXIT

# === INIT ===
echo "=== INIT ==="
if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "${ROOT}/.env"
  set +a
fi

PUBLIC_ADDRESS="${PUBLIC_ADDRESS:-${BOT_ADDRESS:-${FUNDER_ADDRESS:-}}}"
GAS_HOLDER="${GAS_HOLDER_ADDRESS:-${GAS_HOLDER:-}}"
TARGET="${TARGET:-${TARGET_ADDRESS:-}}"

echo "[INIT] RPC: ${RPC_URL:-unset} | Chain: ${CHAIN_ID:-unset}"
echo "[INIT] Wallet: ${PUBLIC_ADDRESS:-unset}"
echo "[INIT] Target: ${TARGET:-unset} | Gas holder: ${GAS_HOLDER:-unset}"
echo "[INIT] Mode: $( [[ "$DRY_ONLY" -eq 1 ]] && echo dry-run-only || echo LIVE )"
echo "[INIT] Workdir: $WORKDIR"

[[ -n "${RPC_URL:-}" ]] || { echo "[INIT] FAIL: RPC_URL not set"; exit 1; }
[[ -n "$PUBLIC_ADDRESS" ]] || { echo "[INIT] FAIL: PUBLIC_ADDRESS / BOT_ADDRESS not set"; exit 1; }
[[ -n "$TARGET" ]] || { echo "[INIT] FAIL: TARGET_ADDRESS not set (arg or env)"; exit 1; }

# === SYNC ===
if [[ "$SKIP_SYNC" -eq 0 ]]; then
  echo "=== SYNC ==="
  echo "[SYNC] MCP bindings + integration verify"
  "$HEXSTRIKE" sync --mcp
fi

# === SIGN ===
echo "=== SIGN ==="
echo "[SIGN] Формирование raw-payload (dry-run preflight)..."
SEND_JSON=$("$HEXSTRIKE" tx send "$TARGET" --value "$VALUE" --gas "$GAS" --dry-run --out "$RAW")
echo "$SEND_JSON"

if [[ "$DRY_ONLY" -eq 1 ]]; then
  echo "[SIGN] Dry-run only — broadcast skipped"
  python3 - <<PY
import json
from pathlib import Path
Path("${SUMMARY}").write_text(json.dumps({
  "run_id": "${RUN_ID}",
  "mode": "dry-run-only",
  "target": "${TARGET}",
  "raw_tx": "${RAW}",
  "result": "ok",
}, indent=2) + "\n")
PY
  exit 0
fi

if [[ -z "${BOT_PRIVATE_KEY:-}" && -z "${SAFE_PRIVATE_KEY:-}" ]]; then
  echo "[SIGN] FAIL: BOT_PRIVATE_KEY not set — cannot sign on this host"
  exit 1
fi

echo "[SIGN] Подпись транзакции..."
SIGN_JSON=$("$HEXSTRIKE" tx sign "$RAW" --debug --out "$SIGNED")
echo "$SIGN_JSON"

# === BROADCAST ===
echo "=== BROADCAST ==="
echo "[BROADCAST] Отправка подписанной транзакции..."
BC_JSON=$("$HEXSTRIKE" tx broadcast "$SIGNED" --force)
echo "$BC_JSON"

HASH=$(echo "$BC_JSON" | python3 -c "import json,sys; print(json.load(sys.stdin).get('hash','') or '')" 2>/dev/null || true)
if [[ -z "$HASH" || "$HASH" == "None" ]]; then
  HASH=$(python3 -c "import json; print(json.load(open('${SIGNED}')).get('hash',''))" 2>/dev/null || true)
fi

# === STATUS ===
echo "=== STATUS ==="
STATUS_JSON='{}'
if [[ -n "$HASH" && "$HASH" != "None" ]]; then
  echo "[STATUS] Проверка статуса ${HASH}..."
  sleep 3
  STATUS_JSON=$("$HEXSTRIKE" tx status "$HASH" --json)
  echo "$STATUS_JSON"
else
  echo "[STATUS] WARN: hash not found — skip status poll"
fi

# === RESCUE ===
echo "=== RESCUE ==="
if [[ -n "$GAS_HOLDER" ]]; then
  BALANCE_WEI=""
  if command -v cast >/dev/null 2>&1; then
    BALANCE_WEI=$(cast balance "$GAS_HOLDER" --rpc-url "$RPC_URL" 2>/dev/null || echo "0")
  else
    BALANCE_WEI=$(python3 - <<PY
import os, sys
sys.path.insert(0, "${ROOT}/scripts")
from crypto_rpc_orchestrator import rpc_call
wei = int(rpc_call(os.environ["RPC_URL"], "eth_getBalance", ["${GAS_HOLDER}", "latest"])["result"], 16)
print(wei)
PY
)
  fi
  BALANCE_BNB=$(python3 -c "print(int('${BALANCE_WEI}') / 1e18)")
  echo "[RESCUE] GAS_HOLDER balance: ${BALANCE_BNB} BNB (wei=${BALANCE_WEI})"
  NEED_RESCUE=$(python3 -c "print(1 if float('${BALANCE_BNB}') < float('${RESCUE_MIN_BNB}') else 0)")
  if [[ "$NEED_RESCUE" -eq 1 ]]; then
    echo "[RESCUE] Недостаточно газа (< ${RESCUE_MIN_BNB} BNB), SAFE подкидывает..."
    if [[ -z "${SAFE_PRIVATE_KEY:-}" ]]; then
      echo "[RESCUE] WARN: SAFE_PRIVATE_KEY not set — rescue dry-run only"
      "$HEXSTRIKE" tx rescue --target="$GAS_HOLDER" --value="$RESCUE_VALUE" --gas "$GAS" --dry-run
    else
      HEXSTRIKE_TX_LIVE=1 "$HEXSTRIKE" tx rescue --target="$GAS_HOLDER" --value="$RESCUE_VALUE" --gas "$GAS"
    fi
  else
    echo "[RESCUE] Баланс достаточный, rescue не требуется."
  fi
else
  echo "[RESCUE] GAS_HOLDER_ADDRESS not set — skip"
fi

python3 - <<PY
import json
from pathlib import Path
summary = {
  "run_id": "${RUN_ID}",
  "mode": "live",
  "target": "${TARGET}",
  "hash": "${HASH}",
  "raw_tx": "${RAW}",
  "signed_tx": "${SIGNED}",
  "tx_logs": "${TX_LOGS}",
  "result": "ok",
}
Path("${SUMMARY}").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
PY

echo "[DONE] summary → ${SUMMARY}"
