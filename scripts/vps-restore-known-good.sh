#!/usr/bin/env bash
# vps-restore-known-good.sh — restore working VPS orchestrator stack (run as root)
set -euo pipefail

INSTALL_DIR="${HEXSTRIKE_DIR:-/opt/hexstrike-ai}"
BRANCH="${HEXSTRIKE_BRANCH:-cursor/hexstrike-agents-a1cf}"
PORT="${HEXSTRIKE_PORT:-8888}"
RUN_DETECT="${RUN_DETECT:-1}"
RUN_CHECKLIST="${RUN_CHECKLIST:-0}"

log() { echo "[restore] $*"; }
die() { echo "[restore] ERROR: $*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || die "Run as root on VPS"

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  log "No repo at $INSTALL_DIR — bootstrap first:"
  echo "  curl -fsSL https://raw.githubusercontent.com/Banda198565/hexstrike-ai/${BRANCH}/scripts/vps-orchestrator-bootstrap.sh | bash"
  exit 1
fi

cd "$INSTALL_DIR"
log "Fetching $BRANCH..."
git fetch origin "$BRANCH"
git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" "origin/$BRANCH"
git pull origin "$BRANCH"

for f in hexstrike-cli hexstrike-orchestrator hexstrike-ultra hexstrike_server.py; do
  [[ -f "$f" ]] && chmod +x "$f" 2>/dev/null || true
done
chmod +x scripts/*.sh 2>/dev/null || true

# Ensure CLI on PATH
[[ -x hexstrike-cli ]] && ln -sf "$INSTALL_DIR/hexstrike-cli" /usr/local/bin/hexstrike-cli
[[ -x hexstrike-orchestrator ]] && ln -sf "$INSTALL_DIR/hexstrike-orchestrator" /usr/local/bin/hexstrike-orchestrator

if ! curl -sf --max-time 3 "http://127.0.0.1:${PORT}/health" >/dev/null; then
  log "Starting hexstrike_server on :${PORT}..."
  pkill -f "hexstrike_server.py" 2>/dev/null || true
  sleep 1
  nohup python3 hexstrike_server.py --port "${PORT}" >/tmp/hexstrike-server.log 2>&1 &
  for _ in $(seq 1 15); do
    curl -sf --max-time 2 "http://127.0.0.1:${PORT}/health" >/dev/null && break
    sleep 1
  done
fi

log "Health:"
curl -sf "http://127.0.0.1:${PORT}/health" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f\"  status={d.get('status')} version={d.get('version')} tools={d.get('total_tools_available')}/{d.get('total_tools_count')}\")
" || die "Server not responding on :${PORT}"

if [[ "$RUN_DETECT" == "1" ]]; then
  log "Technology detect..."
  if [[ -x "$INSTALL_DIR/scripts/vps-technology-detect.sh" ]]; then
    "$INSTALL_DIR/scripts/vps-technology-detect.sh" "http://localhost:${PORT}"
  elif [[ -x hexstrike-cli ]]; then
    ./hexstrike-cli technology-detect "http://localhost:${PORT}"
  else
    curl -sf "http://127.0.0.1:${PORT}/health" -D - -o /dev/null | grep -i '^Server:'
  fi
fi

if [[ "$RUN_CHECKLIST" == "1" ]]; then
  log "Dispatch Agent-Report-06 generate-defensive-checklist..."
  ./hexstrike-orchestrator dispatch Agent-Report-06 generate-defensive-checklist
fi

log "HEAD: $(git log -1 --oneline)"
echo ""
echo "=== Restore OK ==="
echo "  dir:    $INSTALL_DIR"
echo "  branch: $BRANCH"
echo "  api:    http://127.0.0.1:${PORT}/health"
echo ""
echo "Optional:"
echo "  RUN_CHECKLIST=1 $0"
echo "  ./scripts/install-critical-tools.sh"
