#!/usr/bin/env bash
# ONE shot from YOUR Mac (where operator SSH already works).
# 1) allowlists Cursor cloud egress IPs
# 2) installs cloud-agent pubkey(s)
# 3) runs onbox bootstrap (no password rotate)
# 4) syncs local .env if present
# 5) installs critical-services watchdog (crypto_bot + SOCKS5:1337)
#
#   cd ~/hexstrike-ai && git pull
#   bash scripts/vps-open-for-cloud-agent.sh root@78.27.235.70
#
# Optional:
#   EXTRA_IPS="52.34.217.149" bash scripts/vps-open-for-cloud-agent.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-root@78.27.235.70}"
KEY="${HEXSTRIKE_VPS_KEY:-$HOME/.ssh/hexstrike_vps}"
LOCAL_ENV="${LOCAL_ENV:-$ROOT/.env}"
REMOTE_DIR="${REMOTE_DIR:-/root/hexstrike-ai}"

# Current Cursor cloud egress (update if agent IP changes)
CLOUD_IPS=(
  "52.40.48.127"
  "44.236.205.197"
  "52.13.17.46"
  "54.201.20.43"
  "44.239.176.212"
  "50.112.242.221"
  "52.34.217.149"
)
if [[ -n "${EXTRA_IPS:-}" ]]; then
  # shellcheck disable=SC2206
  CLOUD_IPS+=(${EXTRA_IPS})
fi

# Pubkeys for cloud agents (append-only; safe to re-run)
CLOUD_PUBS=(
  "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG3ASf+3bbpvVwpI2zdjpRz2HmayHivj8++CbV7eGIYg hexstrike-cloud-agent-20260717"
  "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIMReLZz4NqfH1q26nhMY1uE24JZowbpKYyYzaGBz+oNR hexstrike-cloud-agent-20260718-bc1f"
  "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOc4+341bbWPywULPF8MTDq9VpaDMT4+TqKLpK4Uo2Gs hexstrike-01@cursor-20260714"
  "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIByufH4aDtJgrm/Udc3Vai4heLmGhT2N4xKdZ5bjZ0DH cursor-cloud-hexstrike"
)

log() { echo "[open-cloud] $*"; }
die() { echo "[open-cloud] ERROR: $*" >&2; exit 1; }

SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
SCP=(scp -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
if [[ -f "$KEY" ]]; then
  SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
  SCP=(scp -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
elif [[ -f "$HOME/.ssh/id_ed25519" ]]; then
  KEY="$HOME/.ssh/id_ed25519"
  SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
  SCP=(scp -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
fi

log "test login $TARGET"
"${SSH[@]}" "$TARGET" 'echo OPERATOR_KEY_OK; whoami' || die "Your Mac cannot SSH either — fix operator key first"

log "allowlist cloud IPs + install cloud agent pubkeys"
IPS_CSV="$(IFS=,; echo "${CLOUD_IPS[*]}")"
PUBS_B64="$(printf '%s\n' "${CLOUD_PUBS[@]}" | base64 | tr -d '\n')"
"${SSH[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
IPS=($IPS_CSV)
mkdir -p /root/.ssh && chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
echo '$PUBS_B64' | base64 -d | while IFS= read -r PUB; do
  [[ -z "\$PUB" ]] && continue
  grep -qxF "\$PUB" /root/.ssh/authorized_keys || echo "\$PUB" >> /root/.ssh/authorized_keys
done
for ip in "\${IPS[@]}"; do
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active; then
    ufw allow from "\$ip" to any port 22 proto tcp comment cursor-cloud || true
  fi
  if command -v fail2ban-client >/dev/null 2>&1; then
    fail2ban-client set sshd unbanip "\$ip" 2>/dev/null || true
    fail2ban-client set ssh unbanip "\$ip" 2>/dev/null || true
  fi
  if command -v iptables >/dev/null 2>&1; then
    iptables -C INPUT -p tcp -s "\$ip" --dport 22 -j ACCEPT 2>/dev/null \\
      || iptables -I INPUT 1 -p tcp -s "\$ip" --dport 22 -j ACCEPT
  fi
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state 2>/dev/null | grep -q running; then
    firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=\${ip}/32 port port=22 protocol=tcp accept" || true
    firewall-cmd --reload || true
  fi
  echo "allowed \$ip"
done
if [[ -f /etc/hosts.deny ]] && grep -qiE '^sshd\\s*:\\s*ALL' /etc/hosts.deny; then
  for ip in "\${IPS[@]}"; do
    grep -q "sshd: \$ip" /etc/hosts.allow 2>/dev/null || echo "sshd: \$ip  # cursor-cloud" >> /etc/hosts.allow
  done
fi
echo ALLOW_DONE
EOF

if [[ -f "$ROOT/scripts/bootstrap-new-vps-onbox.sh" ]]; then
  log "upload + run onbox bootstrap"
  "${SCP[@]}" "$ROOT/scripts/bootstrap-new-vps-onbox.sh" "$TARGET:/tmp/bootstrap-new-vps-onbox.sh"
  "${SSH[@]}" "$TARGET" 'KEEP_PASSWORD_AUTH=1 SKIP_OSINT=1 bash /tmp/bootstrap-new-vps-onbox.sh' || log "WARN: onbox bootstrap partial"
fi

if [[ -f "$LOCAL_ENV" ]]; then
  log "sync .env"
  "${SCP[@]}" "$LOCAL_ENV" "$TARGET:$REMOTE_DIR/.env"
  "${SSH[@]}" "$TARGET" "chmod 600 $REMOTE_DIR/.env"
fi

log "install critical watchdog (crypto_bot + SOCKS5:1337)"
"${SCP[@]}" "$ROOT/scripts/vps-critical-watchdog.sh" "$TARGET:/usr/local/bin/vps-critical-watchdog.sh"
"${SSH[@]}" "$TARGET" 'bash -s' <<'EOF'
set -euo pipefail
chmod +x /usr/local/bin/vps-critical-watchdog.sh
cat >/etc/systemd/system/vps-critical-watchdog.service <<'UNIT'
[Unit]
Description=HexStrike critical services watchdog (crypto_bot + SOCKS5)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
ExecStart=/usr/local/bin/vps-critical-watchdog.sh
Nice=10
UNIT
cat >/etc/systemd/system/vps-critical-watchdog.timer <<'UNIT'
[Unit]
Description=Run critical services watchdog every minute

[Timer]
OnBootSec=30s
OnUnitActiveSec=60s
AccuracySec=5s
Unit=vps-critical-watchdog.service

[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now vps-critical-watchdog.timer
/usr/local/bin/vps-critical-watchdog.sh || true
systemctl list-timers --all | grep -i vps-critical || true
EOF

cat <<EOF

[open-cloud] DONE on VPS.
Cloud agent can now retry SSH from: ${CLOUD_IPS[*]}
Reply to the agent: retry

EOF
