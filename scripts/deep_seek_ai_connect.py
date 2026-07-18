#!/usr/bin/env python3
"""Read-only connector for deep-seek.ai public chat (model attribution / canary).

Policy: uses the same browser flow as the public UI (CSRF + session cookies).
No credential stuffing, no rate-limit bypass, no exploit payloads.
Prompts may leave your host to a third-party mirror + OpenRouter — do not send secrets.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_BASE = "https://deep-seek.ai"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_PROMPT = "Reply with exactly: CONNECT-OK"
UA = "HexStrike-ReadOnly-OSINT/1.0 (+deep_seek_ai_connect)"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_opener() -> urllib.request.OpenerDirector:
    ctx = ssl.create_default_context()
    jar = http.cookiejar.CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=ctx),
    )


def _request(
    opener: urllib.request.OpenerDirector,
    url: str,
    *,
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 60,
) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with opener.open(req, timeout=timeout) as resp:
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
        return resp.status, hdrs, resp.read()


def cookie_value(opener: urllib.request.OpenerDirector, name: str) -> str | None:
    for handler in opener.handlers:
        if isinstance(handler, urllib.request.HTTPCookieProcessor):
            for cookie in handler.cookiejar:
                if cookie.name == name:
                    return urllib.parse.unquote(cookie.value)
    return None


def fetch_chat_bootstrap(opener: urllib.request.OpenerDirector, base: str) -> dict[str, Any]:
    status, headers, body = _request(
        opener,
        f"{base.rstrip('/')}/chat",
        headers={"User-Agent": UA, "Accept": "text/html"},
        timeout=30,
    )
    html = body.decode("utf-8", "replace")
    csrf_m = re.search(r'csrf-token" content="([^"]+)"', html)
    models_m = re.search(r"window\.__CHAT_MODELS__\s*=\s*(\[.*?\]);", html)
    site_m = re.search(r'window\.__CHAT_SITE_NAME__\s*=\s*"([^"]*)"', html)
    if not csrf_m:
        raise RuntimeError("CSRF token not found on /chat")
    models = json.loads(models_m.group(1)) if models_m else []
    return {
        "http_status": status,
        "content_type": headers.get("content-type"),
        "csrf": csrf_m.group(1),
        "site_name": site_m.group(1) if site_m else None,
        "models": models,
        "default_model": models[0]["id"] if models else DEFAULT_MODEL,
        "xsrf": cookie_value(opener, "XSRF-TOKEN"),
        "session_present": cookie_value(opener, "deepseek_session") is not None,
    }


def parse_sse(raw: str) -> dict[str, Any]:
    model_ids: set[str] = set()
    providers: set[str] = set()
    request_ids: set[str] = set()
    contents: list[str] = []
    reasonings: list[str] = []
    openrouter = ": OPENROUTER PROCESSING" in raw

    for line in raw.splitlines():
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(chunk.get("model"), str):
            model_ids.add(chunk["model"])
        if isinstance(chunk.get("provider"), str):
            providers.add(chunk["provider"])
        if isinstance(chunk.get("id"), str):
            request_ids.add(chunk["id"])
        for choice in chunk.get("choices") or []:
            delta = choice.get("delta") or {}
            if isinstance(delta.get("content"), str) and delta["content"]:
                contents.append(delta["content"])
            if isinstance(delta.get("reasoning"), str) and delta["reasoning"]:
                reasonings.append(delta["reasoning"])

    return {
        "openrouter_processing_marker": openrouter,
        "model_field_values": sorted(model_ids),
        "provider_field_values": sorted(providers),
        "request_ids": sorted(request_ids),
        "assistant_text": "".join(contents),
        "reasoning_preview": "".join(reasonings)[:400],
        "raw_prefix": raw[:600],
    }


def chat(
    opener: urllib.request.OpenerDirector,
    base: str,
    *,
    csrf: str,
    xsrf: str | None,
    model: str,
    prompt: str,
    timeout: int,
) -> dict[str, Any]:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "User-Agent": UA,
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
        "X-CSRF-TOKEN": csrf,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": base.rstrip("/"),
        "Referer": f"{base.rstrip('/')}/chat",
    }
    if xsrf:
        headers["X-XSRF-TOKEN"] = xsrf

    try:
        status, resp_headers, body = _request(
            opener,
            f"{base.rstrip('/')}/api/chat",
            method="POST",
            data=data,
            headers=headers,
            timeout=timeout,
        )
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", "replace")
        return {
            "ok": False,
            "http_status": exc.code,
            "error": err_body[:1000],
            "limit_exhausted": exc.code == 429,
        }

    text = body.decode("utf-8", "replace")
    ctype = resp_headers.get("content-type", "")
    parsed = parse_sse(text) if "text/event-stream" in ctype or text.startswith(":") else {
        "assistant_text": text[:2000],
        "raw_prefix": text[:600],
    }
    return {
        "ok": bool(parsed.get("assistant_text")) or bool(parsed.get("model_field_values")),
        "http_status": status,
        "content_type": ctype,
        "requested_model": model,
        "prompt": prompt,
        **parsed,
    }


def connect(base: str, model: str | None, prompt: str, timeout: int) -> dict[str, Any]:
    opener = build_opener()
    report: dict[str, Any] = {
        "generated_at": utc_now(),
        "mode": "read-only_no_exploit",
        "base_url": base.rstrip("/"),
        "ok": False,
    }
    try:
        boot = fetch_chat_bootstrap(opener, base)
        report["bootstrap"] = {
            "http_status": boot["http_status"],
            "site_name": boot["site_name"],
            "session_present": boot["session_present"],
            "xsrf_present": bool(boot["xsrf"]),
            "models": boot["models"],
            "default_model": boot["default_model"],
        }
        selected = model or boot["default_model"]
        result = chat(
            opener,
            base,
            csrf=boot["csrf"],
            xsrf=boot["xsrf"],
            model=selected,
            prompt=prompt,
            timeout=timeout,
        )
        report["chat"] = result
        report["ok"] = bool(result.get("ok"))
        report["verdict"] = {
            "connected": report["ok"],
            "model": (result.get("model_field_values") or [selected])[0],
            "provider": (result.get("provider_field_values") or [None])[0],
            "proxy": "OpenRouter" if result.get("openrouter_processing_marker") else "unknown",
            "assistant_text": result.get("assistant_text"),
        }
    except Exception as exc:  # noqa: BLE001 — surface connector failures as JSON
        report["error"] = str(exc)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Connect to deep-seek.ai public chat (read-only OSINT / canary)."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE, help="Site origin")
    parser.add_argument(
        "--model",
        default=None,
        help=f"OpenRouter-style model id (default: site default / {DEFAULT_MODEL})",
    )
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="User message")
    parser.add_argument("--timeout", type=int, default=90, help="Chat timeout seconds")
    parser.add_argument(
        "--output",
        default="",
        help="Optional path to write JSON report (also printed to stdout)",
    )
    args = parser.parse_args(argv)

    report = connect(args.base_url, args.model, args.prompt, args.timeout)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    sys.stdout.write(text)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
