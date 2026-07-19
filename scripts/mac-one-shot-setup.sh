#!/usr/bin/env bash
# ONE command on iMac — enables cloud agent to reach this Mac.
#
#   curl -fsSL 'https://raw.githubusercontent.com/Banda198565/hexstrike-ai/cursor/r1-deepseek-standalone-7b69/scripts/mac-one-shot-setup.sh' | \
#     DEEPSEEK_API_KEY='sk-...' bash
#
# Optional reverse tunnel (Mac behind NAT):
#   HEXSTRIKE_VPS=root@78.27.235.70 curl -fsSL '...' | DEEPSEEK_API_KEY='sk-...' bash
set -euo pipefail

REPO="${HEXSTRIKE_REPO:-$HOME/hexstrike-ai}"
PUB='ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEOPiUzUcLD21HFkNE4HqpIHa2Ri3D5q5LdR9T6KTfr/ hexstrike-mac-bridge'
KEY="${DEEPSEEK_API_KEY:-}"

[[ "$(uname -s)" == "Darwin" ]] || { echo "Run on macOS iMac"; exit 1; }
[[ -n "$KEY" ]] || { echo "Set DEEPSEEK_API_KEY=sk-..."; exit 1; }

echo "[1/5] SSH authorized_keys..."
mkdir -p ~/.ssh && chmod 700 ~/.ssh
touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys
grep -qxF "$PUB" ~/.ssh/authorized_keys || echo "$PUB" >> ~/.ssh/authorized_keys

echo "[2/5] Remote Login hint..."
if ! systemsetup -getremotelogin 2>/dev/null | grep -qi "On"; then
  echo "  → Enable: System Settings → Sharing → Remote Login ON"
fi

echo "[3/5] Repo..."
if [[ -d "$REPO/.git" ]]; then
  git -C "$REPO" pull --ff-only 2>/dev/null || true
else
  git clone --depth 1 -b cursor/r1-deepseek-standalone-7b69 \
    https://github.com/Banda198565/hexstrike-ai.git "$REPO"
fi

echo "[4/5] Fix Zed settings..."
DEEPSEEK_API_KEY="$KEY" bash "$REPO/scripts/fix-zed-deepseek-settings.sh" "$KEY"

echo "[5/5] Network..."
IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo unknown)"
USER_NAME="$(whoami)"

if [[ -n "${HEXSTRIKE_VPS:-}" ]]; then
  echo "  Starting reverse tunnel to $HEXSTRIKE_VPS (background)..."
  nohup bash "$REPO/scripts/mac-reverse-tunnel.sh" > /tmp/hexstrike-mac-tunnel.log 2>&1 &
  echo "  Tunnel log: /tmp/hexstrike-mac-tunnel.log"
  cat << EOF

=== CLOUD CONFIG (via VPS) ===
MAC_SSH_JUMP=${HEXSTRIKE_VPS}
MAC_SSH=${USER_NAME}@127.0.0.1
MAC_SSH_PORT=2222
MAC_SSH_KEY=~/.ssh/hexstrike_mac_bridge
DEEPSEEK_API_KEY=${KEY}
EOF
else
  cat << EOF

=== CLOUD CONFIG (direct) ===
MAC_SSH=${USER_NAME}@${IP}
MAC_SSH_KEY=~/.ssh/hexstrike_mac_bridge
DEEPSEEK_API_KEY=${KEY}
EOF
fi

echo ""
bash "$REPO/scripts/mac-zed-bridge.sh" status
