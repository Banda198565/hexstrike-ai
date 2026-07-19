#!/usr/bin/env bash
# Fix Zed + DeepSeek on macOS. Keys go to env/keychain — NOT settings.json (Zed docs).
set -euo pipefail

KEY="${DEEPSEEK_API_KEY:-${1:-}}"
if [[ -z "$KEY" ]]; then
  echo "Usage: DEEPSEEK_API_KEY=sk-... $0"
  exit 1
fi

[[ "$(uname -s)" == "Darwin" ]] || { echo "macOS only"; exit 1; }

DIR="${HOME}/Library/Application Support/Zed"
FILE="${DIR}/settings.json"
ALT_DIR="${HOME}/.config/zed"
ALT_FILE="${ALT_DIR}/settings.json"
ENV_FILE="${ALT_DIR}/env"
mkdir -p "$DIR" "$ALT_DIR"

python3 - "$FILE" "$ALT_FILE" "$ENV_FILE" << 'PY'
import json, sys
from pathlib import Path

paths = [Path(sys.argv[1]), Path(sys.argv[2])]
env_path = Path(sys.argv[3])

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
        "deepseek": {
            "api_url": "https://api.deepseek.com/v1",
            "available_models": [
                {
                    "name": "deepseek-v4-flash",
                    "display_name": "DeepSeek V4 Flash",
                    "max_tokens": 1000000,
                    "max_output_tokens": 384000,
                },
                {
                    "name": "deepseek-v4-pro",
                    "display_name": "DeepSeek V4 Pro",
                    "max_tokens": 1000000,
                    "max_output_tokens": 384000,
                },
            ],
        }
    },
    "ui_font_size": 16,
    "buffer_font_size": 15,
    "theme": {"mode": "system", "light": "One Light", "dark": "One Dark"},
}

text = json.dumps(cfg, indent=2) + "\n"
json.loads(text)
for path in paths:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"OK: settings {path}")
PY

# Zed reads DEEPSEEK_API_KEY from process env (not settings.json)
grep -v '^export DEEPSEEK_API_KEY=' "${HOME}/.zprofile" 2>/dev/null > /tmp/zprofile.tmp || true
echo "export DEEPSEEK_API_KEY='${KEY}'" >> /tmp/zprofile.tmp
mv /tmp/zprofile.tmp "${HOME}/.zprofile"
echo "export DEEPSEEK_API_KEY='${KEY}'" > "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "OK: DEEPSEEK_API_KEY → ~/.zprofile and ${ENV_FILE}"

echo "Restarting Zed with DEEPSEEK_API_KEY..."
killall zed 2>/dev/null || true
sleep 2
export DEEPSEEK_API_KEY="$KEY"
if open --help 2>&1 | grep -q '\-\-env'; then
  open -a Zed --env DEEPSEEK_API_KEY="$KEY"
else
  env DEEPSEEK_API_KEY="$KEY" open -a Zed
fi
echo "OK: Zed launched. If key still missing: Agent Settings → DeepSeek → paste key once."
