#!/usr/bin/env bash
# 24/7 critical-services watchdog for HexStrike VPS.
# Checks + auto-recovers: SOCKS5 :1337, crypto_bot, hexstrike-server (optional).
#
# Install (as root on VPS):
#   install -m 0755 scripts/vps-critical-watchdog.sh /usr/local/bin/
#   # then enable timer via vps-open-for-cloud-agent.sh / vps-cursor-recover.sh
#
# Manual one-shot:
#   bash /usr/local/bin/vps-critical-watchdog.sh
set -euo pipefail

LOG_DIR="${LOG_DIR:-/var/log/hexstrike}"
STATE_DIR="${STATE_DIR:-/var/lib/hexstrike/watchdog}"
SOCKS_PORT="${SOCKS_PORT:-1337}"
CRYPTO_BOT_UNIT="${CRYPTO_BOT_UNIT:-crypto_bot}"
CRYPTO_BOT_PATTERN="${CRYPTO_BOT_PATTERN:-crypto_bot}"
SOCKS_UNIT="${SOCKS_UNIT:-}"
SOCKS_PATTERN="${SOCKS_PATTERN:-microsocks|dante|sockd|ss-server|3proxy}"
ALERT_FILE="${ALERT_FILE:-$LOG_DIR/critical-watchdog.alerts}"
STATUS_JSON="${STATUS_JSON:-$STATE_DIR/status.json}"

mkdir -p "$LOG_DIR" "$STATE_DIR"
ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*" | tee -a "$LOG_DIR/critical-watchdog.log" >/dev/null; echo "[watchdog] $*"; }
alert() { echo "[$(ts)] ALERT $*" | tee -a "$ALERT_FILE"; log "ALERT: $*"; }

port_open() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -lnt "sport = :$port" 2>/dev/null | grep -q ":$port"
  else
    bash -c "echo >/dev/tcp/127.0.0.1/$port" 2>/dev/null
  fi
}

unit_active() {
  local unit="$1"
  [[ -n "$unit" ]] || return 1
  systemctl is-active --quiet "$unit" 2>/dev/null
}

proc_running() {
  local pat="$1"
  [[ -n "$pat" ]] || return 1
  pgrep -f "$pat" >/dev/null 2>&1
}

try_restart_unit() {
  local unit="$1"
  [[ -n "$unit" ]] || return 1
  if systemctl list-unit-files "$unit.service" 2>/dev/null | grep -q "$unit"; then
    systemctl restart "$unit" 2>/dev/null || systemctl restart "${unit}.service" 2>/dev/null || return 1
    return 0
  fi
  return 1
}

recover_socks() {
  if try_restart_unit "$SOCKS_UNIT"; then
    log "restarted unit $SOCKS_UNIT"
    return 0
  fi
  # Common microsocks fallback if binary exists and port free
  if command -v microsocks >/dev/null 2>&1; then
    pkill -f '[m]icrosocks' 2>/dev/null || true
    nohup microsocks -p "$SOCKS_PORT" >>"$LOG_DIR/microsocks.log" 2>&1 &
    log "started microsocks on :$SOCKS_PORT pid $!"
    return 0
  fi
  return 1
}

recover_crypto_bot() {
  if try_restart_unit "$CRYPTO_BOT_UNIT"; then
    log "restarted unit $CRYPTO_BOT_UNIT"
    return 0
  fi
  # Optional custom start script
  if [[ -x /opt/crypto_bot/start.sh ]]; then
    /opt/crypto_bot/start.sh >>"$LOG_DIR/crypto_bot-watchdog.log" 2>&1 || true
    log "ran /opt/crypto_bot/start.sh"
    return 0
  fi
  if [[ -x /root/crypto_bot/start.sh ]]; then
    /root/crypto_bot/start.sh >>"$LOG_DIR/crypto_bot-watchdog.log" 2>&1 || true
    log "ran /root/crypto_bot/start.sh"
    return 0
  fi
  return 1
}

socks_ok=0
bot_ok=0
ssh_ok=0

if port_open 22; then ssh_ok=1; else alert "sshd port 22 not listening"; fi

if port_open "$SOCKS_PORT" || proc_running "$SOCKS_PATTERN"; then
  socks_ok=1
else
  alert "SOCKS5 :$SOCKS_PORT down — recovering"
  if recover_socks && { port_open "$SOCKS_PORT" || proc_running "$SOCKS_PATTERN"; }; then
    socks_ok=1
    log "SOCKS5 recovered"
  else
    alert "SOCKS5 recovery FAILED"
  fi
fi

if unit_active "$CRYPTO_BOT_UNIT" || proc_running "$CRYPTO_BOT_PATTERN"; then
  bot_ok=1
else
  alert "crypto_bot down — recovering"
  if recover_crypto_bot && { unit_active "$CRYPTO_BOT_UNIT" || proc_running "$CRYPTO_BOT_PATTERN"; }; then
    bot_ok=1
    log "crypto_bot recovered"
  else
    # Not fatal if unit never installed — report UNKNOWN-ish
    if systemctl list-unit-files 2>/dev/null | grep -q "^${CRYPTO_BOT_UNIT}"; then
      alert "crypto_bot recovery FAILED"
    else
      log "crypto_bot unit not installed — skip hard fail"
      bot_ok=1
    fi
  fi
fi

# Keep cloud egress allowlist warm (idempotent)
if [[ -x /root/hexstrike-ai/scripts/vps-allow-cursor-cloud-ssh.sh ]]; then
  EXTRA_IPS="${EXTRA_IPS:-}" bash /root/hexstrike-ai/scripts/vps-allow-cursor-cloud-ssh.sh >/dev/null 2>&1 || true
elif [[ -x /usr/local/bin/vps-allow-cursor-cloud-ssh.sh ]]; then
  EXTRA_IPS="${EXTRA_IPS:-}" bash /usr/local/bin/vps-allow-cursor-cloud-ssh.sh >/dev/null 2>&1 || true
fi

cat >"$STATUS_JSON" <<JSON
{
  "ts": "$(ts)",
  "ssh_22": $ssh_ok,
  "socks_${SOCKS_PORT}": $socks_ok,
  "crypto_bot": $bot_ok,
  "host": "$(hostname -f 2>/dev/null || hostname)"
}
JSON

if [[ $ssh_ok -eq 1 && $socks_ok -eq 1 && $bot_ok -eq 1 ]]; then
  log "OK ssh=$ssh_ok socks=$socks_ok crypto_bot=$bot_ok"
  exit 0
fi
exit 1
