#!/usr/bin/env bash
# vps-prod-bootstrap.sh — HexStrike VPS bootstrap (Ubuntu OR AlmaLinux/RHEL)
#
# Run ON SERVER as root:
#   cd /opt/hexstrike-ai && git pull && bash scripts/vps-prod-bootstrap.sh
#
# Env:
#   HEXSTRIKE_DIR=/opt/hexstrike-ai
#   HEXSTRIKE_BRANCH=cursor/exploit-agent-orchestrator-58a3
#   SKIP_FASTMCP=1   — skip Alma FastMCP dry-run contour
#   SKIP_SERVER=1    — skip hexstrike-server start
set -euo pipefail

INSTALL_DIR="${HEXSTRIKE_DIR:-/opt/hexstrike-ai}"
BRANCH="${HEXSTRIKE_BRANCH:-cursor/exploit-agent-orchestrator-58a3}"
REPO="${HEXSTRIKE_REPO:-https://github.com/Banda198565/hexstrike-ai.git}"
CLOUD_AGENT_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIByufH4aDtJgrm/Udc3Vai4heLmGhT2N4xKdZ5bjZ0DH cursor-cloud-hexstrike"
SKIP_FASTMCP="${SKIP_FASTMCP:-0}"
SKIP_SERVER="${SKIP_SERVER:-0}"

log() { echo "[vps-prod] $*"; }
die() { echo "[vps-prod] FAIL: $*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || die "Run as root on VPS"

if [[ "${HEXSTRIKE_TX_LIVE:-}" == "1" ]]; then
  die "HEXSTRIKE_TX_LIVE=1 forbidden on VPS — live broadcast is Mac-only"
fi
unset HEXSTRIKE_TX_LIVE || true
export DRY_RUN=true

OS_ID="unknown"
if [[ -f /etc/os-release ]]; then
  # shellcheck source=/dev/null
  . /etc/os-release
  OS_ID="${ID:-unknown}"
  log "OS: ${PRETTY_NAME:-$OS_ID}"
fi

install_packages() {
  if command -v dnf >/dev/null 2>&1; then
    log "Packages via dnf (Alma/RHEL)..."
    dnf install -y git tmux python3 python3-pip python3-devel gcc openssl-devel \
      curl jq ca-certificates || die "dnf install failed"
  elif command -v yum >/dev/null 2>&1; then
    log "Packages via yum..."
    yum install -y git tmux python3 python3-pip python3-devel gcc openssl-devel \
      curl jq ca-certificates || die "yum install failed"
  elif command -v apt-get >/dev/null 2>&1; then
    log "Packages via apt (Debian/Ubuntu)..."
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq git tmux python3 python3-venv python3-pip curl jq \
      build-essential ca-certificates || die "apt install failed"
  else
    die "No dnf/yum/apt-get found"
  fi
}

install_packages

mkdir -p /var/log/hexstrike
mkdir -p /root/.ssh && chmod 700 /root/.ssh
grep -qF 'cursor-cloud-hexstrike' /root/.ssh/authorized_keys 2>/dev/null || \
  echo "$CLOUD_AGENT_PUBKEY" >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

if [[ ! -d "$INSTALL_DIR/.git" ]]; then
  log "Clone $REPO ($BRANCH) -> $INSTALL_DIR"
  git clone --branch "$BRANCH" --single-branch "$REPO" "$INSTALL_DIR"
else
  log "Update $INSTALL_DIR"
  cd "$INSTALL_DIR"
  git config --global --add safe.directory "$INSTALL_DIR" 2>/dev/null || true
  git fetch origin "$BRANCH"
  git checkout "$BRANCH" 2>/dev/null || git checkout -b "$BRANCH" "origin/$BRANCH"
  git pull origin "$BRANCH" || true
fi

cd "$INSTALL_DIR"
log "HEAD: $(git log -1 --oneline)"

if [[ ! -f .env ]]; then
  log "Create .env from template (watch-only defaults)"
  cat >.env <<'ENV'
CHAIN_ID=56
RPC_URL=https://bsc-dataseed.binance.org
TARGET_WALLET=0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA
BOT_ADDRESS=0x85dB346BE1d9d5D8ec4F57acf0067FbE53a6E846
HEXSTRIKE_API_KEY=change-me-on-vps
OLLAMA_HOST=http://127.0.0.1:11434
LLM_PROVIDER=ollama-local
LLM_MODEL=deepseek-r1:1.5b
CURSOR_INTEGRATION_MODE=OFFLINE_PRIMARY
DRY_RUN=true
HEXSTRIKE_TX_LIVE=
ENV
  chmod 600 .env
fi

chmod +x scripts/vps-start-server.sh scripts/vps-run-by-goal.sh \
  scripts/monitor-combat-readiness.sh scripts/vps-almalinux-fastmcp-bootstrap.sh \
  scripts/vps-fastmcp-ops.sh scripts/fastmcp_verify.sh 2>/dev/null || true

# FastMCP dry-run contour (Alma + Ubuntu)
if [[ "$SKIP_FASTMCP" -eq 0 && -f scripts/vps-almalinux-fastmcp-bootstrap.sh ]]; then
  log "FastMCP VPS dry-run contour..."
  SKIP_DNF=1 bash scripts/vps-almalinux-fastmcp-bootstrap.sh || \
    log "WARN: FastMCP bootstrap had warnings"
else
  log "SKIP_FASTMCP=1 or script missing"
fi

if [[ "$SKIP_SERVER" -eq 0 ]]; then
  log "Start hexstrike-server + monitor"
  bash scripts/vps-start-server.sh || log "WARN: server start failed"
else
  log "SKIP_SERVER=1"
fi

log "Combat readiness check"
bash scripts/monitor-combat-readiness.sh || log "WARN: readiness had warnings"

if [[ -f scripts/verify-exploit-integration.sh ]]; then
  log "ExploitAgent integration check"
  bash scripts/verify-exploit-integration.sh "$INSTALL_DIR" || \
    log "WARN: ExploitAgent not integrated — run: bash scripts/vps-sync-exploit-to-opt.sh"
fi

if [[ -f scripts/verify-combat-integration.sh ]]; then
  log "Combat agents check"
  bash scripts/verify-combat-integration.sh "$INSTALL_DIR" || \
    log "WARN: combat verify failed"
fi

echo ""
echo "════════════════════════════════════════════════════════"
echo " VPS PROD CONTOUR — $INSTALL_DIR ($OS_ID)"
echo " IP: $(curl -sf --max-time 3 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
echo " API:  curl -s http://127.0.0.1:8888/health"
echo " Logs: tail -f /var/log/hexstrike/hot-wallet-monitor.log"
echo " Ops:  bash scripts/vps-fastmcp-ops.sh"
echo " Goal: bash scripts/vps-run-by-goal.sh --background"
echo "════════════════════════════════════════════════════════"
echo " SECURITY: HEXSTRIKE_TX_LIVE forbidden on VPS; live = Mac only"
echo " Edit secrets: nano $INSTALL_DIR/.env"
echo "════════════════════════════════════════════════════════"
