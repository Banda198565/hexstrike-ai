#!/usr/bin/env bash
# mac-vps-prod-deploy.sh — с Mac: залить bootstrap на VPS и запустить prod контур
# Usage:
#   export VPS_HOST=78.27.235.70
#   export VPS_USER=root
#   bash scripts/mac-vps-prod-deploy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VPS_HOST="${VPS_HOST:-78.27.235.70}"
VPS_USER="${VPS_USER:-root}"
BRANCH="${HEXSTRIKE_BRANCH:-cursor/exploit-agent-orchestrator-58a3}"

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[[ -n "${VPS_SSH_KEY:-}" && -f "$VPS_SSH_KEY" ]] && SSH_OPTS+=(-i "$VPS_SSH_KEY")

log() { echo "[mac-deploy] $*"; }

log "Deploy prod contour -> ${VPS_USER}@${VPS_HOST} (branch $BRANCH)"
log "You will be prompted for root password (or use SSH key)"

scp "${SSH_OPTS[@]}" "$ROOT/scripts/vps-prod-bootstrap.sh" "${VPS_USER}@${VPS_HOST}:/tmp/vps-prod-bootstrap.sh"
ssh "${SSH_OPTS[@]}" "${VPS_USER}@${VPS_HOST}" \
  "HEXSTRIKE_BRANCH=$BRANCH bash /tmp/vps-prod-bootstrap.sh"

log "DONE — verify:"
echo "  ssh ${VPS_USER}@${VPS_HOST} 'curl -s http://127.0.0.1:8888/health | head'"
echo "  ssh ${VPS_USER}@${VPS_HOST} 'tail -5 /var/log/hexstrike/hot-wallet-monitor.log'"
