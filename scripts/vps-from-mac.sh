#!/usr/bin/env bash
# Operator entrypoint FROM YOUR Mac (key already works).
# Uses real HexStrike VPS params — never ifconfig.io as server IP.
#
# Usage:
#   bash scripts/vps-from-mac.sh check
#   bash scripts/vps-from-mac.sh start          # git pull + vps-start-server.sh
#   bash scripts/vps-from-mac.sh status
#   bash scripts/vps-from-mac.sh shell
#   bash scripts/vps-from-mac.sh tunnel         # SOCKS on 127.0.0.1:1337
#   bash scripts/vps-from-mac.sh tunnel-stop
#   bash scripts/vps-from-mac.sh allow-cloud [EGRESS_IP] [PUBKEY_LINE]
#
# Env overrides: VPS_HOST VPS_USER HEXSTRIKE_VPS_KEY VPS_INSTALL SOCKS_PORT
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=scripts/vps-defaults.sh
source "$ROOT/scripts/vps-defaults.sh"

CMD="${1:-}"
shift || true

log() { echo "[vps-mac] $*"; }
die() { echo "[vps-mac] ERROR: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Operator entrypoint FROM YOUR Mac (real VPS params — never ifconfig.io as server IP).

Usage:
  bash scripts/vps-from-mac.sh check
  bash scripts/vps-from-mac.sh start          # git pull + vps-start-server.sh
  bash scripts/vps-from-mac.sh status
  bash scripts/vps-from-mac.sh shell
  bash scripts/vps-from-mac.sh tunnel         # SOCKS on 127.0.0.1:1337
  bash scripts/vps-from-mac.sh tunnel-stop
  bash scripts/vps-from-mac.sh allow-cloud <CLOUD_EGRESS_IP> [PUBKEY_LINE]

Defaults: root@78.27.235.70  key ~/.ssh/hexstrike_vps  install /opt/hexstrike-ai
Env: VPS_HOST VPS_USER HEXSTRIKE_VPS_KEY VPS_INSTALL SOCKS_PORT
EOF
  exit "${1:-0}"
}

[[ -n "$CMD" ]] || usage 1
[[ "$CMD" == "-h" || "$CMD" == "--help" ]] && usage 0

resolve_key() {
  if [[ -f "$HEXSTRIKE_VPS_KEY" ]]; then
    return 0
  fi
  # Explicit override that is missing → fail loud (do not silently fall back)
  if [[ -n "${HEXSTRIKE_VPS_KEY:-}" && "$HEXSTRIKE_VPS_KEY" != "$HOME/.ssh/hexstrike_vps" ]]; then
    die "HEXSTRIKE_VPS_KEY not found: $HEXSTRIKE_VPS_KEY"
  fi
  # Common Mac fallbacks (never invent placeholders / never use ifconfig.io as host)
  for cand in "$HOME/.ssh/hexstrike_vps" "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_rsa"; do
    if [[ -f "$cand" ]]; then
      HEXSTRIKE_VPS_KEY="$cand"
      log "using key: $HEXSTRIKE_VPS_KEY"
      return 0
    fi
  done
  die "no SSH private key (expected ~/.ssh/hexstrike_vps). Set HEXSTRIKE_VPS_KEY=/path/to/key"
}

ssh_base() {
  resolve_key
  SSH=(ssh -i "$HEXSTRIKE_VPS_KEY" -o IdentitiesOnly=yes -o BatchMode=yes \
    -o StrictHostKeyChecking=accept-new -o ConnectTimeout=20 \
    -o ServerAliveInterval=15 -o ServerAliveCountMax=3)
}

remote() {
  ssh_base
  "${SSH[@]}" "$VPS_TARGET" "$@"
}

resolve_remote_dir() {
  remote bash -s <<EOF
set -euo pipefail
for d in '$VPS_INSTALL' '$VPS_INSTALL_FALLBACK'; do
  if [[ -d "\$d/scripts" ]]; then
    echo "\$d"
    exit 0
  fi
done
echo '$VPS_INSTALL'
EOF
}

cmd_check() {
  log "target=$VPS_TARGET key=$HEXSTRIKE_VPS_KEY"
  remote 'echo SSH_OK; whoami; hostname -I | awk "{print \$1}"'
  DIR="$(resolve_remote_dir)"
  log "remote install dir: $DIR"
  remote "test -x '$DIR/scripts/vps-start-server.sh' && echo START_SCRIPT_OK || echo START_SCRIPT_MISSING"
}

cmd_start() {
  DIR="$(resolve_remote_dir)"
  log "starting hexstrike on $VPS_TARGET ($DIR)"
  remote bash -s <<EOF
set -euo pipefail
cd '$DIR'
if [[ -d .git ]]; then
  git config --global --add safe.directory '$DIR' 2>/dev/null || true
  git fetch origin master 2>/dev/null || true
  git pull origin master 2>/dev/null || echo '[vps-mac] WARN: git pull failed — continuing'
fi
bash scripts/vps-start-server.sh
EOF
}

cmd_status() {
  remote bash -s <<'EOF'
set -euo pipefail
echo "=== systemd ==="
systemctl is-active hexstrike-server hexstrike-orchestrator 2>/dev/null || true
echo "=== health :8888 ==="
curl -sf --max-time 8 http://127.0.0.1:8888/health | head -c 400 || echo HEALTH_FAIL
echo
echo "=== ollama :11434 ==="
curl -sf --max-time 5 http://127.0.0.1:11434/api/tags >/dev/null && echo OLLAMA_UP || echo OLLAMA_DOWN
echo "=== monitor ==="
pgrep -af autonomous_monitor.py 2>/dev/null | head -3 || echo MONITOR_DOWN
EOF
}

cmd_shell() {
  ssh_base
  exec "${SSH[@]}" -t "$VPS_TARGET" "${*:-bash -l}"
}

cmd_tunnel() {
  ssh_base
  if ss -ltn 2>/dev/null | grep -q ":${SOCKS_PORT} " || \
     netstat -ltn 2>/dev/null | grep -q ":${SOCKS_PORT} "; then
    die "port ${SOCKS_BIND}:${SOCKS_PORT} already in use — stop with: $0 tunnel-stop"
  fi
  # Bind localhost only — never 0.0.0.0 (open SOCKS proxy)
  "${SSH[@]}" -f -N -D "${SOCKS_BIND}:${SOCKS_PORT}" "$VPS_TARGET"
  log "SOCKS up → socks5://${SOCKS_BIND}:${SOCKS_PORT}"
  if curl -sf --max-time 15 --socks5 "${SOCKS_BIND}:${SOCKS_PORT}" https://ifconfig.io/ip >/tmp/vps-socks-ip.txt 2>/dev/null; then
    log "tunnel egress: $(tr -d '\n' </tmp/vps-socks-ip.txt) (expect VPS ${VPS_HOST})"
  else
    log "WARN: socks check failed — tunnel process may still be up"
  fi
}

cmd_tunnel_stop() {
  # Match only our local SOCKS forwarder
  pkill -f "ssh .* -D ${SOCKS_BIND}:${SOCKS_PORT} .*${VPS_HOST}" 2>/dev/null || \
    pkill -f "ssh .* -D ${SOCKS_PORT} .*${VPS_HOST}" 2>/dev/null || true
  log "tunnel stop requested for ${VPS_HOST}:${SOCKS_PORT}"
}

cmd_allow_cloud() {
  local egress_ip="${1:-}"
  local pub="${2:-}"
  [[ -n "$egress_ip" ]] || die "usage: $0 allow-cloud <CLOUD_EGRESS_IP> [ssh-ed25519 AAAA... comment]"
  [[ "$egress_ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "invalid IPv4: $egress_ip"

  log "allowlisting cloud egress $egress_ip on $VPS_TARGET"
  remote bash -s <<EOF
set -euo pipefail
IP='$egress_ip'
PUB='$pub'
mkdir -p /root/.ssh && chmod 700 /root/.ssh
touch /root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys
if [[ -n "\$PUB" ]]; then
  grep -qxF "\$PUB" /root/.ssh/authorized_keys || echo "\$PUB" >> /root/.ssh/authorized_keys
  echo "pubkey installed"
fi
if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active; then
  ufw allow from "\$IP" to any port 22 proto tcp comment cursor-cloud || true
fi
if command -v fail2ban-client >/dev/null 2>&1; then
  fail2ban-client set sshd unbanip "\$IP" 2>/dev/null || true
  fail2ban-client set ssh unbanip "\$IP" 2>/dev/null || true
fi
if command -v iptables >/dev/null 2>&1; then
  iptables -C INPUT -p tcp -s "\$IP" --dport 22 -j ACCEPT 2>/dev/null \\
    || iptables -I INPUT 1 -p tcp -s "\$IP" --dport 22 -j ACCEPT
fi
if [[ -f /etc/hosts.deny ]] && grep -qiE '^sshd[[:space:]]*:[[:space:]]*ALL' /etc/hosts.deny; then
  grep -q "sshd: \$IP" /etc/hosts.allow 2>/dev/null || echo "sshd: \$IP  # cursor-cloud" >> /etc/hosts.allow
fi
echo ALLOW_DONE
EOF
  log "done — cloud agent can retry SSH from $egress_ip"
}

case "$CMD" in
  check)        cmd_check ;;
  start)        cmd_start ;;
  status)       cmd_status ;;
  shell)        cmd_shell "$@" ;;
  tunnel)       cmd_tunnel ;;
  tunnel-stop)  cmd_tunnel_stop ;;
  allow-cloud)  cmd_allow_cloud "$@" ;;
  *)            die "unknown command: $CMD (try --help)" ;;
esac
