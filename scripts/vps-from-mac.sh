#!/usr/bin/env bash
# Operator entrypoint FROM YOUR Mac (key already works).
# Uses real HexStrike VPS params — never ifconfig.io as server IP.
#
# Usage:
#   bash scripts/vps-from-mac.sh check
#   bash scripts/vps-from-mac.sh install-key    # ssh-copy-id with the right key
#   bash scripts/vps-from-mac.sh start          # ensure repo + vps-start-server.sh
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

REPO_URL="${REPO_URL:-https://github.com/Banda198565/hexstrike-ai.git}"
REPO_BRANCH="${REPO_BRANCH:-master}"

CMD="${1:-}"
shift || true

log() { echo "[vps-mac] $*"; }
die() { echo "[vps-mac] ERROR: $*" >&2; exit 1; }

usage() {
  cat <<'EOF'
Operator entrypoint FROM YOUR Mac (real VPS params — never ifconfig.io as server IP).

Usage:
  bash scripts/vps-from-mac.sh check
  bash scripts/vps-from-mac.sh install-key    # copy pubkey to VPS (fixes ssh-copy-id)
  bash scripts/vps-from-mac.sh start          # clone/pull + vps-start-server.sh
  bash scripts/vps-from-mac.sh status
  bash scripts/vps-from-mac.sh shell
  bash scripts/vps-from-mac.sh tunnel         # SOCKS on 127.0.0.1:1337 (NOT 0.0.0.0)
  bash scripts/vps-from-mac.sh tunnel-stop
  bash scripts/vps-from-mac.sh allow-cloud <CLOUD_EGRESS_IP> [PUBKEY_LINE]

Defaults: root@78.27.235.70  key ~/.ssh/hexstrike_vps  install /opt/hexstrike-ai
There is NO repair / vps-setup.sh / start_all.sh / health.sh — use these commands.
Env: VPS_HOST VPS_USER HEXSTRIKE_VPS_KEY VPS_INSTALL SOCKS_PORT
EOF
  exit "${1:-0}"
}

[[ -n "$CMD" ]] || usage 1
[[ "$CMD" == "-h" || "$CMD" == "--help" ]] && usage 0

resolve_key() {
  # Ignore stale/wrong overrides (e.g. Linux /root/... path pasted on a Mac)
  if [[ -n "${HEXSTRIKE_VPS_KEY:-}" && ! -f "$HEXSTRIKE_VPS_KEY" ]]; then
    if [[ "$HEXSTRIKE_VPS_KEY" == /root/* || "$HEXSTRIKE_VPS_KEY" == /home/* ]]; then
      log "WARN: HEXSTRIKE_VPS_KEY=$HEXSTRIKE_VPS_KEY missing on this host — falling back to ~/.ssh"
      HEXSTRIKE_VPS_KEY="$HOME/.ssh/hexstrike_vps"
    else
      die "HEXSTRIKE_VPS_KEY not found: $HEXSTRIKE_VPS_KEY"
    fi
  fi
  if [[ -f "$HEXSTRIKE_VPS_KEY" ]]; then
    return 0
  fi
  # Common Mac/operator fallbacks (never /root on a laptop; never ifconfig.io as host)
  for cand in "$HOME/.ssh/hexstrike_vps" "$HOME/.ssh/id_ed25519" "$HOME/.ssh/id_rsa"; do
    if [[ -f "$cand" ]]; then
      HEXSTRIKE_VPS_KEY="$cand"
      log "using key: $HEXSTRIKE_VPS_KEY"
      return 0
    fi
  done
  die "no SSH private key (expected ~/.ssh/hexstrike_vps or ~/.ssh/id_ed25519)"
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
  if remote "test -x '$DIR/scripts/vps-start-server.sh'"; then
    log "START_SCRIPT_OK"
  else
    log "START_SCRIPT_MISSING — run: bash scripts/vps-from-mac.sh start  (will clone into $VPS_INSTALL)"
  fi
}

cmd_install_key() {
  resolve_key
  local pub="${HEXSTRIKE_VPS_KEY}.pub"
  [[ -f "$pub" ]] || die "public key missing: $pub (generate: ssh-keygen -t ed25519 -f $HEXSTRIKE_VPS_KEY -N '')"
  log "installing $pub → $VPS_TARGET"
  if command -v ssh-copy-id >/dev/null 2>&1; then
    # Always pass -i: bare ssh-copy-id fails with "No identities found"
    ssh-copy-id -i "$pub" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new "$VPS_TARGET"
  else
    # Portable fallback (password prompt once if key not yet authorized)
    local line
    line="$(tr -d '\n' <"$pub")"
    ssh -o StrictHostKeyChecking=accept-new "$VPS_TARGET" \
      "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && grep -qxF '$line' ~/.ssh/authorized_keys || echo '$line' >> ~/.ssh/authorized_keys && echo KEY_INSTALLED"
  fi
  log "verifying key login..."
  remote 'echo KEY_LOGIN_OK; whoami'
}

ensure_remote_repo() {
  # Clone into VPS_INSTALL if start script is missing (fixes START_SCRIPT_MISSING)
  remote bash -s <<EOF
set -euo pipefail
INSTALL='$VPS_INSTALL'
FALLBACK='$VPS_INSTALL_FALLBACK'
REPO='$REPO_URL'
BRANCH='$REPO_BRANCH'

pick_dir() {
  for d in "\$INSTALL" "\$FALLBACK"; do
    if [[ -x "\$d/scripts/vps-start-server.sh" ]]; then
      echo "\$d"
      return 0
    fi
  done
  return 1
}

if DIR="\$(pick_dir)"; then
  echo "\$DIR"
  exit 0
fi

command -v git >/dev/null || { apt-get update -qq && apt-get install -y -qq git; }
mkdir -p "\$(dirname "\$INSTALL")"
if [[ -d "\$INSTALL/.git" ]]; then
  git -C "\$INSTALL" fetch origin
  git -C "\$INSTALL" checkout "\$BRANCH" 2>/dev/null || true
  git -C "\$INSTALL" pull --ff-only origin "\$BRANCH" || true
else
  rm -rf "\$INSTALL"
  git clone --branch "\$BRANCH" "\$REPO" "\$INSTALL"
fi
chmod +x "\$INSTALL"/scripts/*.sh 2>/dev/null || true
test -x "\$INSTALL/scripts/vps-start-server.sh" || { echo "clone incomplete: missing vps-start-server.sh" >&2; exit 1; }
echo "\$INSTALL"
EOF
}

cmd_start() {
  log "ensuring repo on $VPS_TARGET..."
  DIR="$(ensure_remote_repo | tail -1)"
  [[ -n "$DIR" ]] || die "could not resolve remote install dir"
  log "starting hexstrike on $VPS_TARGET ($DIR)"
  remote bash -s <<EOF
set -euo pipefail
cd '$DIR'
git config --global --add safe.directory '$DIR' 2>/dev/null || true
if [[ -d .git ]]; then
  git fetch origin '$REPO_BRANCH' 2>/dev/null || true
  git pull --ff-only origin '$REPO_BRANCH' 2>/dev/null || echo '[vps-mac] WARN: git pull failed — continuing'
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
  install-key)  cmd_install_key ;;
  start)        cmd_start ;;
  status)       cmd_status ;;
  shell)        cmd_shell "$@" ;;
  tunnel)       cmd_tunnel ;;
  tunnel-stop)  cmd_tunnel_stop ;;
  allow-cloud)  cmd_allow_cloud "$@" ;;
  repair|fix-all)
    die "no '$CMD' command — use: install-key → check → start → status (see --help)"
    ;;
  *)            die "unknown command: $CMD (try --help)" ;;
esac
