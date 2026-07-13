#!/usr/bin/env bash
# vps-pull-and-ops.sh — Alma/Ubuntu VPS: git pull latest branch + FastMCP ops
#
# Usage (on VPS):
#   bash scripts/vps-pull-and-ops.sh
#   bash scripts/vps-pull-and-ops.sh --full
#   HEXSTRIKE_BRANCH=cursor/exploit-agent-orchestrator-58a3 bash scripts/vps-pull-and-ops.sh --quick
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

BRANCH="${HEXSTRIKE_BRANCH:-cursor/exploit-agent-orchestrator-58a3}"
MODE="${1:---standard}"

log() { echo "[vps-pull] $*"; }
die() { echo "[vps-pull] FAIL: $*" >&2; exit 1; }

if [[ "${HEXSTRIKE_TX_LIVE:-}" == "1" ]]; then
  die "HEXSTRIKE_TX_LIVE=1 forbidden on VPS"
fi
unset HEXSTRIKE_TX_LIVE || true

log "ROOT=$ROOT branch=$BRANCH mode=$MODE"

if [[ -d .git ]]; then
  git config --global --add safe.directory "$ROOT" 2>/dev/null || true
  log "fetch/checkout/pull $BRANCH"
  git fetch origin "$BRANCH"
  git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" "origin/$BRANCH"
  git pull --ff-only origin "$BRANCH" || git pull origin "$BRANCH" || true
  log "HEAD: $(git log -1 --oneline)"
else
  die "Not a git repo: $ROOT"
fi

chmod +x scripts/vps-fastmcp-ops.sh scripts/fastmcp_verify.sh \
  scripts/vps-almalinux-fastmcp-bootstrap.sh 2>/dev/null || true

# Activate venv if present
if [[ -f hexstrike_env/bin/activate ]]; then
  # shellcheck source=/dev/null
  source hexstrike_env/bin/activate
fi

log "Run FastMCP ops $MODE"
exec bash scripts/vps-fastmcp-ops.sh "$MODE"
