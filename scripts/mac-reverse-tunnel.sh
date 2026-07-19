#!/usr/bin/env bash
# Run on iMac — reverse SSH tunnel so cloud agent reaches Mac via VPS jump.
#
#   export HEXSTRIKE_VPS=root@78.27.235.70
#   export MAC_TUNNEL_PORT=2222
#   bash scripts/mac-reverse-tunnel.sh
#
# Cloud then uses in mac-bridge.env:
#   MAC_SSH_JUMP=root@78.27.235.70
#   MAC_SSH=mufasaai@127.0.0.1
#   MAC_SSH_PORT=2222
set -euo pipefail

VPS="${HEXSTRIKE_VPS:-}"
PORT="${MAC_TUNNEL_PORT:-2222}"

[[ -n "$VPS" ]] || { echo "Set HEXSTRIKE_VPS=root@your-vps" >&2; exit 1; }

echo "Opening reverse tunnel: VPS:${PORT} -> this Mac:22"
echo "Keep this terminal open. Ctrl+C to stop."

exec ssh -N \
  -o ServerAliveInterval=30 \
  -o ExitOnForwardFailure=yes \
  -R "127.0.0.1:${PORT}:localhost:22" \
  "$VPS"
