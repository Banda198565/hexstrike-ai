#!/usr/bin/env bash
# run-operator-rescue-mainnet.sh — P5 operator rescue for 0x85dB… (DRY_RUN default)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

export DRY_RUN="${DRY_RUN:-true}"
export BOT_ADDRESS="${BOT_ADDRESS:-0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846}"
export TARGET_WATCH_ADDRESS="${TARGET_WATCH_ADDRESS:-0x96B23C4680E1a37cE17730e6118D0C9223e72A66}"
export FUNDER_ADDRESS="${FUNDER_ADDRESS:-0x060447dC91dfb22A5233731aF67E9E8dafdF24d1}"
export ALLOWED_FUNDERS="${ALLOWED_FUNDERS:-$FUNDER_ADDRESS}"
export PUISSANT_BUILDER_URL="${PUISSANT_BUILDER_URL:-https://puissant-builder.48.club/}"
export RPC_URL="${RPC_URL:-https://bsc-dataseed.binance.org}"

echo "=== Operator mainnet rescue (Puissant dry-run) ==="
echo "BOT=$BOT_ADDRESS DRY_RUN=$DRY_RUN"

python3 "$ROOT/scripts/sandbox/operator_rescue_puissant.py"

if [[ -f "$ROOT/.env" ]]; then
  echo "=== deploy-mainnet dry-run (if .env present) ==="
  bash "$ROOT/scripts/sandbox/deploy-mainnet.sh" dry-run || true
else
  echo "[--] skip deploy-mainnet dry-run — no .env (expected in cloud CI)"
fi

echo "[OK] → artifacts/sandbox/operator-rescue-puissant.json"
