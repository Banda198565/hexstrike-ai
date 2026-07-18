#!/usr/bin/env bash
# ONE shot from YOUR Mac (where key SSH already works).
# 1) allowlists Cursor cloud egress IPs
# 2) installs cloud-agent pubkey
# 3) runs onbox bootstrap (no password rotate)
# 4) syncs local .env if present
#
#   cd ~/hexstrike-ai && git pull
#   bash scripts/vps-open-for-cloud-agent.sh
#   bash scripts/vps-open-for-cloud-agent.sh root@78.27.235.70
#
# Optional:
#   EXTRA_CLOUD_IPS=44.233.218.155
#   CLOUD_PUB='ssh-ed25519 AAAA... hexstrike-cloud-agent-YYYYMMDD'
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/vps-defaults.sh
source "$ROOT/scripts/vps-defaults.sh"

TARGET="${1:-$VPS_TARGET}"
KEY="${HEXSTRIKE_VPS_KEY}"
LOCAL_ENV="${LOCAL_ENV:-$ROOT/.env}"
REMOTE_DIR="${REMOTE_DIR:-$VPS_INSTALL}"

CLOUD_IPS=("${CLOUD_EGRESS_IPS_DEFAULT[@]}")
if [[ -n "${EXTRA_CLOUD_IPS:-}" ]]; then
  IFS=',' read -r -a _extra <<<"$EXTRA_CLOUD_IPS"
  for ip in "${_extra[@]}"; do
    ip="${ip// /}"
    [[ -n "$ip" ]] && CLOUD_IPS+=("$ip")
  done
fi

# Pubkey from cloud agent session — override with CLOUD_PUB when agent regenerates
CLOUD_PUB="${CLOUD_PUB:-ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIG3ASf+3bbpvVwpI2zdjpRz2HmayHivj8++CbV7eGIYg hexstrike-cloud-agent-20260717}"

log() { echo "[open-cloud] $*"; }
die() { echo "[open-cloud] ERROR: $*" >&2; exit 1; }

SSH=(ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
SCP=(scp -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
if [[ -f "$KEY" ]]; then
  SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20)
  SCP=(scp -i "$KEY" -o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
fi

log "test login $TARGET"
"${SSH[@]}" "$TARGET" 'echo OPERATOR_KEY_OK; whoami' || die "Your Mac cannot SSH either — fix key first (HEXSTRIKE_VPS_KEY=~/.ssh/hexstrike_vps)"

log "allowlist cloud IPs + install cloud agent pubkey"
IPS_CSV="$(IFS=,; echo "${CLOUD_IPS[*]}")"
"${SSH[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
IPS=($IPS_CSV)
PUB='$CLOUD_PUB'
mkdir -p /root/.ssh && chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
grep -qxF "\$PUB" /root/.ssh/authorized_keys || echo "\$PUB" >> /root/.ssh/authorized_keys
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

log "upload + run onbox bootstrap"
"${SCP[@]}" "$ROOT/scripts/bootstrap-new-vps-onbox.sh" "$TARGET:/tmp/bootstrap-new-vps-onbox.sh"
"${SSH[@]}" "$TARGET" 'KEEP_PASSWORD_AUTH=1 SKIP_OSINT=1 bash /tmp/bootstrap-new-vps-onbox.sh'

# Prefer /opt/hexstrike-ai when present after bootstrap
SYNC_DIR="$REMOTE_DIR"
if "${SSH[@]}" "$TARGET" "test -d /opt/hexstrike-ai"; then
  SYNC_DIR="/opt/hexstrike-ai"
elif "${SSH[@]}" "$TARGET" "test -d /root/hexstrike-ai"; then
  SYNC_DIR="/root/hexstrike-ai"
fi

if [[ -f "$LOCAL_ENV" ]]; then
  log "sync .env → $SYNC_DIR/.env"
  "${SCP[@]}" "$LOCAL_ENV" "$TARGET:$SYNC_DIR/.env"
  "${SSH[@]}" "$TARGET" "chmod 600 $SYNC_DIR/.env"
fi

log "OSINT smoke"
"${SSH[@]}" "$TARGET" "bash -s" <<EOF
set -euo pipefail
cd $SYNC_DIR
set -a; source .env 2>/dev/null || true; set +a
if [[ -f hexstrike-env/bin/activate ]]; then
  # shellcheck disable=SC1091
  source hexstrike-env/bin/activate
elif [[ -f hexstrike_env/bin/activate ]]; then
  # shellcheck disable=SC1091
  source hexstrike_env/bin/activate
fi
export PYTHONPATH=$SYNC_DIR:$SYNC_DIR/src
export ARKHAM_API_KEY="\${ARKHAM_API_KEY:-\${SAMSON_ARKHAM_API_KEY:-}}"
mkdir -p artifacts docs/recon
[[ -n "\${SHODAN_API_KEY:-}" ]] && bash scripts/run-ru-shodan-recon.sh || true
[[ -n "\${SHODAN_API_KEY:-}" ]] && bash scripts/run-kz-shodan-recon.sh || true
[[ -n "\${ARKHAM_API_KEY:-}" ]] && bash scripts/arkham-probe.sh || true
cat artifacts/vps-bootstrap-status.json 2>/dev/null || true
echo ALL_DONE
EOF

cat <<EOF

[open-cloud] DONE on VPS ($TARGET).
Cloud agent can retry SSH from: ${CLOUD_IPS[*]}
Next (from Mac): bash scripts/vps-from-mac.sh start

EOF
