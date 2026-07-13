#!/usr/bin/env bash
# mac-vps-sync-fastmcp.sh — Mac → Alma VPS: rsync FastMCP combat scripts + remote ops
#
# Run ON MAC:
#   VPS_HOST=x.x.x.x bash scripts/mac-vps-sync-fastmcp.sh
#   VPS_SSH_KEY=~/.ssh/id_ed25519 bash scripts/mac-vps-sync-fastmcp.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

VPS_HOST="${VPS_HOST:-78.27.235.70}"
VPS_USER="${VPS_USER:-root}"
VPS_OPT="${VPS_INSTALL:-/opt/hexstrike-ai}"
BRANCH="${HEXSTRIKE_BRANCH:-cursor/exploit-agent-orchestrator-58a3}"

SSH_OPTS=(-o StrictHostKeyChecking=accept-new)
[[ -n "${VPS_SSH_KEY:-}" && -f "$VPS_SSH_KEY" ]] && SSH_OPTS+=(-i "$VPS_SSH_KEY")
RSYNC_SSH="ssh ${SSH_OPTS[*]}"

log() { echo "[mac-vps-fastmcp] $*"; }
die() { echo "[mac-vps-fastmcp] ERROR: $*" >&2; exit 1; }

REMOTE="${VPS_USER}@${VPS_HOST}"

REQUIRED=(
  scripts/fastmcp_verify.sh
  scripts/fastmcp_live_cycle.sh
  scripts/vps-almalinux-fastmcp-bootstrap.sh
  scripts/vps-fastmcp-ops.sh
  scripts/vps-pull-and-ops.sh
  scripts/vps-prod-bootstrap.sh
  scripts/install-pipeline-systemd.sh
  scripts/run_fastmcp_combat_live.py
  scripts/mac-fastmcp-live.sh
  scripts/verify-combat-integration.sh
  scripts/pipeline_transaction_discovery.sh
  docs/FASTMCP-COMBAT-TX.md
  hexstrike
  config/hot-wallet-allowlist.json
)

for f in "${REQUIRED[@]}"; do
  [[ -f "$ROOT/$f" ]] || die "missing $f — git checkout $BRANCH"
done

log "Rsync FastMCP scripts → ${REMOTE}:${VPS_OPT}"
rsync -avz -e "$RSYNC_SSH" \
  "$ROOT/scripts/fastmcp_verify.sh" \
  "$ROOT/scripts/fastmcp_live_cycle.sh" \
  "$ROOT/scripts/vps-almalinux-fastmcp-bootstrap.sh" \
  "$ROOT/scripts/vps-fastmcp-ops.sh" \
  "$ROOT/scripts/vps-pull-and-ops.sh" \
  "$ROOT/scripts/vps-prod-bootstrap.sh" \
  "$ROOT/scripts/install-pipeline-systemd.sh" \
  "$ROOT/scripts/run_fastmcp_combat_live.py" \
  "$ROOT/scripts/mac-fastmcp-live.sh" \
  "$ROOT/scripts/verify-combat-integration.sh" \
  "$ROOT/scripts/pipeline_transaction_discovery.sh" \
  "${REMOTE}:${VPS_OPT}/scripts/"

rsync -avz -e "$RSYNC_SSH" \
  "$ROOT/docs/FASTMCP-COMBAT-TX.md" \
  "${REMOTE}:${VPS_OPT}/docs/"

rsync -avz -e "$RSYNC_SSH" \
  "$ROOT/hexstrike" \
  "${REMOTE}:${VPS_OPT}/"

rsync -avz -e "$RSYNC_SSH" \
  "$ROOT/config/hot-wallet-allowlist.json" \
  "${REMOTE}:${VPS_OPT}/config/"

if [[ -d "$ROOT/src/hexstrike/mcp/fastmcp" ]]; then
  log "Rsync src/hexstrike/mcp/fastmcp/"
  ssh "${SSH_OPTS[@]}" "$REMOTE" "mkdir -p ${VPS_OPT}/src/hexstrike/mcp/fastmcp"
  rsync -avz -e "$RSYNC_SSH" \
    "$ROOT/src/hexstrike/mcp/fastmcp/" \
    "${REMOTE}:${VPS_OPT}/src/hexstrike/mcp/fastmcp/"
fi

log "Remote: chmod + pull-and-ops --quick"
ssh "${SSH_OPTS[@]}" "$REMOTE" bash -s <<REMOTE
set -euo pipefail
cd ${VPS_OPT}
chmod +x scripts/*.sh hexstrike 2>/dev/null || true
export HEXSTRIKE_BRANCH=${BRANCH}
export HEXSTRIKE_TX_LIVE=
if [[ -d .git ]]; then
  git config --global --add safe.directory ${VPS_OPT} 2>/dev/null || true
  git fetch origin ${BRANCH} 2>/dev/null || true
  git checkout ${BRANCH} 2>/dev/null || true
  git pull --ff-only origin ${BRANCH} 2>/dev/null || true
fi
bash scripts/vps-pull-and-ops.sh --quick
REMOTE

log "DONE — VPS dry-run ops complete. Live remains Mac-only."
