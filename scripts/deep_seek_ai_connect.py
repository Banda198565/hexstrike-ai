#!/usr/bin/env python3
"""DeepSeek API connect smoke-test (OpenAI-compatible).

Usage (Mac / VPS):
  export DEEPSEEK_API_KEY=sk-...
  python3 scripts/deep_seek_ai_connect.py
  python3 scripts/deep_seek_ai_connect.py --chat "Summarize BSC hot-wallet OSINT briefly"

Reads DEEPSEEK_API_KEY from env or repo .env. Never hardcode keys.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = os.environ.get("DEEPSEEK_API_BASE", "https://api.deepseek.com").rstrip("/")
DEFAULT_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or (ROOT / ".env")
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = val
    except OSError:
        return


def api_key() -> str:
    return (
        os.environ.get("DEEPSEEK_API_KEY")
        or os.environ.get("DEEPSEEK_KEY")
        or ""
    ).strip()


def request(method: str, path: str, payload: dict | None = None, timeout: int = 45) -> dict:
    key = api_key()
    if not key:
        raise SystemExit(
            "[FAIL] DEEPSEEK_API_KEY not set\n"
            "  export DEEPSEEK_API_KEY=sk-...\n"
            "  # or add to .env in repo root"
        )
    url = f"{DEFAULT_BASE}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:500]
        raise SystemExit(f"[FAIL] HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise SystemExit(f"[FAIL] transport: {e}") from e


def list_models() -> list[str]:
    payload = request("GET", "/v1/models")
    data = payload.get("data") or []
    return [str(m.get("id")) for m in data if isinstance(m, dict) and m.get("id")]


def chat(prompt: str, model: str) -> str:
    payload = request(
        "POST",
        "/v1/chat/completions",
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a defensive HexStrike OSINT assistant. "
                        "Read-only analysis only. No exploit or drain advice."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        },
    )
    choices = payload.get("choices") or []
    if not choices:
        return json.dumps(payload, ensure_ascii=False)[:1000]
    msg = choices[0].get("message") or {}
    return str(msg.get("content") or "")


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description="DeepSeek API connect / smoke test")
    ap.add_argument("--chat", metavar="PROMPT", help="Send one chat completion")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"default: {DEFAULT_MODEL}")
    ap.add_argument("--json-out", default="", help="Write smoke report JSON path")
    args = ap.parse_args()

    print("=== DeepSeek connect ===")
    print(f"Base:  {DEFAULT_BASE}")
    print(f"Model: {args.model}")
    print(f"Key:   {'set' if api_key() else 'MISSING'} (len={len(api_key())})")
    print()

    models = list_models()
    print(f"[OK]   /v1/models — {len(models)} model(s)")
    for m in models:
        print(f"       • {m}")

    if args.model not in models and models:
        print(f"[WARN] requested model not in list; using {models[0]}")
        args.model = models[0]

    reply = ""
    if args.chat:
        reply = chat(args.chat, args.model)
        print("\n[OK]   chat/completions")
        print("---")
        print(reply[:2000])
        print("---")

    report = {
        "success": True,
        "base": DEFAULT_BASE,
        "model": args.model,
        "models": models,
        "chat_preview": (reply[:500] if reply else None),
    }
    out = Path(args.json_out) if args.json_out else ROOT / "artifacts" / "deepseek-connect.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\n[OK]   wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
