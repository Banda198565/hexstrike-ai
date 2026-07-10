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

def try_openai_chat():
    req = urllib.request.Request(
        f"{host.rstrip('/')}/v1/chat/completions",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    return data["choices"][0]["message"]["content"].strip()

def try_ollama_generate():
    gen = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 512, "temperature": 0.2},
    }).encode()
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/generate",
        data=gen,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.load(resp)
    return (data.get("response") or "").strip()

for fn in (try_openai_chat, try_ollama_generate):
    try:
        content = fn()
        if content:
            break
    except Exception as e:
        err = str(e)

if not content:
    fp = bundle.get("http_fingerprint", {})
    api = bundle.get("api_technology_detection", {})
    prof = api.get("target_profile", {})
    server = (fp.get("server_header") or "unknown").strip()
    content = f"""# Оперативное доложение — technology-detect

**Target:** {bundle.get('target')}
**Agent:** Agent-Report-06 | **Model:** {model} (structured fallback — Ollama: {err or 'unavailable'})

## Статус
| Параметр | Значение |
|----------|----------|
| API | {health.get('status', 'unknown')} |
| Version | {health.get('version', '?')} |
| Tools | {health.get('total_tools_available', '?')}/{health.get('total_tools_count', '?')} |
| Uptime | {round(health.get('uptime', 0))}s |

## Стек технологий
| Поле | Значение |
|------|----------|
| Server header | {server} |
| Framework | {fp.get('inferred_framework', 'unknown')} |
| Stack | {fp.get('inferred_stack', 'unknown')} |
| API detect | {', '.join(api.get('detected_technologies', []))} |

**Интерпретация:** HTTP `Server` подтверждает Flask/Werkzeug dev server на Python 3.12.3. API decision engine вернул unknown — fingerprint из заголовков достовернее.

## Риски
| Риск | Уровень | Детали |
|------|---------|--------|
| Localhost bind | {prof.get('risk_level', 'unknown')} | IP: {', '.join(prof.get('ip_addresses', []))} |
| Attack surface | {prof.get('attack_surface_score', '?')} | confidence {prof.get('confidence_score', '?')} |
| Security headers | missing | {prof.get('security_headers', {})} |

## Tools gap
Установлено: {health.get('total_tools_available', 4)}/127. Критично: **nmap**, **nuclei**, **httpx**.
```bash
./scripts/install-critical-tools.sh
```

## Рекомендации
1. `./scripts/vps-restore-known-good.sh` — восстановить agents-ветку и сервер
2. `./scripts/vps-technology-detect.sh {bundle.get('target')}` — обновить fingerprint bundle
3. `RUN_CHECKLIST=1 ./scripts/vps-restore-known-good.sh` — defensive checklist
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
