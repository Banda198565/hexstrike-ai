#!/usr/bin/env bash
# install-zed-deepseek-cloud.sh — configure Zed for DeepSeek CLOUD API (R1 / reasoner)
# Run on Mac with Zed. Does NOT need Ollama.
#
# Usage:
#   export DEEPSEEK_API_KEY='sk-...'   # optional; Zed UI keychain also works
#   bash scripts/install-zed-deepseek-cloud.sh
#
# Key: https://platform.deepseek.com/api_keys
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

MODEL="${DEEPSEEK_MODEL:-deepseek-reasoner}"
API_URL="${DEEPSEEK_API_URL:-https://api.deepseek.com}"
TEMPLATE="${ROOT}/scripts/zed-deepseek-cloud-settings.json"

ZED_XDG="${HOME}/.config/zed/settings.json"
ZED_MAC="${HOME}/Library/Application Support/Zed/settings.json"
if [[ -f "${ZED_MAC}" && ! -f "${ZED_XDG}" ]]; then
  ZED_SETTINGS="${ZED_MAC}"
else
  ZED_SETTINGS="${ZED_XDG}"
fi

echo "=== HexStrike: DeepSeek CLOUD R1 → Zed ==="
echo "Model:    ${MODEL}"
echo "API:      ${API_URL}"
echo "Settings: ${ZED_SETTINGS}"
echo ""

if [[ ! -f "${TEMPLATE}" ]]; then
  echo "[FAIL] Missing ${TEMPLATE}"
  exit 1
fi

mkdir -p "$(dirname "${ZED_SETTINGS}")"
if [[ -f "${ZED_SETTINGS}" ]]; then
  cp -a "${ZED_SETTINGS}" "${ZED_SETTINGS}.bak.$(date +%Y%m%d%H%M%S)"
  echo "[OK]   Backed up existing settings"
fi

python3 - "${TEMPLATE}" "${ZED_SETTINGS}" "${MODEL}" "${API_URL}" <<'PY'
import json, sys
from pathlib import Path

template_path, settings_path, model, api_url = sys.argv[1:5]
template = json.loads(Path(template_path).read_text())
template.pop("_comment", None)

assistant = template.setdefault("assistant", {})
assistant["default_model"] = {"provider": "deepseek", "model": model}
assistant.setdefault("version", "2")

ds = template.setdefault("language_models", {}).setdefault("deepseek", {})
ds["api_url"] = api_url

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

# Prefer cloud DeepSeek; drop local Ollama default if present
lm = current.setdefault("language_models", {})
dst = lm.setdefault("deepseek", {})
src = template["language_models"]["deepseek"]
dst["api_url"] = src.get("api_url", api_url)

existing = {m.get("name"): m for m in dst.get("available_models", []) if isinstance(m, dict) and m.get("name")}
for m in src.get("available_models", []):
    if isinstance(m, dict) and m.get("name"):
        existing[m["name"]] = m
dst["available_models"] = list(existing.values())

current["assistant"] = {**current.get("assistant", {}), **template.get("assistant", {})}
# Remove ollama as default if we just set deepseek
path.write_text(json.dumps(current, indent=2) + "\n")
print(f"[OK]   Merged DeepSeek cloud into {settings_path}")
PY

chmod 600 "${ZED_SETTINGS}" 2>/dev/null || true

# Persist key for shells / Zed launched from terminal (never print the key)
ENV_FILE="${HOME}/.hexstrike-deepseek.env"
if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  umask 077
  printf 'export DEEPSEEK_API_KEY=%q\n' "${DEEPSEEK_API_KEY}" > "${ENV_FILE}"
  echo "[OK]   Wrote ${ENV_FILE} (chmod 600)"
  # Ensure zsh loads it
  for rc in "${HOME}/.zshrc" "${HOME}/.zprofile"; do
    [[ -f "$rc" ]] || touch "$rc"
    if ! grep -q 'hexstrike-deepseek.env' "$rc" 2>/dev/null; then
      echo '' >> "$rc"
      echo '# HexStrike DeepSeek cloud (Zed)' >> "$rc"
      echo '[[ -f ~/.hexstrike-deepseek.env ]] && source ~/.hexstrike-deepseek.env' >> "$rc"
      echo "[OK]   Hooked ${rc}"
    fi
  done
else
  echo "[WARN] DEEPSEEK_API_KEY not set in this shell"
  echo "       Get key: https://platform.deepseek.com/api_keys"
  echo "       Then either:"
  echo "         export DEEPSEEK_API_KEY='sk-...' && bash scripts/install-zed-deepseek-cloud.sh"
  echo "       or paste key in Zed: agent: open settings → DeepSeek"
fi

# Optional API smoke test (no key leak)
if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  echo "[INFO] Smoke-testing ${API_URL}/models ..."
  code=$(curl -s -o /tmp/hexstrike-deepseek-models.json -w '%{http_code}' \
    --max-time 20 \
    -H "Authorization: Bearer ${DEEPSEEK_API_KEY}" \
    "${API_URL}/models" || echo "000")
  if [[ "$code" == "200" ]]; then
    echo "[OK]   DeepSeek API key accepted (HTTP 200)"
    python3 - <<'PY' 2>/dev/null || true
import json
d=json.load(open("/tmp/hexstrike-deepseek-models.json"))
ids=[m.get("id") for m in d.get("data",[]) if isinstance(m, dict)]
print("       models:", ", ".join(ids[:12]) or "(none listed)")
PY
  else
    echo "[FAIL] DeepSeek API HTTP ${code} — check key / balance at platform.deepseek.com"
  fi
  rm -f /tmp/hexstrike-deepseek-models.json
fi

echo ""
echo "=== Zed ==="
echo "1. Restart Zed"
echo "2. Agent → select: ${MODEL}"
echo "3. If auth error: agent: open settings → DeepSeek → paste API key"
echo "4. Need balance/top-up on https://platform.deepseek.com"
echo ""
echo "Note: deepseek-reasoner ≈ R1; after 2026-07-24 prefer deepseek-v4-flash (thinking)."
echo "Done."
