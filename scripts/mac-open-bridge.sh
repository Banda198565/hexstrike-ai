#!/usr/bin/env bash
# Run on iMac — opens reverse SSH tunnel + cloud key on VPS.
#   cd ~/hexstrike-ai && bash scripts/mac-open-bridge.sh
set -euo pipefail

VPS="${HEXSTRIKE_VPS:-root@78.27.235.70}"
PORT="${MAC_TUNNEL_PORT:-2222}"
PUB='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEOPiUzUcLD21HFkNE4HqpIHa2Ri3D5q5LdR9T6KTfr/ hexstrike-mac-bridge'
KEY="${HEXSTRIKE_VPS_KEY:-$HOME/.ssh/hexstrike_vps}"

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new)
[[ -f "$KEY" ]] && SSH+=(-i "$KEY" -o IdentitiesOnly=yes)

echo "[1] Remote Login..."
if ! systemsetup -getremotelogin 2>/dev/null | grep -qi "On"; then
  echo "  Turn ON: System Settings → Sharing → Remote Login"
fi

echo "[2] Cloud pubkey on VPS..."
"${SSH[@]}" "$VPS" "bash -s" <<EOF
set -euo pipefail
mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
grep -qxF '$PUB' ~/.ssh/authorized_keys || echo '$PUB' >> ~/.ssh/authorized_keys
echo VPS_KEY_OK
EOF

echo "[3] Reverse tunnel :${PORT} → this Mac..."
pkill -f "127.0.0.1:${PORT}:localhost:22" 2>/dev/null || true
nohup "${SSH[@]}" -N -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes \
  -R "127.0.0.1:${PORT}:localhost:22" "$VPS" >> /tmp/hexstrike-mac-tunnel.log 2>&1 &
sleep 2
if pgrep -f "127.0.0.1:${PORT}:localhost:22" >/dev/null; then
  echo "TUNNEL_OK (log: /tmp/hexstrike-mac-tunnel.log)"
else
  echo "TUNNEL_FAIL — see /tmp/hexstrike-mac-tunnel.log"
  tail -5 /tmp/hexstrike-mac-tunnel.log || true
  exit 1
fi

echo "[4] Zed settings..."
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -x "$ROOT/scripts/fix-zed-deepseek-settings.sh" ]] && [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  bash "$ROOT/scripts/fix-zed-deepseek-settings.sh" "$DEEPSEEK_API_KEY"
elif [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  curl -fsSL "https://raw.githubusercontent.com/Banda198565/hexstrike-ai/cursor/r1-deepseek-standalone-7b69/scripts/fix-zed-deepseek-settings.sh" \
    | DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" bash -s "$DEEPSEEK_API_KEY"
fi

cat << EOF

=== Bridge open — tell cloud agent: retry ===
MAC_SSH_JUMP=${VPS}
MAC_SSH=$(whoami)@127.0.0.1
MAC_SSH_PORT=${PORT}
EOF
