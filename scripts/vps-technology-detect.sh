#!/usr/bin/env bash
# vps-technology-detect.sh — HTTP fingerprint + API technology-detect for orchestrator
set -euo pipefail

TARGET="${1:-http://localhost:8888}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${2:-/tmp/hexstrike-tech-detect.json}"

load_api_key() {
  if [[ -n "${HEXSTRIKE_API_KEY:-}" ]]; then
    echo "$HEXSTRIKE_API_KEY"
    return
  fi
  if [[ -f "$ROOT/.env" ]]; then
    grep -E '^HEXSTRIKE_API_KEY=' "$ROOT/.env" | head -1 | cut -d= -f2- | tr -d '"'"'"
    return
  fi
  echo ""
}

echo "=== Technology detect: $TARGET ==="

HEADERS_FILE=$(mktemp)
BODY_FILE=$(mktemp)
trap 'rm -f "$HEADERS_FILE" "$BODY_FILE"' EXIT

probe() {
  local url="$1"
  curl -sS -D "$HEADERS_FILE" -o "$BODY_FILE" --max-time 10 "$url" || return 1
  local status server ctype
  status=$(awk 'NR==1{print $2}' "$HEADERS_FILE")
  server=$(awk -F': ' 'tolower($1)=="server"{print $2; exit}' "$HEADERS_FILE")
  ctype=$(awk -F': ' 'tolower($1)=="content-type"{print $2; exit}' "$HEADERS_FILE")
  echo "  GET $url"
  echo "    status: $status"
  echo "    Server: ${server:-<none>}"
  echo "    Content-Type: ${ctype:-<none>}"
}

probe "${TARGET%/}/health" || true
probe "$TARGET" || true

API_KEY=$(load_api_key)
API_JSON='{"error":"skipped"}'
if [[ -n "$API_KEY" ]]; then
  API_JSON=$(curl -sS --max-time 30 -X POST "${TARGET%/}/api/intelligence/technology-detection" \
    -H "Content-Type: application/json" \
    -H "X-API-KEY: $API_KEY" \
    -d "{\"target\":\"$TARGET\"}" || echo '{"error":"api failed"}')
else
  echo "  [warn] HEXSTRIKE_API_KEY not set — API detect skipped (health probe only)"
fi

SERVER=$(awk -F': ' 'tolower($1)=="server"{print $2; exit}' "$HEADERS_FILE")
STACK="unknown"
FRAMEWORK=""
if [[ "$SERVER" == *Werkzeug* || "$SERVER" == *Flask* ]]; then
  STACK="python"
  FRAMEWORK="Flask (Werkzeug dev server)"
fi

python3 - "$OUT" "$TARGET" "$SERVER" "$STACK" "$FRAMEWORK" "$API_JSON" <<'PY'
import json, sys, datetime
out, target, server, stack, framework, api_raw = sys.argv[1:7]
try:
    api = json.loads(api_raw)
except json.JSONDecodeError:
    api = {"parse_error": True, "raw": api_raw[:500]}
bundle = {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "target": target,
    "http_fingerprint": {
        "server_header": server or None,
        "inferred_stack": stack,
        "inferred_framework": framework or None,
    },
    "api_technology_detection": api,
}
with open(out, "w") as f:
    json.dump(bundle, f, indent=2)
print("")
print("=== Inferred stack ===")
print(f"  Framework: {framework or 'unknown'}")
print(f"  Server:    {server or 'unknown'}")
print(f"  Stack:     {stack}")
print("")
print(f"Full bundle: {out}")
PY
