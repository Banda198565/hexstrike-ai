#!/bin/bash
# Switch Mac Terminal from harsh green "matrix" to readable soft blue-gray.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
THEME="$ROOT/scripts/terminal-themes/HexStrike-Soft.terminal"
PROFILE_NAME="HexStrike Soft"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This theme is for macOS Terminal.app only."
  exit 1
fi

if [[ ! -f "$THEME" ]]; then
  echo "Theme file missing: $THEME"
  exit 1
fi

echo "Importing Terminal profile: $PROFILE_NAME"
open "$THEME"

cat <<MSG

Profile imported.

1) Terminal → Settings (⌘,) → Profiles
2) Select "$PROFILE_NAME"
3) Click "Default" (bottom of profile list)
4) Open a new tab/window (⌘N)

Text: soft blue-gray  |  Background: dark gray  |  Accents: muted (no neon green)

Optional — softer zsh prompt in ~/.zshrc:
  export PS1='%F{117}(%~)%f %# '

MSG
