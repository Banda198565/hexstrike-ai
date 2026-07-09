#!/usr/bin/env bash
# Bootstrap HexStrike orchestrator on VPS (fixes stale 0x4m4 shallow clone).
set -euo pipefail

INSTALL_DIR="${1:-/opt/hexstrike-ai}"
BRANCH="cursor/hexstrike-agents-a1cf"
REPO="https://github.com/Banda198565/hexstrike-ai.git"

log() { echo "[hexstrike] $*"; }

if [ -d "$INSTALL_DIR/.git" ]; then
  log "Backing up existing clone -> ${INSTALL_DIR}-old-$(date +%s)"
  mv "$INSTALL_DIR" "${INSTALL_DIR}-old-$(date +%s)"
fi

apt-get update -qq >/dev/null 2>&1 || true
apt-get install -y -qq git tmux python3 >/dev/null 2>&1 || true

log "Cloning $REPO branch $BRANCH -> $INSTALL_DIR"
git clone --branch "$BRANCH" --single-branch --depth 1 "$REPO" "$INSTALL_DIR"

cd "$INSTALL_DIR"
chmod +x hexstrike-orchestrator hexstrike-cli

log "HEAD: $(git log -1 --oneline)"
log "Ready. Run:"
echo "  cd $INSTALL_DIR && ./hexstrike-orchestrator run full-recon-readonly"
echo "  tmux new -s hexstrike -c $INSTALL_DIR './hexstrike-orchestrator watch'"
