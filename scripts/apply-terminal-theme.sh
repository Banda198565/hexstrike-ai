#!/bin/bash
# Apply HexStrike Soft: light blue-gray text instead of neon green (macOS Terminal).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
THEME="$ROOT/scripts/terminal-themes/HexStrike-Soft.terminal"
PROFILE_NAME="HexStrike Soft"
ZSHRC="${ZSHRC:-$HOME/.zshrc}"
MARKER="# hexstrike-soft-terminal"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "macOS only. Run this on your Mac (mufasaai), not on VPS/cloud."
  exit 1
fi

if [[ ! -f "$THEME" ]]; then
  echo "Theme missing: $THEME"
  exit 1
fi

echo "→ Import profile: $PROFILE_NAME"
open "$THEME"
sleep 1.5

echo "→ Set as default + repaint open windows"
osascript <<APPLESCRIPT || true
tell application "Terminal"
    try
        set default settings to settings set "$PROFILE_NAME"
        repeat with w in windows
            set current settings of w to settings set "$PROFILE_NAME"
        end repeat
    on error errMsg
        display notification "Open Terminal → Settings → Profiles → $PROFILE_NAME → Default" with title "HexStrike Soft"
    end try
end tell
APPLESCRIPT

# Softer prompt (light blue path) — idempotent
if [[ -f "$ZSHRC" ]] && grep -q "$MARKER" "$ZSHRC"; then
  echo "→ ~/.zshrc prompt already configured"
else
  cat >>"$ZSHRC" <<'ZSH'

# hexstrike-soft-terminal — light blue prompt, no neon green
export PS1='%F{117}(%~)%f %# '
ZSH
  echo "→ Added soft prompt to $ZSHRC (run: source ~/.zshrc)"
fi

cat <<MSG

Done. HexStrike Soft is active.

  Text:     light blue-gray (not green)
  Prompt:   soft blue (%~)
  New tab:  ⌘N — already uses new colors

If colors did not change: Terminal → Settings → Profiles → "$PROFILE_NAME" → Default → ⌘N

MSG
