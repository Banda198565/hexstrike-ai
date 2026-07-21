#!/usr/bin/env bash
# diagnose-zed-ollama.sh — why Zed does not show DeepSeek R1 (run on Mac/Linux with Zed)
# Usage: bash scripts/diagnose-zed-ollama.sh [model]
set -euo pipefail

HOST="http://127.0.0.1:11434"
MODEL="${1:-deepseek-r1:1.5b}"
ZED_XDG="${HOME}/.config/zed/settings.json"
ZED_MAC="${HOME}/Library/Application Support/Zed/settings.json"

echo "=== HexStrike Zed ↔ Ollama Diagnostic ==="
echo ""

fail=0
ok()   { echo "[OK]   $1"; }
bad()  { echo "[FAIL] $1"; fail=$((fail+1)); }
warn() { echo "[WARN] $1"; }

if command -v ollama >/dev/null 2>&1; then
  ok "ollama CLI present"
else
  bad "ollama CLI missing — brew install ollama"
fi

if curl -sf --max-time 3 "${HOST}/api/tags" >/dev/null; then
  ok "Ollama reachable at ${HOST}"
else
  bad "Ollama NOT running — open Ollama.app or: ollama serve"
fi

if command -v ollama >/dev/null 2>&1 && ollama list 2>/dev/null | awk '{print $1}' | grep -qx "${MODEL}"; then
  ok "Model in ollama list: ${MODEL}"
else
  bad "Model '${MODEL}' not pulled — run: ollama pull ${MODEL}"
  echo "       Available:"
  ollama list 2>/dev/null | sed 's/^/         /' || true
fi

settings=""
if [[ -f "${ZED_XDG}" ]]; then
  settings="${ZED_XDG}"
elif [[ -f "${ZED_MAC}" ]]; then
  settings="${ZED_MAC}"
fi

if [[ -n "${settings}" ]]; then
  ok "Zed settings found: ${settings}"
  if python3 - "${settings}" "${MODEL}" <<'PY'
import json, sys
path, model = sys.argv[1], sys.argv[2]
try:
    data = json.load(open(path))
except Exception as e:
    print(f"parse_error:{e}")
    sys.exit(2)
ollama = (data.get("language_models") or {}).get("ollama") or {}
api = ollama.get("api_url", "")
names = [m.get("name") for m in ollama.get("available_models") or [] if isinstance(m, dict)]
default = ((data.get("assistant") or {}).get("default_model") or {})
print(f"api_url={api}")
print(f"models={','.join(n for n in names if n)}")
print(f"default={default.get('provider')}:{default.get('model')}")
sys.exit(0 if model in names or ollama.get("auto_discover", True) else 1)
PY
  then
    ok "Zed settings reference Ollama / ${MODEL} (or auto_discover)"
  else
    bad "Zed settings missing ${MODEL} — run: bash scripts/install-zed-ollama-config.sh"
  fi
else
  bad "No Zed settings.json — run: bash scripts/install-zed-ollama-config.sh"
fi

if command -v zed >/dev/null 2>&1; then
  ok "zed CLI on PATH"
else
  warn "zed CLI not on PATH (app may still be installed)"
fi

echo ""
echo "=== Zed UI checklist ==="
echo "1. Agent panel → pick ${MODEL}"
echo "2. If list empty: Settings → Language Models → Ollama → API http://127.0.0.1:11434"
echo "3. Cloud Agent cannot configure your local Zed — run install script on the Mac"
echo ""

if [[ $fail -eq 0 ]]; then
  echo "=== Backend OK — select model in Zed Agent dropdown ==="
else
  echo "=== Fix failures above, then re-open Zed ==="
fi
exit "$fail"
