#!/usr/bin/env bash
set -euo pipefail
PID_FILE="${TMPDIR:-/tmp}/hexstrike-anvil.pid"
PORT="${ANVIL_PORT:-8545}"

if [[ -f "$PID_FILE" ]]; then
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
fi
pkill -f "anvil.*--port ${PORT}" 2>/dev/null || true
pkill -f "anvil --host" 2>/dev/null || true
sleep 1
echo "[OK] Anvil stopped (port ${PORT})"
