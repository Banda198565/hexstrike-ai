#!/usr/bin/env bash
# Shared HexStrike VPS connection defaults (source from other scripts).
#
# Real production target — do NOT derive VPS IP from ifconfig.io / ifconfig.me
# (those return the *client* egress IP, not the server).
#
# Override via env when needed:
#   VPS_HOST  VPS_USER  HEXSTRIKE_VPS_KEY  VPS_INSTALL  SOCKS_PORT
#
# shellcheck disable=SC2034

# Canonical HexStrike VPS (MiroHost)
VPS_HOST="${VPS_HOST:-78.27.235.70}"
VPS_USER="${VPS_USER:-root}"
VPS_TARGET="${VPS_TARGET:-${VPS_USER}@${VPS_HOST}}"

# Operator key on Mac / cloud agent (private key never committed)
HEXSTRIKE_VPS_KEY="${HEXSTRIKE_VPS_KEY:-${VPS_SSH_KEY:-$HOME/.ssh/hexstrike_vps}}"

# Install tree on the server (primary; bootstrap may also use /root/hexstrike-ai)
VPS_INSTALL="${VPS_INSTALL:-${HEXSTRIKE_DIR:-/opt/hexstrike-ai}}"
VPS_INSTALL_FALLBACK="${VPS_INSTALL_FALLBACK:-/root/hexstrike-ai}"

# Local SOCKS bind — localhost only (never 0.0.0.0)
SOCKS_BIND="${SOCKS_BIND:-127.0.0.1}"
SOCKS_PORT="${SOCKS_PORT:-1337}"

# Known Cursor cloud egress IPs (refresh with EXTRA_CLOUD_IPS=x.x.x.x)
CLOUD_EGRESS_IPS_DEFAULT=(
  "52.40.48.127"
  "44.236.205.197"
  "52.13.17.46"
  "54.201.20.43"
  "44.233.218.155"
)
