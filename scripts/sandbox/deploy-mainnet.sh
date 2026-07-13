#!/usr/bin/env bash
# deploy-mainnet.sh — production rescue watch loop (BSC mainnet)
# Commit ref: 050dd5f — External Funder architecture (NO Target private key)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SANDBOX="$ROOT/scripts/sandbox"
ENV_SRC="$SANDBOX/mainnet.env.example"
ENV_DST="${MAINNET_ENV:-$ROOT/.env}"
LOG_DIR="$ROOT/logs"
LOG_FILE="$LOG_DIR/mainnet-prod.log"
PID_FILE="$LOG_DIR/mainnet-prod.pid"
AGENT_BIN="${HEXSTRIKE_AGENT:-$ROOT/bin/hexstrike-agent}"
RESCUE_ENGINE="${RESCUE_ENGINE:-go}"

usage() {
  echo "Usage: $0 {setup|build|dry-run|start|status|logs|stop}"
  echo "  RESCUE_ENGINE=go|python (default: go when binary exists)"
  exit 1
}

resolve_engine() {
  if [[ "$RESCUE_ENGINE" == "python" ]]; then
    echo "python"
    return
  fi
  if [[ -x "$AGENT_BIN" ]] || [[ "$RESCUE_ENGINE" == "go" ]]; then
    echo "go"
    return
  fi
  echo "python"
}

cmd_build() {
  bash "$SANDBOX/build-agent.sh" "$AGENT_BIN"
}

require_env() {
  if [[ ! -f "$ENV_DST" ]]; then
    echo "[FAIL] Missing $ENV_DST — run: $0 setup"
    exit 1
  fi
  # shellcheck disable=SC1090
  set -a && source "$ENV_DST" && set +a
  if [[ -z "${TARGET_WATCH_ADDRESS:-}" ]]; then
    echo "[FAIL] TARGET_WATCH_ADDRESS not set"
    exit 1
  fi
  if [[ -z "${ALLOWED_FUNDERS:-}" && -z "${FUNDER_ADDRESS:-}" ]]; then
    echo "[FAIL] ALLOWED_FUNDERS or FUNDER_ADDRESS required"
    exit 1
  fi
  if [[ "${DRY_RUN:-true}" != "true" ]]; then
    if [[ -z "$(resolve_key)" ]]; then
      echo "[FAIL] BOT_PRIVATE_KEY or AGENT_PRIVATE_KEY required for LIVE mode"
      exit 1
    fi
  fi
}

resolve_key() {
  echo "${BOT_PRIVATE_KEY:-${AGENT_PRIVATE_KEY:-}}"
}

cmd_setup() {
  mkdir -p "$LOG_DIR"
  if [[ -f "$ENV_DST" ]]; then
    echo "[OK]   $ENV_DST exists (not overwritten)"
  else
    cp "$ENV_SRC" "$ENV_DST"
    echo "[OK]   Created $ENV_DST from template"
  fi
  echo ""
  echo "Edit $ENV_DST:"
  echo "  TARGET_WATCH_ADDRESS=0x96B23C4680E1a37cE17730e6118D0C9223e72A66"
  echo "  ALLOWED_FUNDERS=0x060447dC91dfb22A5233731aF67E9E8dafdF24d1"
  echo "  BOT_ADDRESS=0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846"
  echo "  BOT_PRIVATE_KEY=<operator key — NEVER commit>"
  echo "  DRY_RUN=true  # flip to false only after dry-run PASS"
}

cmd_dry_run() {
  require_env
  export DRY_RUN=true
  export SANDBOX_ENV="$ENV_DST"
  engine="$(resolve_engine)"
  if [[ "$engine" == "go" ]]; then
    if [[ ! -x "$AGENT_BIN" ]]; then
      cmd_build
    fi
    echo "[dry-run] Go engine single poll"
    # shellcheck disable=SC1090
    set -a && source "$ENV_DST" && set +a
    export DRY_RUN=true
    "$AGENT_BIN" watch-dry-run
    echo "[OK] dry-run complete — check artifacts/sandbox/go-watch-events.jsonl"
  else
    echo "[dry-run] Python dummy_bot single poll"
    python3 "$SANDBOX/dummy_bot.py" --once --dry-run
    echo "[OK] dry-run complete — check for [CORE] Engine started (DRY_RUN)"
  fi
}

cmd_start() {
  require_env
  mkdir -p "$LOG_DIR"
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "[WARN] Already running pid $(cat "$PID_FILE")"
    exit 1
  fi
  export SANDBOX_ENV="$ENV_DST"
  # shellcheck disable=SC1090
  set -a && source "$ENV_DST" && set +a
  engine="$(resolve_engine)"
  if [[ "$engine" == "go" ]]; then
    if [[ ! -x "$AGENT_BIN" ]]; then
      cmd_build
    fi
    echo "[start] Go engine DRY_RUN=${DRY_RUN:-false} → $LOG_FILE"
    nohup "$AGENT_BIN" watch >>"$LOG_FILE" 2>&1 &
  else
    echo "[start] Python DRY_RUN=${DRY_RUN:-false} → $LOG_FILE"
    nohup python3 "$SANDBOX/dummy_bot.py" >>"$LOG_FILE" 2>&1 &
  fi
  echo $! >"$PID_FILE"
  sleep 2
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "[FAIL] process exited — tail $LOG_FILE"
    tail -20 "$LOG_FILE"
    exit 1
  fi
  echo "[OK] pid $(cat "$PID_FILE")"
  tail -5 "$LOG_FILE"
}

cmd_status() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "[OK] running pid $(cat "$PID_FILE")"
  else
    echo "[--] not running"
  fi
}

cmd_logs() {
  mkdir -p "$LOG_DIR"
  tail -f "$LOG_FILE"
}

cmd_stop() {
  if [[ -f "$PID_FILE" ]]; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    rm -f "$PID_FILE"
    echo "[OK] stopped"
  else
    echo "[--] no pid file"
  fi
}

case "${1:-}" in
  setup) cmd_setup ;;
  build) cmd_build ;;
  dry-run) cmd_dry_run ;;
  start) cmd_start ;;
  status) cmd_status ;;
  logs) cmd_logs ;;
  stop) cmd_stop ;;
  *) usage ;;
esac
