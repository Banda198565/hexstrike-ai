#!/usr/bin/env bash
# setup-bsc-fork.sh — BSC mainnet fork for offensive MEV sim (no live submission)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PORT="${BSC_FORK_PORT:-8545}"
HOST="${BSC_FORK_HOST:-127.0.0.1}"
UPSTREAM="${BSC_FORK_URL:-https://bsc-dataseed.binance.org}"
PID_FILE="${TMPDIR:-/tmp}/hexstrike-bsc-fork.pid"
LOG_FILE="${TMPDIR:-/tmp}/hexstrike-bsc-fork.log"

if ! command -v anvil >/dev/null; then
  echo "[FAIL] anvil not found"
  exit 1
fi

# Stop pure Anvil if running on same port
"$ROOT/scripts/sandbox/stop-anvil.sh" 2>/dev/null || true
"$ROOT/scripts/sandbox/stop-bsc-fork.sh" 2>/dev/null || true
if [[ -f "$PID_FILE" ]]; then
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
fi
pkill -f "anvil.*--port ${PORT}" 2>/dev/null || true
sleep 2

echo "[start] BSC fork on http://${HOST}:${PORT} upstream=$UPSTREAM"
FORK_ARGS=(--host "$HOST" --port "$PORT" --chain-id 56 --fork-url "$UPSTREAM")
if [[ -n "${BSC_FORK_BLOCK:-}" ]]; then
  FORK_ARGS+=(--fork-block-number "$BSC_FORK_BLOCK")
fi
nohup anvil "${FORK_ARGS[@]}" >"$LOG_FILE" 2>&1 &
echo $! >"$PID_FILE"
sleep 4

CHAIN="$(cast chain-id --rpc-url "http://${HOST}:${PORT}" 2>/dev/null || echo fail)"
if [[ "$CHAIN" != "56" ]]; then
  echo "[FAIL] fork not ready chain=$CHAIN"
  tail -20 "$LOG_FILE" || true
  exit 1
fi

echo "[OK] BSC fork ready chain_id=56 pid=$(cat "$PID_FILE")"
echo "       RPC: http://${HOST}:${PORT}"
echo "       Log: $LOG_FILE"
