#!/bin/bash
# Standalone: apply HexStrike Soft theme without local git repo.
# Usage on Mac:
#   curl -fsSL https://raw.githubusercontent.com/Banda198565/hexstrike-ai/cursor/mcp-blockchain-layer-a1cf/scripts/install-terminal-theme.sh | bash
set -euo pipefail

PROFILE_NAME="HexStrike Soft"
BASE="${HEX_THEME_DIR:-$HOME/.hexstrike/terminal-themes}"
THEME="$BASE/HexStrike-Soft.terminal"
RAW="https://raw.githubusercontent.com/Banda198565/hexstrike-ai/cursor/mcp-blockchain-layer-a1cf/scripts/terminal-themes/HexStrike-Soft.terminal"
ZSHRC="${ZSHRC:-$HOME/.zshrc}"
MARKER="# hexstrike-soft-terminal"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS Terminal.app only."
  exit 1
fi

mkdir -p "$BASE"
echo "→ Download theme to $THEME"
curl -fsSL -o "$THEME" "$RAW"

echo "→ Import + set default"
open "$THEME"
sleep 1.5

osascript <<APPLESCRIPT || true
tell application "Terminal"
    try
        set default settings to settings set "$PROFILE_NAME"
        repeat with w in windows
            set current settings of w to settings set "$PROFILE_NAME"
        end repeat
    end try
end tell
APPLESCRIPT

if [[ -f "$ZSHRC" ]] && grep -q "$MARKER" "$ZSHRC"; then
  echo "→ ~/.zshrc already has soft prompt"
else
  cat >>"$ZSHRC" <<'ZSH'

# hexstrike-soft-terminal — light blue prompt
export PS1='%F{117}(%~)%f %# '
ZSH
  echo "→ Added soft prompt to $ZSHRC"
fi

echo ""
echo "Done. Open new tab: ⌘N  (or: source ~/.zshrc)"
echo "Manual fallback: Terminal → Settings → Profiles → HexStrike Soft → Default"
