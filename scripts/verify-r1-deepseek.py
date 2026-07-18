#!/usr/bin/env python3
"""Verify DeepSeek R1 API connectivity — never prints the API key."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.workflow.r1_client import R1Client, resolve_r1_config


def main() -> int:
    cfg = resolve_r1_config()
    if not cfg.api_key:
        print("FAIL: R1_API_KEY / DEEPSEEK_API_KEY not set")
        print("Add to .env or Cursor Cloud Environment secrets:")
        print("  R1_PROVIDER=deepseek")
        print("  R1_API_KEY=sk-...")
        return 1

    print(f"provider: {cfg.base_url}")
    print(f"model:    {cfg.model}")
    print(f"key:      ***set*** ({len(cfg.api_key)} chars)")

    client = R1Client(cfg)
    resp = client.chat(
        [
            {"role": "system", "content": "Reply with exactly: R1_OK"},
            {"role": "user", "content": "ping"},
        ],
        temperature=0,
    )
    if not resp.get("ok"):
        print(f"FAIL: {resp.get('error', resp)}")
        return 1

    content = (resp.get("content") or "")[:200]
    print(f"OK: response preview: {content!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
