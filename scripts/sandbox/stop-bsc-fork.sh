#!/usr/bin/env bash
# stop-bsc-fork.sh — stop BSC anvil fork
set -euo pipefail
PID_FILE="${TMPDIR:-/tmp}/hexstrike-bsc-fork.pid"
PORT="${BSC_FORK_PORT:-8545}"

if [[ -f "$PID_FILE" ]]; then
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
fi
pkill -f "anvil.*--port ${PORT}" 2>/dev/null || true
pkill -f "anvil --host" 2>/dev/null || true
sleep 1
echo "[OK] BSC fork stopped (port ${PORT})"
