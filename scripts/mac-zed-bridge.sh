#!/usr/bin/env bash
# Mac-side Zed + DeepSeek bridge. Run on iMac (Darwin only).
#
#   bash scripts/mac-zed-bridge.sh status
#   bash scripts/mac-zed-bridge.sh fix [api_key]
#   bash scripts/mac-zed-bridge.sh restart
set -euo pipefail

CMD="${1:-status}"
KEY="${2:-${DEEPSEEK_API_KEY:-}}"

SETTINGS="${HOME}/.config/zed/settings.json"
SETTINGS_ALT="${HOME}/Library/Application Support/Zed/settings.json"

die() { echo "ERROR: $*" >&2; exit 1; }

[[ "$(uname -s)" == "Darwin" ]] || die "Run on macOS"

status_json() {
  python3 - "$SETTINGS" "$SETTINGS_ALT" << 'PY'
import json, os, subprocess, sys
from pathlib import Path

paths = [Path(sys.argv[1]), Path(sys.argv[2])]
p = paths[0] if paths[0].is_file() else paths[1]
out = {"settings_path": str(p), "settings_exists": p.is_file(), "json_ok": False, "key_len": 0, "key_placeholder": False, "zed_running": False, "models_api_ok": False, "both_paths": [str(x) for x in paths]}

try:
    r = subprocess.run(["pgrep", "-x", "zed"], capture_output=True)
    out["zed_running"] = r.returncode == 0
except OSError:
    pass

if not p.is_file():
    print(json.dumps(out))
    raise SystemExit(0)

try:
    data = json.loads(p.read_text(encoding="utf-8"))
    out["json_ok"] = True
    key = (
        data.get("language_models", {}).get("providers", {}).get("deepseek", {}).get("api_key")
        or os.environ.get("DEEPSEEK_API_KEY", "")
    )
    if not key and Path.home().joinpath(".config/zed/env").is_file():
        for line in Path.home().joinpath(".config/zed/env").read_text().splitlines():
            if line.startswith("export DEEPSEEK_API_KEY="):
                key = line.split("=", 1)[1].strip().strip("'\"")
                break
    out["key_len"] = len(key)
    out["key_placeholder"] = "ВАШ" in key or key.endswith("_КЛЮЧ")
    if key and not out["key_placeholder"]:
        import urllib.request
        req = urllib.request.Request(
            "https://api.deepseek.com/v1/models",
            headers={"Authorization": f"Bearer {key}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read(200).decode()
                out["models_api_ok"] = '"data"' in body
        except Exception as exc:
            out["api_error"] = str(exc)[:120]
except json.JSONDecodeError as exc:
    out["json_error"] = str(exc)

print(json.dumps(out, ensure_ascii=False, indent=2))
PY
}

cmd_fix() {
  [[ -n "$KEY" ]] || die "Usage: mac-zed-bridge.sh fix sk-...  (or DEEPSEEK_API_KEY=...)"
  ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  bash "${ROOT}/scripts/fix-zed-deepseek-settings.sh" "$KEY"
}

cmd_restart() {
  killall zed 2>/dev/null || true
  sleep 2
  open -a Zed
  echo "OK: Zed restarted"
}

case "$CMD" in
  status) status_json ;;
  fix) cmd_fix ;;
  restart) cmd_restart ;;
  *) die "Usage: mac-zed-bridge.sh {status|fix|restart}" ;;
esac
