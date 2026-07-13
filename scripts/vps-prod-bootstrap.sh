#!/usr/bin/env bash
# vps-prod-bootstrap.sh — рабочий контур HexStrike на чистом Ubuntu VPS (MiroHost)
# Запуск НА СЕРВЕРЕ как root:
#   ssh root@78.27.235.70
#   curl -fsSL https://raw.githubusercontent.com/Banda198565/hexstrike-ai/cursor/go-watch-mempool-ir-58a3/scripts/vps-prod-bootstrap.sh | bash
#
# Или если репо уже есть:
#   cd /opt/hexstrike-ai && git pull && bash scripts/vps-prod-bootstrap.sh
set -euo pipefail

INSTALL_DIR="${HEXSTRIKE_DIR:-/opt/hexstrike-ai}"
BRANCH="${HEXSTRIKE_BRANCH:-cursor/go-watch-mempool-ir-58a3}"
REPO="${HEXSTRIKE_REPO:-https://github.com/Banda198565/hexstrike-ai.git}"
CLOUD_AGENT_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIByufH4aDtJgrm/Udc3Vai4heLmGhT2N4xKdZ5bjZ0DH cursor-cloud-hexstrike"

log() { echo "[vps-prod] $*"; }
die() { echo "[vps-prod] FAIL: $*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || die "Run as root on VPS"

export DEBIAN_FRONTEND=noninteractive
log "Packages: git python3 venv curl jq build-essential"
apt-get update -qq
apt-get install -y -qq git tmux python3 python3-venv python3-pip curl jq build-essential ca-certificates

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
  log "Create .env from template"
  cat >.env <<'ENV'
CHAIN_ID=56
RPC_URL=http://51.222.42.220:8545
TARGET_WALLET=0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA
HEXSTRIKE_API_KEY=change-me-on-vps
OLLAMA_HOST=http://127.0.0.1:11434
LLM_PROVIDER=ollama-local
LLM_MODEL=deepseek-r1:1.5b
CURSOR_INTEGRATION_MODE=OFFLINE_PRIMARY
DRY_RUN=true
ENV
  chmod 600 .env
fi

chmod +x scripts/vps-start-server.sh scripts/vps-run-by-goal.sh scripts/monitor-combat-readiness.sh 2>/dev/null || true

log "Start hexstrike-server + monitor"
bash scripts/vps-start-server.sh

log "Combat readiness check"
bash scripts/monitor-combat-readiness.sh || log "WARN: readiness had warnings"

echo ""
echo "════════════════════════════════════════════════════════"
echo " VPS PROD CONTOUR — $INSTALL_DIR"
echo " IP: $(curl -sf --max-time 3 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
echo " API:  curl -s http://127.0.0.1:8888/health"
echo " Logs: tail -f /var/log/hexstrike/hot-wallet-monitor.log"
echo " Goal: bash scripts/vps-run-by-goal.sh --background"
echo "════════════════════════════════════════════════════════"
echo " SECURITY: passwd -> SSH key only; rotate root password"
echo " Edit secrets: nano $INSTALL_DIR/.env"
echo "════════════════════════════════════════════════════════"
