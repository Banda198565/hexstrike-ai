#!/usr/bin/env bash
# install-zed-ollama-config.sh — pull deepseek-r1 + merge Ollama settings into Zed
# Run on the machine where Zed is installed (Mac/Linux), not in Cloud Agent.
# Usage:
#   bash scripts/install-zed-ollama-config.sh
#   OLLAMA_MODEL=deepseek-r1:7b bash scripts/install-zed-ollama-config.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODEL="${OLLAMA_MODEL:-deepseek-r1:1.5b}"
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
TEMPLATE="${ROOT}/scripts/zed-ollama-settings.json"

# Zed settings locations (prefer XDG path; also support macOS Application Support)
ZED_XDG="${HOME}/.config/zed/settings.json"
ZED_MAC="${HOME}/Library/Application Support/Zed/settings.json"
if [[ -f "${ZED_MAC}" && ! -f "${ZED_XDG}" ]]; then
  ZED_SETTINGS="${ZED_MAC}"
else
  ZED_SETTINGS="${ZED_XDG}"
fi

echo "=== HexStrike: DeepSeek R1 → Zed (Ollama) ==="
echo "Model:    ${MODEL}"
echo "Ollama:   ${HOST}"
echo "Settings: ${ZED_SETTINGS}"
echo ""

# 1. Ollama CLI
if command -v ollama >/dev/null 2>&1; then
  echo "[OK]   ollama CLI: $(command -v ollama)"
else
  echo "[FAIL] ollama not found"
  echo "       brew install ollama"
  echo "       or: curl -fsSL https://ollama.com/install.sh | sh"
  exit 1
fi

# 2. Ollama API
if curl -sf --max-time 3 "${HOST}/api/tags" >/dev/null 2>&1; then
  echo "[OK]   Ollama API: ${HOST}"
else
  echo "[WARN] Ollama not running — start: open -a Ollama  OR  ollama serve"
  echo "       Continuing with model pull / settings merge..."
fi

# 3. Pull DeepSeek R1
if ollama list 2>/dev/null | awk '{print $1}' | grep -qx "${MODEL}"; then
  echo "[OK]   Model present: ${MODEL}"
else
  echo "[INFO] Pulling ${MODEL} ..."
  ollama pull "${MODEL}"
  echo "[OK]   Pulled ${MODEL}"
fi

# Also ensure 7b is available if operator asked for medium tier later
if [[ "${MODEL}" == "deepseek-r1:1.5b" ]] && [[ "${PULL_R1_7B:-0}" == "1" ]]; then
  if ! ollama list 2>/dev/null | awk '{print $1}' | grep -qx "deepseek-r1:7b"; then
    echo "[INFO] Pulling deepseek-r1:7b (PULL_R1_7B=1) ..."
    ollama pull deepseek-r1:7b || echo "[WARN] 7b pull failed"
  fi
fi

# 4. Merge template into Zed settings.json
if [[ ! -f "${TEMPLATE}" ]]; then
  echo "[FAIL] Missing template: ${TEMPLATE}"
  exit 1
fi

mkdir -p "$(dirname "${ZED_SETTINGS}")"
if [[ -f "${ZED_SETTINGS}" ]]; then
  cp -a "${ZED_SETTINGS}" "${ZED_SETTINGS}.bak.$(date +%Y%m%d%H%M%S)"
  echo "[OK]   Backed up existing settings"
fi

python3 - "${TEMPLATE}" "${ZED_SETTINGS}" "${MODEL}" <<'PY'
import json, sys
from pathlib import Path

template_path, settings_path, model = sys.argv[1], sys.argv[2], sys.argv[3]
template = json.loads(Path(template_path).read_text())
template.pop("_comment", None)

# Pin default assistant model to requested OLLAMA_MODEL
assistant = template.setdefault("assistant", {})
assistant["default_model"] = {"provider": "ollama", "model": model}
assistant.setdefault("version", "2")

path = Path(settings_path)
if path.exists() and path.stat().st_size > 0:
    try:
        current = json.loads(path.read_text())
        if not isinstance(current, dict):
            current = {}
    except json.JSONDecodeError:
        current = {}
else:
    current = {}

# Deep-merge language_models.ollama
lm = current.setdefault("language_models", {})
ollama = lm.setdefault("ollama", {})
src = template.get("language_models", {}).get("ollama", {})
ollama["api_url"] = src.get("api_url", ollama.get("api_url", "http://127.0.0.1:11434"))
if "auto_discover" in src:
    ollama["auto_discover"] = src["auto_discover"]

# Merge available_models by name (template wins on conflict)
existing = {m.get("name"): m for m in ollama.get("available_models", []) if isinstance(m, dict) and m.get("name")}
for m in src.get("available_models", []):
    if isinstance(m, dict) and m.get("name"):
        existing[m["name"]] = m
ollama["available_models"] = list(existing.values())

# Assistant defaults
current["assistant"] = {**current.get("assistant", {}), **template.get("assistant", {})}

path.write_text(json.dumps(current, indent=2) + "\n")
print(f"[OK]   Merged Ollama/DeepSeek R1 into {settings_path}")
PY

chmod 600 "${ZED_SETTINGS}" 2>/dev/null || true

echo ""
echo "=== Manual steps in Zed ==="
echo "1. Restart Zed (or reopen the window)"
echo "2. Open Agent panel → model dropdown"
echo "3. Select: ${MODEL}  (display: DeepSeek R1 … HexStrike)"
echo "4. If missing: agent: open settings → Ollama → confirm API URL ${HOST}"
echo ""
echo "Verify Ollama:"
echo "  ollama list | grep deepseek-r1"
echo "  curl -s ${HOST}/api/tags | python3 -m json.tool | head"
echo ""
echo "Done."
