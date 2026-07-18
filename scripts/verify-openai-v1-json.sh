#!/usr/bin/env bash
# verify-openai-v1-json.sh — detect Nano AI / OpenAI-client JSON Parse errors
# against local Ollama. Prints first bytes of each response and fails if body
# is not JSON (classic "Unexpected character: E" = plain "Error: ...").
set -euo pipefail

HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
HOST="${HOST%/}"
MODEL="${OLLAMA_MODEL:-${HEXSTRIKE_CHAT_MODEL:-qwen2.5-coder:7b}}"

red() { printf '\033[31m%s\033[0m\n' "$*"; }
ok() { printf '[OK]  %s\n' "$*"; }
fail() { red "[FAIL] $*"; }

echo "=== OpenAI /v1 JSON probe ==="
echo "host=${HOST}"
echo "model=${MODEL}"
echo ""

is_json() {
  python3 -c 'import sys,json; json.load(sys.stdin)' 2>/dev/null
}

probe() {
  local name="$1" url="$2"
  shift 2
  local body file
  file="$(mktemp)"
  code="$(curl -sS -o "$file" -w '%{http_code}' --max-time 60 "$url" "$@" || true)"
  head="$(head -c 120 "$file" | tr '\n' ' ')"
  echo "--- ${name} HTTP ${code}"
  echo "prefix: ${head}"
  if [[ ! -s "$file" ]]; then
    fail "${name}: empty body"
    rm -f "$file"
    return 1
  fi
  first="$(head -c 1 "$file")"
  if [[ "$first" != "{" && "$first" != "[" ]]; then
    fail "${name}: not JSON (starts with '${first}') — Nano AI will throw JSON Parse error"
    if [[ "$first" == "E" || "$first" == "e" ]]; then
      echo "hint: body looks like Error:... — wrong model name or wrong path"
    fi
    rm -f "$file"
    return 1
  fi
  if is_json <"$file"; then
    ok "${name}: valid JSON"
    rm -f "$file"
    return 0
  fi
  fail "${name}: looks like JSON but failed to parse"
  rm -f "$file"
  return 1
}

RC=0
probe "GET /api/tags" "${HOST}/api/tags" || RC=1
probe "GET /v1/models" "${HOST}/v1/models" || RC=1

# Wrong path often returns HTML/text — demonstrate for operators
WRONG="$(mktemp)"
curl -sS -o "$WRONG" -w '%{http_code}' --max-time 10 "${HOST}/api/generate" \
  -H 'Content-Type: application/json' \
  -d '{"model":"deepseek-v4-flash","prompt":"ping"}' >/tmp/hs-v1-wrong.code || true
echo "--- anti-pattern POST /api/generate model=deepseek-v4-flash (local Ollama)"
echo "prefix: $(head -c 120 "$WRONG" | tr '\n' ' ')"
echo "note: deepseek-v4-flash is official API / OpenRouter id — not a local Ollama tag"
rm -f "$WRONG"

CHAT_FILE="$(mktemp)"
CHAT_CODE="$(curl -sS -o "$CHAT_FILE" -w '%{http_code}' --max-time 120 \
  "${HOST}/v1/chat/completions" \
  -H 'Content-Type: application/json' \
  -d "{\"model\":\"${MODEL}\",\"messages\":[{\"role\":\"user\",\"content\":\"Reply with exactly: pong\"}],\"stream\":false}" || true)"
echo "--- POST /v1/chat/completions HTTP ${CHAT_CODE}"
echo "prefix: $(head -c 160 "$CHAT_FILE" | tr '\n' ' ')"
if head -c 1 "$CHAT_FILE" | grep -q '{'; then
  if is_json <"$CHAT_FILE"; then
    ok "chat/completions: valid JSON (use this Base URL in Nano AI: ${HOST}/v1 )"
  else
    fail "chat/completions: invalid JSON"
    RC=1
  fi
else
  fail "chat/completions: not JSON — fix model pull or Base URL"
  RC=1
fi
rm -f "$CHAT_FILE"

echo ""
echo "Nano AI / OpenAI client settings:"
echo "  Base URL : ${HOST}/v1"
echo "  Model    : ${MODEL}"
echo "  API Key  : ollama"
echo "Do NOT set Base URL to .../api/generate"
echo "Do NOT use deepseek-v4-flash as a local Ollama model name"
exit "$RC"
