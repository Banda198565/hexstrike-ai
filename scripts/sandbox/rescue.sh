#!/usr/bin/env bash
# SAFE → GAS_HOLDER gas rescue (combat scenario)
#
# Mac/VPS:
#   source .env   # SAFE_PRIVATE_KEY, GAS_HOLDER_ADDRESS, RPC_URL
#   bash scripts/sandbox/rescue.sh           # check + rescue if needed
#   bash scripts/sandbox/rescue.sh --dry-run # force dry-run log
#   bash scripts/sandbox/rescue.sh --force   # rescue even if balance OK
#
# Logs: artifacts/sandbox/rescue-operations.jsonl
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
ENV_FILE="${SANDBOX_ENV:-$ROOT/.env}"

[[ -f "$ENV_FILE" ]] && set -a && source "$ENV_FILE" && set +a

export SANDBOX_ENV="$ENV_FILE"
DRY_FLAG=""
FORCE_FLAG=""
for arg in "$@"; do
  case "$arg" in
    --dry-run) export DRY_RUN=true ;;
    --force) FORCE_FLAG="--force" ;;
  esac
done

if [[ -f "$ROOT/hexstrike_env/bin/activate" ]]; then
  # shellcheck source=/dev/null
  source "$ROOT/hexstrike_env/bin/activate"
fi

echo "[rescue] GAS_HOLDER=${GAS_HOLDER_ADDRESS:-${BOT_ADDRESS:-unset}}"
echo "[rescue] SAFE=${SAFE_ADDRESS:-${FUNDER_ADDRESS:-unset}}"
echo "[rescue] RPC=${RPC_URL:-unset} DRY_RUN=${DRY_RUN:-true}"

python3 "$ROOT/scripts/sandbox/rescue_gas.py" $FORCE_FLAG
