#!/usr/bin/env bash
# generate-model-report.sh — Agent-Report style briefing via local Ollama (1.5b)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-http://localhost:8888}"
MODEL="${LLM_MODEL:-deepseek-r1:1.5b}"
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
BUNDLE="${2:-/tmp/hexstrike-tech-detect.json}"
OUT_MD="${3:-$ROOT/artifacts/model-report-tech-detect.md}"
OUT_JSON="${4:-$ROOT/artifacts/model-report-tech-detect.json}"

mkdir -p "$(dirname "$OUT_MD")"

if [[ ! -f "$BUNDLE" ]]; then
  "$ROOT/scripts/vps-technology-detect.sh" "$TARGET" "$BUNDLE"
fi

HEALTH=$(curl -sf --max-time 5 "${TARGET%/}/health" 2>/dev/null || echo '{}')

python3 - "$BUNDLE" "$HEALTH" "$MODEL" "$HOST" "$OUT_MD" "$OUT_JSON" <<'PY'
import json, sys, urllib.request, pathlib

bundle_path, health_raw, model, host, out_md, out_json = sys.argv[1:7]
bundle = json.load(open(bundle_path))
try:
    health = json.loads(health_raw)
except json.JSONDecodeError:
    health = {}

prompt = f"""Ты Agent-Report-06. Краткое оперативное доложение (markdown, русский) по technology-detect.

Fingerprint JSON:
{json.dumps(bundle, ensure_ascii=False, indent=2)}

Health: version={health.get('version')} status={health.get('status')} tools={health.get('total_tools_available')}/{health.get('total_tools_count')}

Секции: ## Статус | ## Стек технологий | ## Риски | ## Tools gap | ## Рекомендации (3 пункта)
Только факты из данных."""

payload = json.dumps({
    "model": model,
    "stream": False,
    "options": {"num_predict": 512, "temperature": 0.2},
    "messages": [
        {"role": "system", "content": "Аналитик безопасности. Структурированный markdown без воды."},
        {"role": "user", "content": prompt},
    ],
}).encode()

content = None
err = None
try:
    req = urllib.request.Request(
        f"{host.rstrip('/')}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    content = data["choices"][0]["message"]["content"].strip()
except Exception as e:
    err = str(e)

if not content:
    # Fallback template when Ollama unavailable
    fp = bundle.get("http_fingerprint", {})
    api = bundle.get("api_technology_detection", {})
    prof = api.get("target_profile", {})
    content = f"""# Оперативное доложение — technology-detect

**Target:** {bundle.get('target')}
**Model fallback:** template (Ollama error: {err or 'empty response'})

## Статус
- API: {health.get('status', 'unknown')} v{health.get('version', '?')}
- Tools: {health.get('total_tools_available', '?')}/{health.get('total_tools_count', '?')}

## Стек технологий
- Server: {fp.get('server_header', 'unknown')}
- Framework: {fp.get('inferred_framework', 'unknown')}

## Риски
- risk_level: {prof.get('risk_level', 'unknown')}
- security_headers: {prof.get('security_headers', {})}

## Tools gap
Установить: nmap, nuclei, httpx (`./scripts/install-critical-tools.sh`)

## Рекомендации
1. `./scripts/vps-restore-known-good.sh`
2. `./scripts/vps-technology-detect.sh {bundle.get('target')}`
3. `RUN_CHECKLIST=1 ./scripts/vps-restore-known-good.sh`
"""

pathlib.Path(out_md).write_text(content + "\n")
json.dump({
    "model": model,
    "task": "technology-detect briefing",
    "target": bundle.get("target"),
    "source_bundle": bundle_path,
    "ollama_error": err,
    "markdown_chars": len(content),
    "report_markdown": content,
}, open(out_json, "w"), ensure_ascii=False, indent=2)

print(content)
print(f"\n[saved] {out_md}\n[saved] {out_json}")
PY
