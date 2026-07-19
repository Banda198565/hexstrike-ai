#!/usr/bin/env python3
"""Verify DeepSeek R1 API — standalone (no IDE). Never prints the API key."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.llm.cloud_r1 import CloudR1Provider, resolve_cloud_r1_config


def main() -> int:
    cfg = resolve_cloud_r1_config()
    if not cfg.api_key:
        print("FAIL: R1_API_KEY / DEEPSEEK_API_KEY / OPENROUTER_API_KEY not set")
        print("Set in .env or shell export:")
        print("  R1_PROVIDER=deepseek")
        print("  R1_API_KEY=sk-...")
        return 1

    print(f"provider: {cfg.provider}")
    print(f"base:     {cfg.base_url}")
    print(f"model:    {cfg.model}")
    print(f"key:      ***set*** ({len(cfg.api_key)} chars)")

    report = CloudR1Provider(cfg).handshake()
    ping = report.get("ping") or {}
    if not ping.get("ok"):
        print(f"FAIL: {ping.get('error', report)}")
        return 1

    preview = (ping.get("content") or "")[:200]
    print(f"OK: {preview!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
