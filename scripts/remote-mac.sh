#!/usr/bin/env bash
# Cloud agent → Mac over SSH. Requires config/mac-bridge.env (see mac-bridge.example.env).
#
#   bash scripts/remote-mac.sh status
#   bash scripts/remote-mac.sh fix
#   bash scripts/remote-mac.sh restart
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${MAC_BRIDGE_ENV:-${ROOT}/config/mac-bridge.env}"

if [[ -f "$ENV_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$ENV_FILE"
fi

CMD="${1:-status}"
MAC_SSH="${MAC_SSH:-}"
MAC_SSH_KEY="${MAC_SSH_KEY:-}"
REPO_ON_MAC="${MAC_HEXSTRIKE_PATH:-~/hexstrike-ai}"

if [[ -z "$MAC_SSH" ]]; then
  cat << EOF
MAC_SSH not set. One-time setup on iMac:

1) System Settings → General → Sharing → Remote Login ON
2) Add cloud agent public key to ~/.ssh/authorized_keys on Mac:
   $(cat "${ROOT}/config/mac-bridge-cloud.pub" 2>/dev/null || echo '  (run: bash scripts/setup-mac-bridge.sh)')

3) Create ${ROOT}/config/mac-bridge.env:
   MAC_SSH=mufasaai@YOUR_MAC_IP
   MAC_SSH_KEY=~/.ssh/hexstrike_mac_bridge
   DEEPSEEK_API_KEY=sk-...

Optional (Mac behind NAT): on iMac run reverse tunnel:
   bash scripts/mac-reverse-tunnel.sh

Then retry: bash scripts/remote-mac.sh ${CMD}
EOF
  exit 1
fi

SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new)
if [[ -n "${MAC_SSH_KEY:-}" ]]; then
  SSH+=(-i "$MAC_SSH_KEY" -o IdentitiesOnly=yes)
fi
if [[ -n "${MAC_SSH_JUMP:-}" ]]; then
  SSH+=(-J "$MAC_SSH_JUMP")
fi
if [[ -n "${MAC_SSH_PORT:-}" ]]; then
  SSH+=(-p "$MAC_SSH_PORT")
fi

REMOTE="cd ${REPO_ON_MAC} && bash scripts/mac-zed-bridge.sh"

case "$CMD" in
  status)
    "${SSH[@]}" "$MAC_SSH" "${REMOTE} status"
    ;;
  fix)
    [[ -n "${DEEPSEEK_API_KEY:-}" ]] || { echo "Set DEEPSEEK_API_KEY in mac-bridge.env" >&2; exit 1; }
    "${SSH[@]}" "$MAC_SSH" "DEEPSEEK_API_KEY='${DEEPSEEK_API_KEY}' ${REMOTE} fix"
    ;;
  restart)
    "${SSH[@]}" "$MAC_SSH" "${REMOTE} restart"
    ;;
  *)
    echo "Usage: remote-mac.sh {status|fix|restart}" >&2
    exit 1
    ;;
esac
