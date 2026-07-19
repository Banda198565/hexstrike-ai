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
MAC_SSH_KEY="${MAC_SSH_KEY:-$HOME/.ssh/hexstrike_mac_bridge}"
MAC_SSH_JUMP="${MAC_SSH_JUMP:-}"
MAC_SSH_PORT="${MAC_SSH_PORT:-22}"
REPO_ON_MAC="${MAC_HEXSTRIKE_PATH:-~/hexstrike-ai}"

if [[ -z "$MAC_SSH" ]]; then
  cat << EOF
MAC_SSH not set. On iMac run:
  DEEPSEEK_API_KEY=sk-... bash scripts/mac-open-bridge.sh
EOF
  exit 1
fi

run_on_mac() {
  local remote_cmd="$1"
  if [[ -n "$MAC_SSH_JUMP" ]]; then
    [[ -f "$MAC_SSH_KEY" ]] || { echo "Missing key: $MAC_SSH_KEY" >&2; exit 1; }
    ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new \
      -i "$MAC_SSH_KEY" "$MAC_SSH_JUMP" "bash -s" <<EOF
set -euo pipefail
install -m 700 -d /root/.ssh
cat > /root/.ssh/hexstrike_mac_bridge << 'KEYEOF'
$(cat "$MAC_SSH_KEY")
KEYEOF
chmod 600 /root/.ssh/hexstrike_mac_bridge
ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 \
  -i /root/.ssh/hexstrike_mac_bridge -p ${MAC_SSH_PORT} ${MAC_SSH} $(printf '%q' "$remote_cmd")
EOF
  else
    ssh -o BatchMode=yes -o ConnectTimeout=15 -o StrictHostKeyChecking=accept-new \
      -i "$MAC_SSH_KEY" -o IdentitiesOnly=yes "$MAC_SSH" "$remote_cmd"
  fi
}

REMOTE="cd ${REPO_ON_MAC} && bash scripts/mac-zed-bridge.sh"

case "$CMD" in
  status) run_on_mac "${REMOTE} status" ;;
  fix)
    [[ -n "${DEEPSEEK_API_KEY:-}" ]] || { echo "Set DEEPSEEK_API_KEY in mac-bridge.env" >&2; exit 1; }
    run_on_mac "DEEPSEEK_API_KEY='${DEEPSEEK_API_KEY}' ${REMOTE} fix"
    ;;
  restart) run_on_mac "${REMOTE} restart" ;;
  *)
    echo "Usage: remote-mac.sh {status|fix|restart}" >&2
    exit 1
    ;;
esac
