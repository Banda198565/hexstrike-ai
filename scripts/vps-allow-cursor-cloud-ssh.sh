#!/usr/bin/env bash
# Allow Cursor cloud agent egress IPs through ufw/fail2ban/iptables (run ON VPS as root).
#
#   bash scripts/vps-allow-cursor-cloud-ssh.sh
#   EXTRA_IPS="1.2.3.4 5.6.7.8" bash scripts/vps-allow-cursor-cloud-ssh.sh
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo "run as root"; exit 1; }

# Refresh when agent still cannot SSH: from agent run `curl -4 -sS ifconfig.me`
# Cursor cloud egress rotates across AWS us-west-2 NAT — keep the working set.
IPS=(
  "52.40.48.127"
  "44.236.205.197"
  "52.13.17.46"
  "54.201.20.43"
  "44.239.176.212"
  "50.112.242.221"
  "52.34.217.149"
  "35.167.27.154"
)

# Optional runtime extras (space-separated)
if [[ -n "${EXTRA_IPS:-}" ]]; then
  # shellcheck disable=SC2206
  IPS+=(${EXTRA_IPS})
fi

allow_one() {
  local ip="$1"
  [[ "$ip" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "skip invalid ip: $ip"; return 0; }

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
  if command -v iptables >/dev/null 2>&1; then
    iptables -C INPUT -p tcp -s "$ip" --dport 22 -j ACCEPT 2>/dev/null \
      || iptables -I INPUT 1 -p tcp -s "$ip" --dport 22 -j ACCEPT
    echo "iptables ACCEPT $ip:22"
  fi
  if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state 2>/dev/null | grep -q running; then
    firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=${ip}/32 port port=22 protocol=tcp accept" || true
    firewall-cmd --reload || true
  fi
}

for ip in "${IPS[@]}"; do
  allow_one "$ip"
done

echo "DONE — ask cloud agent to retry SSH"
sshd -t 2>/dev/null && systemctl reload sshd 2>/dev/null || systemctl reload ssh 2>/dev/null || true
