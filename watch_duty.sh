#!/usr/bin/env bash
# watch_duty.sh — keep autonomous_monitor running 24/7 with auto-restart
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

ARTIFACTS_DIR="$ROOT/artifacts"
DUTY_LOG="$ARTIFACTS_DIR/duty.log"
mkdir -p "$ARTIFACTS_DIR"

# Load API key from .env
if [[ -f "$ROOT/.env" ]]; then
  # shellcheck disable=SC2046
  export $(grep -v '^#' "$ROOT/.env" | grep HEXSTRIKE_API_KEY | xargs)
fi

if [[ -z "${HEXSTRIKE_API_KEY:-}" ]]; then
  echo "[!] HEXSTRIKE_API_KEY not set. Copy .env.example to .env and configure a key."
  exit 1
fi

# Prefer project venv when available
if [[ -x "$ROOT/hexstrike-env/bin/python3" ]]; then
  PYTHON="$ROOT/hexstrike-env/bin/python3"
elif [[ -x "$ROOT/hexstrike_env/bin/python3" ]]; then
  PYTHON="$ROOT/hexstrike_env/bin/python3"
else
  PYTHON="python3"
fi

MONITOR="$ROOT/scripts/autonomous_monitor.py"

echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Боевое дежурство начато." | tee -a "$DUTY_LOG"
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Python: $PYTHON" | tee -a "$DUTY_LOG"
echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Monitor: $MONITOR" | tee -a "$DUTY_LOG"

while true; do
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Запуск монитора..." | tee -a "$DUTY_LOG"
  "$PYTHON" "$MONITOR" 2>&1 | tee -a "$DUTY_LOG" || true
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] Монитор упал! Перезапуск через 5 секунд..." | tee -a "$DUTY_LOG"
  sleep 5
done
