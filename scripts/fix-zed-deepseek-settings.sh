#!/usr/bin/env bash
# Fix Zed settings.json for DeepSeek (macOS). Run on your Mac, not in cloud VM.
#
# Usage:
#   export DEEPSEEK_API_KEY=sk-...
#   bash scripts/fix-zed-deepseek-settings.sh
#
# Or:
#   bash scripts/fix-zed-deepseek-settings.sh sk-...
set -euo pipefail

KEY="${DEEPSEEK_API_KEY:-${1:-}}"
if [[ -z "$KEY" ]]; then
  echo "Usage: DEEPSEEK_API_KEY=sk-... $0"
  echo "   or: $0 sk-..."
  exit 1
fi

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This script targets macOS Zed path."
  exit 1
fi

DIR="${HOME}/Library/Application Support/Zed"
FILE="${DIR}/settings.json"
ALT_DIR="${HOME}/.config/zed"
ALT_FILE="${ALT_DIR}/settings.json"
mkdir -p "$DIR" "$ALT_DIR"

python3 - "$FILE" "$ALT_FILE" "$KEY" << 'PY'
import json
import sys
from pathlib import Path

paths = [Path(sys.argv[1]), Path(sys.argv[2])]
api_key = sys.argv[3]

cfg = {
    "agent": {
        "default_model": {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "enable_thinking": True,
            "effort": "high",
        },
        "favorite_models": [],
        "model_parameters": [],
    },
    "language_models": {
        "providers": {
            "deepseek": {
                "api_key": api_key,
            }
        }
    },
    "ui_font_size": 16,
    "buffer_font_size": 15,
    "theme": {
        "mode": "system",
        "light": "One Light",
        "dark": "One Dark",
    },
}

text = json.dumps(cfg, indent=2) + "\n"
json.loads(text)
for path in paths:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"OK: wrote {path} ({path.stat().st_size} bytes)")
PY

echo "Restarting Zed..."
killall zed 2>/dev/null || true
sleep 2
open -a Zed 2>/dev/null || echo "Open Zed manually (Cmd+Shift+A → New Thread)"
