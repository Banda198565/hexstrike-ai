#!/usr/bin/env bash
# vps-ollama-install.sh — install & configure Ollama on AlmaLinux/RHEL/Ubuntu VPS
#
# Modes (mutually exclusive):
#   --localhost   (default, safest) — bind 127.0.0.1:11434, expose via SSH tunnel only
#   --exposed     — bind 0.0.0.0:11434 (⚠️ requires firewall allowlist)
#   --check       — status probe only
#
# Options:
#   --model deepseek-r1:1.5b   Pull model after install (default deepseek-r1:1.5b)
#   --no-model                 Skip model pull
#   --allow-ip a.b.c.d[,e.f.g.h]  IPs allowed to reach 11434 in exposed mode (firewalld/ufw)
#   --systemd                  Install systemd unit and enable on boot
#
# Usage:
#   sudo bash scripts/vps-ollama-install.sh --localhost --systemd
#   sudo bash scripts/vps-ollama-install.sh --exposed --allow-ip <MAC_PUBLIC_IP> --systemd
#   bash scripts/vps-ollama-install.sh --check
set -euo pipefail

MODE="localhost"
MODEL="deepseek-r1:1.5b"
NO_MODEL=0
ALLOW_IP=""
INSTALL_SYSTEMD=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --localhost) MODE="localhost"; shift ;;
    --exposed) MODE="exposed"; shift ;;
    --check) MODE="check"; shift ;;
    --model|--model=*) [[ "$1" == *=* ]] && MODEL="${1#*=}" || { MODEL="$2"; shift; }; shift ;;
    --no-model) NO_MODEL=1; shift ;;
    --allow-ip|--allow-ip=*) [[ "$1" == *=* ]] && ALLOW_IP="${1#*=}" || { ALLOW_IP="$2"; shift; }; shift ;;
    --systemd) INSTALL_SYSTEMD=1; shift ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown: $1" >&2; exit 1 ;;
  esac
done

log() { echo "[vps-ollama] $*"; }
die() { echo "[vps-ollama] FAIL: $*" >&2; exit 1; }
warn() { echo "[vps-ollama] WARN: $*"; }

# Detect installer + require root for install
PKG=""
if command -v dnf >/dev/null 2>&1; then PKG=dnf
elif command -v yum >/dev/null 2>&1; then PKG=yum
elif command -v apt-get >/dev/null 2>&1; then PKG=apt
fi

if [[ "$MODE" != "check" && $(id -u) -ne 0 ]]; then
  die "run as root: sudo bash scripts/vps-ollama-install.sh --${MODE}"
fi

# --- CHECK MODE ---
if [[ "$MODE" == "check" ]]; then
  echo "════════════════════════════════════════════════════════"
  echo " Ollama VPS status check"
  echo "════════════════════════════════════════════════════════"
  if command -v ollama >/dev/null; then
    echo "  binary: $(command -v ollama)  version: $(ollama --version 2>/dev/null || echo unknown)"
  else
    echo "  binary: NOT INSTALLED"
  fi

  if systemctl is-active --quiet ollama 2>/dev/null; then
    echo "  systemd: active"
  else
    echo "  systemd: inactive"
  fi

  BIND=$(ss -tlnp 2>/dev/null | grep 11434 || true)
  if [[ -n "$BIND" ]]; then
    echo "  listen:  $BIND"
    if echo "$BIND" | grep -qE '0\.0\.0\.0:11434|\*:11434'; then
      echo "  ⚠️  bound to 0.0.0.0 — verify firewall allowlist"
    else
      echo "  ✅ localhost-only bind"
    fi
  else
    echo "  listen:  not bound"
  fi

  if curl -sf --max-time 3 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    echo "  api:     $(curl -sf http://127.0.0.1:11434/api/version)"
  else
    echo "  api:     unreachable on localhost"
  fi
  exit 0
fi

# --- INSTALL ---
if ! command -v ollama >/dev/null; then
  log "Installing Ollama via official installer"
  curl -fsSL https://ollama.com/install.sh | sh || die "ollama install failed"
else
  log "Ollama already installed: $(ollama --version 2>/dev/null || echo unknown)"
fi

id ollama >/dev/null 2>&1 || useradd -r -s /bin/false -d /var/lib/ollama ollama 2>/dev/null || true
mkdir -p /var/lib/ollama /var/log/ollama /etc/systemd/system/ollama.service.d
chown -R ollama:ollama /var/lib/ollama /var/log/ollama 2>/dev/null || true

# --- BIND CONFIG ---
BIND_HOST="127.0.0.1"
if [[ "$MODE" == "exposed" ]]; then
  BIND_HOST="0.0.0.0"
  warn "MODE=exposed — Ollama will bind 0.0.0.0:11434 (no built-in auth)"
  warn "You MUST firewall this port. Only ${ALLOW_IP:-<no --allow-ip>} will be allowed."
fi

cat >/etc/systemd/system/ollama.service.d/override.conf <<EOF
[Service]
Environment="OLLAMA_HOST=${BIND_HOST}:11434"
Environment="OLLAMA_ORIGINS=*"
EOF

# --- FIREWALL (exposed only) ---
if [[ "$MODE" == "exposed" ]]; then
  [[ -n "$ALLOW_IP" ]] || die "--exposed requires --allow-ip <Mac_public_ip>"
  IFS=',' read -r -a IPS <<< "$ALLOW_IP"

  if command -v firewall-cmd >/dev/null 2>&1 && systemctl is-active --quiet firewalld 2>/dev/null; then
    log "Configuring firewalld rich rules for 11434"
    # First drop any existing rule for 11434
    firewall-cmd --permanent --remove-port=11434/tcp 2>/dev/null || true
    for ip in "${IPS[@]}"; do
      log "  allow $ip → 11434"
      firewall-cmd --permanent --add-rich-rule="rule family=ipv4 source address=${ip} port protocol=tcp port=11434 accept" || true
    done
    firewall-cmd --permanent --add-rich-rule='rule family=ipv4 port protocol=tcp port=11434 reject' || true
    firewall-cmd --reload
    log "firewalld rules applied"
  elif command -v ufw >/dev/null 2>&1; then
    log "Configuring ufw"
    ufw delete allow 11434/tcp 2>/dev/null || true
    for ip in "${IPS[@]}"; do
      ufw allow from "$ip" to any port 11434 proto tcp
    done
    ufw deny 11434/tcp
    ufw reload 2>/dev/null || true
  else
    warn "No firewalld/ufw — install one or set iptables manually before enabling ollama"
  fi
fi

# --- SYSTEMD ---
if [[ ! -f /etc/systemd/system/ollama.service ]]; then
  log "Creating /etc/systemd/system/ollama.service"
  cat >/etc/systemd/system/ollama.service <<'UNIT'
[Unit]
Description=Ollama LLM server
After=network-online.target

[Service]
ExecStart=/usr/local/bin/ollama serve
User=ollama
Group=ollama
Restart=on-failure
RestartSec=3
StandardOutput=append:/var/log/ollama/serve.log
StandardError=append:/var/log/ollama/serve.log

[Install]
WantedBy=multi-user.target
UNIT
fi

systemctl daemon-reload
if [[ "$INSTALL_SYSTEMD" -eq 1 || "$MODE" == "exposed" ]]; then
  log "Enable + start ollama.service"
  systemctl enable --now ollama.service
else
  log "Restart ollama.service (foreground start avoided)"
  systemctl restart ollama.service || systemctl start ollama.service || true
fi

# --- WAIT ---
for i in $(seq 1 30); do
  if curl -sf --max-time 2 http://127.0.0.1:11434/api/version >/dev/null 2>&1; then
    log "Ollama API ready on 127.0.0.1:11434"
    break
  fi
  sleep 1
done

# --- MODEL PULL ---
if [[ "$NO_MODEL" -eq 0 && -n "$MODEL" ]]; then
  log "Pulling model $MODEL (may take minutes)"
  su -s /bin/bash ollama -c "ollama pull $MODEL" || \
    (log "pull as ollama failed, retry as root"; ollama pull "$MODEL") || \
    warn "model pull failed — try manually: ollama pull $MODEL"
fi

# --- REPORT ---
echo ""
echo "════════════════════════════════════════════════════════"
echo " Ollama VPS — DONE"
echo "════════════════════════════════════════════════════════"
echo "  mode:    $MODE"
echo "  bind:    ${BIND_HOST}:11434"
echo "  model:   $([[ $NO_MODEL -eq 1 ]] && echo skipped || echo $MODEL)"
echo "  status:  systemctl status ollama --no-pager"
echo "  logs:    tail -f /var/log/ollama/serve.log"
echo ""
if [[ "$MODE" == "localhost" ]]; then
  echo "  📎 SAFE ACCESS FROM MAC (SSH tunnel):"
  echo "    ssh -N -L 11434:127.0.0.1:11434 root@\$VPS_HOST"
  echo "    curl http://127.0.0.1:11434/api/version"
  echo "    export OLLAMA_HOST=http://127.0.0.1:11434"
else
  echo "  ⚠️  EXPOSED ON PUBLIC IP — allowlist: ${ALLOW_IP:-none}"
  echo "    curl http://\$VPS_HOST:11434/api/version"
  echo "    export OLLAMA_HOST=http://\$VPS_HOST:11434"
  echo "    Better: switch to --localhost + SSH tunnel"
fi
echo "════════════════════════════════════════════════════════"
