#!/bin/bash
# install-agent.sh — install HexStrike agent globally or to local bin

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "🔧 Installing HexStrike Agent..."
echo ""

# Build
cd "$PROJECT_ROOT/cmd/agent"
bash build.sh

AGENT_BIN="$PROJECT_ROOT/bin/hexstrike-agent"

# Option to install globally
if [[ "${1:-}" == "global" ]]; then
  echo ""
  echo "[*] Installing to /usr/local/bin..."
  sudo cp "$AGENT_BIN" /usr/local/bin/
  echo "[✓] Installed globally: hexstrike-agent"
else
  echo ""
  echo "[✓] Installed locally: $AGENT_BIN"
  echo ""
  echo "To add to PATH, run:"
  echo "  export PATH=\"\$PATH:$PROJECT_ROOT/bin\""
  echo ""
  echo "Or install globally:"
  echo "  bash $SCRIPT_DIR/install-agent.sh global"
fi
