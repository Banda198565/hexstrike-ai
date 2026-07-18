#!/usr/bin/env python3
"""Validate a shell command string against config/cursor-shell-patterns.json.

Optional layer on top of cli.json permissions — for pre-flight review or hooks.
Exit 0 = allowed, 1 = denied, 2 = config error.

Usage:
  python3 scripts/cursor-shell-guard.py "git status"
  python3 scripts/cursor-shell-guard.py "ls && rm -rf /"
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PATTERNS = ROOT / "config" / "cursor-shell-patterns.json"


def check(command: str, cfg: dict | None = None) -> tuple[bool, str]:
    if cfg is None:
        if not PATTERNS.is_file():
            return False, f"missing {PATTERNS}"
        cfg = json.loads(PATTERNS.read_text(encoding="utf-8"))

    cmd = command.strip()
    deny = cfg.get("deny_patterns") or []
    allow = cfg.get("allow_patterns") or []
    deny_wins = cfg.get("deny_wins", True)

    for pat in deny:
        if pat in cmd:
            return False, f"deny pattern matched: {pat!r}"

    if allow:
        matched = any(
            cmd == p.rstrip("*") or (p.endswith("*") and cmd.startswith(p[:-1]))
            for p in allow
        )
        if not matched:
            return False, "no allow pattern matched"

    if deny_wins:
        for pat in deny:
            if pat in cmd:
                return False, f"deny wins: {pat!r}"

    return True, "ok"


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: cursor-shell-guard.py <command>", file=sys.stderr)
        return 2
    command = " ".join(sys.argv[1:])
    ok, reason = check(command)
    print(reason)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
