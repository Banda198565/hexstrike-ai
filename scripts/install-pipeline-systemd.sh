#!/usr/bin/env bash
# Install systemd timer for transaction+discovery pipeline (VPS dry-run).
# Usage: sudo bash scripts/install-pipeline-systemd.sh [/opt/hexstrike-ai]
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
UNIT=/etc/systemd/system/hexstrike-pipeline.service
TIMER=/etc/systemd/system/hexstrike-pipeline.timer

cat <<EOF | sudo tee "$UNIT" >/dev/null
[Unit]
Description=HexStrike transaction+discovery pipeline (dry-run)
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${ROOT}
Environment=TARGET_ADDRESS=0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA
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

sudo systemctl daemon-reload
sudo systemctl enable --now hexstrike-pipeline.timer
echo "Installed hexstrike-pipeline.timer — check: systemctl list-timers | grep hexstrike"
