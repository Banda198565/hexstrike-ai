#!/usr/bin/env bash
# Install systemd timers for HexStrike VPS dry-run contour.
# Usage: sudo bash scripts/install-pipeline-systemd.sh [/opt/hexstrike-ai]
#
# Units:
#   hexstrike-pipeline.timer  — transaction+discovery every 15m
#   hexstrike-fastmcp-ops.timer — FastMCP verify/ops every 30m
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
TARGET="${TARGET_ADDRESS:-${TARGET_WALLET:-0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA}}"

if [[ "${HEXSTRIKE_TX_LIVE:-}" == "1" ]]; then
  echo "ERROR: HEXSTRIKE_TX_LIVE=1 forbidden — VPS timers are dry-run only" >&2
  exit 1
fi

command -v systemctl >/dev/null || { echo "systemctl required" >&2; exit 1; }

UNIT=/etc/systemd/system/hexstrike-pipeline.service
TIMER=/etc/systemd/system/hexstrike-pipeline.timer
OPS_UNIT=/etc/systemd/system/hexstrike-fastmcp-ops.service
OPS_TIMER=/etc/systemd/system/hexstrike-fastmcp-ops.timer

# Ensure scripts executable
chmod +x "${ROOT}/scripts/pipeline_transaction_discovery.sh" \
  "${ROOT}/scripts/vps-fastmcp-ops.sh" \
  "${ROOT}/scripts/fastmcp_verify.sh" 2>/dev/null || true

cat <<EOF | sudo tee "$UNIT" >/dev/null
[Unit]
Description=HexStrike transaction+discovery pipeline (dry-run)
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${ROOT}
Environment=TARGET_ADDRESS=${TARGET}
Environment=DRY_RUN=true
Environment=HEXSTRIKE_TX_LIVE=
ExecStart=/bin/bash ${ROOT}/scripts/pipeline_transaction_discovery.sh
User=root

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF | sudo tee "$TIMER" >/dev/null
[Unit]
Description=Run HexStrike pipeline every 15 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
Persistent=true

[Install]
WantedBy=timers.target
EOF

cat <<EOF | sudo tee "$OPS_UNIT" >/dev/null
[Unit]
Description=HexStrike FastMCP VPS ops (dry-run verify)
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${ROOT}
Environment=TARGET_ADDRESS=${TARGET}
Environment=DRY_RUN=true
Environment=HEXSTRIKE_TX_LIVE=
EnvironmentFile=-${ROOT}/.env
ExecStart=/bin/bash ${ROOT}/scripts/vps-fastmcp-ops.sh --standard
User=root

[Install]
WantedBy=multi-user.target
EOF

cat <<EOF | sudo tee "$OPS_TIMER" >/dev/null
[Unit]
Description=Run HexStrike FastMCP ops every 30 minutes

[Timer]
OnBootSec=8min
OnUnitActiveSec=30min
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now hexstrike-pipeline.timer
sudo systemctl enable --now hexstrike-fastmcp-ops.timer

echo "Installed:"
echo "  hexstrike-pipeline.timer   (every 15m)"
echo "  hexstrike-fastmcp-ops.timer (every 30m)"
echo "Check: systemctl list-timers | grep hexstrike"
echo "Logs:  journalctl -u hexstrike-fastmcp-ops.service -n 50"
echo "Manual: bash ${ROOT}/scripts/vps-fastmcp-ops.sh --quick"
