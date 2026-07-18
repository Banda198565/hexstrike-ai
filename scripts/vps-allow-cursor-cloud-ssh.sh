#!/usr/bin/env bash
# Allow Cursor cloud agent egress IPs through ufw/fail2ban (run ON VPS as root).
#
#   bash scripts/vps-allow-cursor-cloud-ssh.sh
#   EXTRA_CLOUD_IPS="44.233.218.155,1.2.3.4" bash scripts/vps-allow-cursor-cloud-ssh.sh
#   bash scripts/vps-allow-cursor-cloud-ssh.sh 44.233.218.155
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/vps-defaults.sh
source "$SCRIPT_DIR/vps-defaults.sh"

[[ $(id -u) -eq 0 ]] || { echo "run as root"; exit 1; }

IPS=("${CLOUD_EGRESS_IPS_DEFAULT[@]}")

# Positional args = extra IPs
for arg in "$@"; do
  [[ "$arg" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "skip invalid: $arg"; continue; }
  IPS+=("$arg")
done

# EXTRA_CLOUD_IPS=ip1,ip2
if [[ -n "${EXTRA_CLOUD_IPS:-}" ]]; then
  IFS=',' read -r -a _extra <<<"$EXTRA_CLOUD_IPS"
  for ip in "${_extra[@]}"; do
    ip="${ip// /}"
    [[ -z "$ip" ]] && continue
    [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || continue
    IPS+=("$ip")
  done
fi

# Dedupe
declare -A SEEN=()
UNIQUE=()
for ip in "${IPS[@]}"; do
  [[ -n "${SEEN[$ip]:-}" ]] && continue
  SEEN[$ip]=1
  UNIQUE+=("$ip")
done
IPS=("${UNIQUE[@]}")

for ip in "${IPS[@]}"; do
  if command -v ufw >/dev/null 2>&1 && ufw status 2>/dev/null | grep -qi active; then
    ufw allow from "$ip" to any port 22 proto tcp comment "cursor-cloud-agent" || true
    echo "ufw allow $ip:22"
  fi
  if command -v fail2ban-client >/dev/null 2>&1; then
    fail2ban-client set sshd unbanip "$ip" 2>/dev/null || true
    fail2ban-client set ssh unbanip "$ip" 2>/dev/null || true
    echo "fail2ban unban $ip (if was banned)"
  fi
  if [[ -f /etc/hosts.allow ]]; then
    grep -q "sshd: $ip" /etc/hosts.allow 2>/dev/null || echo "sshd: $ip  # cursor-cloud" >>/etc/hosts.allow
  fi
done

if command -v iptables >/dev/null 2>&1; then
  for ip in "${IPS[@]}"; do
    iptables -C INPUT -p tcp -s "$ip" --dport 22 -j ACCEPT 2>/dev/null \
      || iptables -I INPUT 1 -p tcp -s "$ip" --dport 22 -j ACCEPT
    echo "iptables ACCEPT $ip:22"
  done
fi

echo "DONE — allowlisted: ${IPS[*]}"
echo "Cloud agent retry: ssh ${VPS_USER}@${VPS_HOST}"
sshd -t 2>/dev/null && systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || true
