#!/usr/bin/env bash
# mac-ollama-vps-tunnel.sh — Mac → VPS SSH tunnel for Ollama (safe alternative to exposed port)
#
# Usage (on Mac):
#   VPS_HOST=78.27.235.70 bash scripts/mac-ollama-vps-tunnel.sh
#   bash scripts/mac-ollama-vps-tunnel.sh --stop
#   bash scripts/mac-ollama-vps-tunnel.sh --check
#
# After tunnel is up: OLLAMA_HOST=http://127.0.0.1:11434 works locally
set -euo pipefail

VPS_HOST="${VPS_HOST:-78.27.235.70}"
VPS_USER="${VPS_USER:-root}"
LOCAL_PORT="${OLLAMA_LOCAL_PORT:-11434}"
REMOTE_PORT="${OLLAMA_REMOTE_PORT:-11434}"
PID_FILE="/tmp/hexstrike-ollama-tunnel.pid"

SSH_OPTS=(-o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes)
[[ -n "${VPS_SSH_KEY:-}" && -f "$VPS_SSH_KEY" ]] && SSH_OPTS+=(-i "$VPS_SSH_KEY")

MODE="${1:---start}"

log() { echo "[ollama-tunnel] $*"; }
die() { echo "[ollama-tunnel] FAIL: $*" >&2; exit 1; }

case "$MODE" in
  --stop)
    if [[ -f "$PID_FILE" ]]; then
      pid=$(cat "$PID_FILE")
      if kill -0 "$pid" 2>/dev/null; then
        kill "$pid" && log "stopped tunnel pid $pid"
      fi
      rm -f "$PID_FILE"
    else
      log "no tunnel pid file"
    fi
    exit 0
    ;;
  --check)
    if curl -sf --max-time 3 "http://127.0.0.1:${LOCAL_PORT}/api/version" >/dev/null 2>&1; then
      curl -s "http://127.0.0.1:${LOCAL_PORT}/api/version"; echo
      log "tunnel active on 127.0.0.1:${LOCAL_PORT}"
      exit 0
    fi
    log "no tunnel on 127.0.0.1:${LOCAL_PORT}"
    exit 1
    ;;
  --start|"") ;;
  *) die "unknown: $MODE" ;;
esac

# Stop any existing tunnel on same port
if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  log "restarting existing tunnel"
  kill "$(cat "$PID_FILE")" 2>/dev/null || true
  rm -f "$PID_FILE"
fi

if lsof -iTCP:"$LOCAL_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  die "port $LOCAL_PORT already in use — stop local ollama or change OLLAMA_LOCAL_PORT"
fi

log "opening SSH tunnel ${VPS_USER}@${VPS_HOST} :${REMOTE_PORT} → 127.0.0.1:${LOCAL_PORT}"
ssh "${SSH_OPTS[@]}" -f -N -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}" "${VPS_USER}@${VPS_HOST}"

# Grab the ssh pid
sleep 1
tunnel_pid=$(pgrep -f "ssh.*-L ${LOCAL_PORT}:127.0.0.1:${REMOTE_PORT}.*${VPS_USER}@${VPS_HOST}" | head -1 || true)
if [[ -n "$tunnel_pid" ]]; then
  echo "$tunnel_pid" > "$PID_FILE"
  log "tunnel pid $tunnel_pid → $PID_FILE"
fi

# Verify
for i in $(seq 1 10); do
  if curl -sf --max-time 2 "http://127.0.0.1:${LOCAL_PORT}/api/version" >/dev/null 2>&1; then
    log "✅ Ollama reachable via tunnel: $(curl -sf http://127.0.0.1:${LOCAL_PORT}/api/version)"
    echo ""
    echo "Set in your shell / .env:"
    echo "  export OLLAMA_HOST=http://127.0.0.1:${LOCAL_PORT}"
    echo "  export LLM_PROVIDER=ollama-local"
    echo "  export LLM_MODEL=deepseek-r1:1.5b   # or your pulled model"
    echo ""
    echo "Stop tunnel: bash scripts/mac-ollama-vps-tunnel.sh --stop"
    exit 0
  fi
  sleep 1
done

die "tunnel opened but API unreachable on 127.0.0.1:${LOCAL_PORT} — check VPS: ssh ${VPS_USER}@${VPS_HOST} 'curl -sf http://127.0.0.1:${REMOTE_PORT}/api/version'"
