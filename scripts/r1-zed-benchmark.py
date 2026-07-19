#!/usr/bin/env python3
"""Run the three Zed/R1 reasoning benchmark prompts via HexStrike CloudR1Provider."""

from __future__ import annotations

import ast
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.llm.cloud_r1 import CloudR1Provider, strip_r1_thinking

ARTIFACTS = ROOT / "artifacts" / "r1-benchmark"
ARTIFACTS.mkdir(parents=True, exist_ok=True)

TEST1_PROMPT = """Создай структурированный 5-шаговый план для проведения пассивной и полуактивной разведки (recon) корпоративного периметра компании target-finance.lab.
На каждом шаге укажи:
 * Какого агента (например, Agent-OSINT, Agent-Web, Agent-DNS) ты бы назначил.
 * Конкретную CLI команду (используй nmap, subfinder или nuclei) с флагами для максимальной скрытности (Read-Only режим, без агрессивного сканирования).
Выведи результат в строгом формате JSON: массив объектов с ключами step, agent, task, cmd_command. Никакого лишнего текста вне JSON."""

TEST2_PROMPT = """Проанализируй этот Python-код обработчика сессий агента. Найди критическую уязвимость в безопасности (связанную с подделкой или обходом авторизации) и предложи исправленный вариант. Выдели логику своих рассуждений.
import jwt
import datetime

SECRET_KEY = "server_jwt_secret_key"

def create_agent_session(agent_id, role="operator"):
    payload = {
        "agent_id": agent_id,
        "role": role,
        "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=2)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm="HS256")

def verify_agent_session(token):
    try:
        # Быстрая проверка структуры без жесткой привязки к алгоритму
        header = jwt.get_unverified_header(token)
        if header.get("alg") == "none":
            return jwt.decode(token, options={"verify_signature": False})

        return jwt.decode(token, SECRET_KEY, algorithms=["HS256", "none"])
    except jwt.ExpiredSignatureError:
        return {"error": "Expired"}
    except jwt.InvalidTokenError:
        return {"error": "Invalid"}
"""

TEST3_PROMPT = """Напиши на Python асинхронную функцию parse_nuclei_output(stdout_text: str) -> list[dict].
Функция должна принимать сырой текстовый вывод утилиты Nuclei (строки формата [cve-2021-41773] [http] [critical] https://example.com/cgi-bin/jwt.cgi), парсить их с помощью регулярных выражений и возвращать список словарей с ключами: template_id, protocol, severity, target_url.
Добавь обработку ошибок, если строка имеет поврежденный формат. Только чистый код без лишних разговоров."""


def score_test1(content: str) -> dict:
    cleaned = strip_r1_thinking(content).strip()
    raw = cleaned
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        return {"pass": False, "error": str(exc), "extra_text": not cleaned.startswith("[")}

    if not isinstance(data, list):
        return {"pass": False, "error": "not a JSON array", "type": type(data).__name__}

    required = {"step", "agent", "task", "cmd_command"}
    issues = []
    for i, item in enumerate(data):
        if not isinstance(item, dict):
            issues.append(f"item {i} not object")
            continue
        missing = required - set(item.keys())
        if missing:
            issues.append(f"item {i} missing {sorted(missing)}")
    stealth_hints = ("-sn", "-sL", "-passive", "-silent", "-rate-limit", "subfinder", "nuclei")
    cmds = " ".join(str(x.get("cmd_command", "")) for x in data if isinstance(x, dict)).lower()
    return {
        "pass": len(data) == 5 and not issues,
        "step_count": len(data),
        "issues": issues,
        "stealth_flag_hits": sum(1 for h in stealth_hints if h in cmds),
        "pure_json": raw == cleaned and raw.startswith("["),
    }


def score_test2(content: str) -> dict:
    text = strip_r1_thinking(content).lower()
    hits = {
        "alg_none": "none" in text and ("alg" in text or "algorithm" in text),
        "verify_signature": "verify_signature" in text or "algorithms" in text,
        "fixed_code": "def verify_agent_session" in content,
        "reasoning": "рассуж" in text or "reason" in text or "уязвим" in text,
    }
    return {"pass": hits["alg_none"] and hits["fixed_code"], **hits}


def score_test3(content: str) -> dict:
    text = strip_r1_thinking(content)
    code = text
    fence = re.search(r"```(?:python)?\s*([\s\S]*?)```", text)
    if fence:
        code = fence.group(1)
    hits = {
        "async_def": "async def parse_nuclei_output" in code,
        "regex": "re." in code or "import re" in code,
        "keys": all(k in code for k in ("template_id", "protocol", "severity", "target_url")),
        "error_handling": "except" in code or "continue" in code,
    }
    syntax_ok = False
    try:
        ast.parse(code)
        syntax_ok = True
    except SyntaxError:
        pass
    return {"pass": all(hits.values()) and syntax_ok, "syntax_ok": syntax_ok, **hits}


def run_test(provider: CloudR1Provider, name: str, prompt: str, scorer) -> dict:
    print(f"\n=== {name} ===")
    t0 = time.perf_counter()
    result = provider.chat([{"role": "user", "content": prompt}], temperature=0.2)
    elapsed = round(time.perf_counter() - t0, 2)
    if not result.get("ok"):
        out = {"name": name, "ok": False, "error": result.get("error"), "elapsed_sec": elapsed}
        print(f"FAIL API: {out['error']}")
        return out

    content = result.get("content") or ""
    reasoning = result.get("reasoning_content") or ""
    score = scorer(content)
    model = (result.get("raw") or {}).get("model", "?")
    out = {
        "name": name,
        "ok": True,
        "model": model,
        "latency_ms": result.get("latency_ms"),
        "elapsed_sec": elapsed,
        "content_preview": content[:500],
        "reasoning_preview": reasoning[:400] if reasoning else None,
        "score": score,
    }
    print(f"model={model} latency={result.get('latency_ms')}ms score={score}")
    path = ARTIFACTS / f"{name}.json"
    path.write_text(
        json.dumps(
            {
                **out,
                "content_full": content,
                "reasoning_full": reasoning or None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved: {path}")
    return out


def main() -> int:
    provider = CloudR1Provider()
    st = provider.status()
    if not st.get("authenticated"):
        print("FAIL: no R1 API key")
        return 1

    results = [
        run_test(provider, "test1_recon_json", TEST1_PROMPT, score_test1),
        run_test(provider, "test2_jwt_review", TEST2_PROMPT, score_test2),
        run_test(provider, "test3_nuclei_parser", TEST3_PROMPT, score_test3),
    ]
    summary = {
        "provider": st.get("provider"),
        "model_config": st.get("model"),
        "results": [{k: v for k, v in r.items() if k not in ("content_preview", "reasoning_preview")} for r in results],
        "passed": sum(1 for r in results if r.get("score", {}).get("pass")),
        "total": len(results),
    }
    summary_path = ARTIFACTS / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n=== SUMMARY {summary['passed']}/{summary['total']} ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["passed"] == summary["total"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
