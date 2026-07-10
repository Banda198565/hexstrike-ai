#!/usr/bin/env bash
# vps-bootstrap-mirohost.sh — bootstrap HexStrike on MiroHost VPS (run from Mac)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${ROOT}/config/vps_config.json"
HOST="${VPS_HOST:-hexstrike-vps}"
INSTALL_DIR="${HEXSTRIKE_DIR:-/opt/hexstrike-ai}"
BRANCH="${HEXSTRIKE_BRANCH:-cursor/hexstrike-modules-mcp-be22}"
REPO="${HEXSTRIKE_REPO:-https://github.com/Banda198565/hexstrike-ai.git}"

log() { echo "[vps-bootstrap] $*"; }
die() { echo "[vps-bootstrap] ERROR: $*" >&2; exit 1; }

ssh -o BatchMode=yes -o ConnectTimeout=15 "${HOST}" "echo ok" >/dev/null 2>&1 || \
  die "SSH to ${HOST} failed — check ~/.ssh/config and key"

log "Bootstrapping ${HOST} → ${INSTALL_DIR} (${BRANCH})"

ssh "${HOST}" "bash -s" <<REMOTE
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git tmux python3 python3-venv curl

INSTALL_DIR="${INSTALL_DIR}"
BRANCH="${BRANCH}"
REPO="${REPO}"

if [[ -d "\${INSTALL_DIR}/.git" ]]; then
  cd "\${INSTALL_DIR}"
  git fetch origin "\${BRANCH}" --depth 1
  git checkout "\${BRANCH}" 2>/dev/null || git checkout -B "\${BRANCH}" FETCH_HEAD
  git reset --hard "origin/\${BRANCH}" 2>/dev/null || git reset --hard FETCH_HEAD
else
  git clone --branch "\${BRANCH}" --single-branch --depth 1 "\${REPO}" "\${INSTALL_DIR}"
  cd "\${INSTALL_DIR}"
fi

chmod +x hexstrike-orchestrator hexstrike-cli scripts/*.sh 2>/dev/null || true
ln -sf "\${INSTALL_DIR}/hexstrike-orchestrator" /usr/local/bin/hexstrike-orchestrator
ln -sf "\${INSTALL_DIR}/hexstrike-cli" /usr/local/bin/hexstrike-cli

python3 -m venv "\${INSTALL_DIR}/hexstrike-env" 2>/dev/null || true
"\${INSTALL_DIR}/hexstrike-env/bin/pip" install -q requests psutil flask 2>/dev/null || true

cat >/etc/systemd/system/hexstrike-orchestrator.service <<UNIT
[Unit]
Description=HexStrike orchestrator watch queue
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=\${INSTALL_DIR}
ExecStart=\${INSTALL_DIR}/hexstrike-orchestrator watch
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable hexstrike-orchestrator
systemctl restart hexstrike-orchestrator

echo "HEAD: \$(git log -1 --oneline)"
systemctl is-active hexstrike-orchestrator && echo "SERVICE: active" || echo "SERVICE: failed"
REMOTE

log "Running initial vps-full-readonly workflow..."
ssh "${HOST}" "cd ${INSTALL_DIR} && ./hexstrike-orchestrator run-all" || log "WARN: run-all had failures"

log "Done. Check: ssh ${HOST} 'cd ${INSTALL_DIR} && ./hexstrike-orchestrator report'"
