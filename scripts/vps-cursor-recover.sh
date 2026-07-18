#!/usr/bin/env bash
# SINGLE-COMMAND Cursor↔VPS recovery (run on YOUR Mac / operator host).
#
#   bash scripts/vps-cursor-recover.sh
#   bash scripts/vps-cursor-recover.sh root@78.27.235.70
#   EXTRA_IPS="52.34.217.149" bash scripts/vps-cursor-recover.sh
#
# What it does:
#   1. SSH with operator key
#   2. Allowlist current Cursor cloud egress IPs + EXTRA_IPS
#   3. Install cloud-agent pubkeys into authorized_keys
#   4. Install/enable critical watchdog timer (crypto_bot + SOCKS5:1337)
#   5. Print status for the cloud agent to retry
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-root@78.27.235.70}"

# Prefer dedicated key, then id_ed25519 (path from task context)
if [[ -z "${HEXSTRIKE_VPS_KEY:-}" ]]; then
  for cand in "$HOME/.ssh/hexstrike_vps" "$HOME/.ssh/id_ed25519" /root/.ssh/id_ed25519; do
    if [[ -f "$cand" ]]; then
      export HEXSTRIKE_VPS_KEY="$cand"
      break
    fi
  done
fi

echo "[recover] operator key: ${HEXSTRIKE_VPS_KEY:-<default agent>}"
echo "[recover] target: $TARGET"
echo "[recover] EXTRA_IPS: ${EXTRA_IPS:-<none>}"

exec bash "$ROOT/scripts/vps-open-for-cloud-agent.sh" "$TARGET"
