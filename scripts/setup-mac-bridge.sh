#!/usr/bin/env bash
# One-time: generate SSH key for cloud→Mac and print Mac setup steps.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEY="${HEXSTRIKE_MAC_BRIDGE_KEY:-${HOME}/.ssh/hexstrike_mac_bridge}"
PUB="${ROOT}/config/mac-bridge-cloud.pub"

mkdir -p "${HOME}/.ssh" "${ROOT}/config"
chmod 700 "${HOME}/.ssh"

if [[ ! -f "$KEY" ]]; then
  ssh-keygen -t ed25519 -f "$KEY" -N "" -C "hexstrike-mac-bridge"
fi

cp "${KEY}.pub" "$PUB"

cat << EOF
=== Cloud agent key ready ===
Private: ${KEY}
Public:  ${PUB}

=== On iMac (once) ===

# 1. Remote Login ON (Sharing)

# 2. Add this pubkey to Mac ~/.ssh/authorized_keys:
$(cat "$PUB")

# 3. Clone repo (if needed):
# git clone https://github.com/Banda198565/hexstrike-ai.git ~/hexstrike-ai

# 4. Test from Mac:
# bash ~/hexstrike-ai/scripts/mac-zed-bridge.sh status

# 5. Create cloud config (in repo, gitignored):
# cp config/mac-bridge.example.env config/mac-bridge.env
# Edit MAC_SSH=mufasaai@<mac-ip-or-tailscale-ip>
# Edit DEEPSEEK_API_KEY=sk-...

# If Mac has no public IP — on iMac keep tunnel open:
# bash ~/hexstrike-ai/scripts/mac-reverse-tunnel.sh

=== Then cloud agent runs ===
MAC_BRIDGE_ENV=config/mac-bridge.env bash scripts/remote-mac.sh status
EOF
