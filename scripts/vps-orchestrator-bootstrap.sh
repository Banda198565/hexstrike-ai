#!/usr/bin/env bash
# Full VPS bootstrap: clone Banda198565 branch, systemd watch, first recon run.
# Usage (as root on VPS):
#   curl -fsSL https://raw.githubusercontent.com/Banda198565/hexstrike-ai/cursor/hexstrike-agents-a1cf/scripts/vps-orchestrator-bootstrap.sh | bash
set -euo pipefail

INSTALL_DIR="${HEXSTRIKE_DIR:-/opt/hexstrike-ai}"
BRANCH="cursor/hexstrike-agents-a1cf"
REPO="https://github.com/Banda198565/hexstrike-ai.git"
CLOUD_AGENT_PUBKEY="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIByufH4aDtJgrm/Udc3Vai4heLmGhT2N4xKdZ5bjZ0DH cursor-cloud-hexstrike"

log() { echo "[hexstrike] $*"; }
die() { echo "[hexstrike] ERROR: $*" >&2; exit 1; }

[[ $(id -u) -eq 0 ]] || die "Run as root: curl -fsSL ... | sudo bash"

log "Installing packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq git tmux python3 curl

log "SSH: allow cursor-cloud agent key (optional future access)"
mkdir -p /root/.ssh
chmod 700 /root/.ssh
grep -qF 'cursor-cloud-hexstrike' /root/.ssh/authorized_keys 2>/dev/null || \
  echo "$CLOUD_AGENT_PUBKEY" >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

if [[ -d "$INSTALL_DIR/.git" ]]; then
  backup="${INSTALL_DIR}-old-$(date +%s)"
  log "Backing up $INSTALL_DIR -> $backup"
  mv "$INSTALL_DIR" "$backup"
  # Keep hexstrike MCP service working if it pointed at old path
  if systemctl is-active hexstrike &>/dev/null; then
    sed -i "s|WorkingDirectory=.*|WorkingDirectory=$backup|" /etc/systemd/system/hexstrike.service 2>/dev/null || true
    systemctl daemon-reload
    systemctl restart hexstrike || true
  fi
fi

log "Cloning $REPO ($BRANCH) -> $INSTALL_DIR"
git clone --branch "$BRANCH" --single-branch --depth 1 "$REPO" "$INSTALL_DIR"

cd "$INSTALL_DIR"
chmod +x hexstrike-orchestrator hexstrike-cli scripts/vps-orchestrator-bootstrap.sh

log "HEAD: $(git log -1 --oneline)"

log "Installing systemd service: hexstrike-orchestrator"
cat >/etc/systemd/system/hexstrike-orchestrator.service <<UNIT
[Unit]
Description=HexStrike orchestrator watch queue
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/hexstrike-orchestrator watch
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable hexstrike-orchestrator
systemctl restart hexstrike-orchestrator

sleep 2
if systemctl is-active --quiet hexstrike-orchestrator; then
  log "hexstrike-orchestrator.service: active"
else
  log "WARN: service not active — check: journalctl -u hexstrike-orchestrator -n 30"
fi

log "Running initial workflow: vps-full-readonly (all agents)"
"$INSTALL_DIR/hexstrike-orchestrator" run-all || log "WARN: run-all had failures — check artifacts/orchestrator/"

log "=== DONE ==="
echo "  systemctl status hexstrike-orchestrator"
echo "  journalctl -u hexstrike-orchestrator -f"
echo "  cd $INSTALL_DIR && ./hexstrike-orchestrator report"
echo "  Queue jobs: drop JSON into $INSTALL_DIR/agents/queue/"
