#!/usr/bin/env python3
"""Verify transport-only config files exist and cli.json blocks Shell (no shell required).

Exit 0 = all checks pass. For Cloud Agent: run after checkout to confirm branch has configs.

Usage:
  python3 scripts/verify-transport-config.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHECKS: list[tuple[str, Path, str | None]] = [
    ("cli.json", ROOT / ".cursor/cli.json", None),
    ("permissions.json", ROOT / ".cursor/permissions.json", None),
    ("transport-only rule", ROOT / ".cursor/rules/transport-only.mdc", None),
    ("shell-policy rule", ROOT / ".cursor/rules/shell-policy.mdc", None),
    ("gated mcp config", ROOT / "config/gated-mcp.json", None),
    ("cloud agent doc", ROOT / "config/cursor-cloud-agent-transport.md", None),
    ("mcp.json gated-orchestrator", ROOT / ".cursor/mcp.json", "gated-orchestrator"),
]


def _cli_shell_blocked() -> tuple[bool, str]:
    cli = ROOT / ".cursor/cli.json"
    if not cli.is_file():
        return False, "missing .cursor/cli.json"
    cfg = json.loads(cli.read_text(encoding="utf-8"))
    perms = cfg.get("permissions") or {}
    deny = [str(x) for x in (perms.get("deny") or [])]
    allow = [str(x) for x in (perms.get("allow") or [])]
    if not any(d.startswith("Shell(") for d in deny):
        return False, "no Shell(...) in deny"
    if any(a.startswith("Shell(") for a in allow):
        return False, "Shell(...) found in allow"
    return True, "Shell(*) denied, no Shell in allow"


def main() -> int:
    ok = True
    print("=== Transport config verification ===\n")
    for name, path, needle in CHECKS:
        if not path.is_file():
            print(f"FAIL  {name}: missing {path.relative_to(ROOT)}")
            ok = False
            continue
        if needle and needle not in path.read_text(encoding="utf-8"):
            print(f"FAIL  {name}: {needle!r} not in {path.name}")
            ok = False
        else:
            print(f"OK    {name}")

    blocked, detail = _cli_shell_blocked()
    if blocked:
        print(f"OK    cli Shell block: {detail}")
    else:
        print(f"FAIL  cli Shell block: {detail}")
        ok = False

    perms = ROOT / ".cursor/permissions.json"
    if perms.is_file() and '"terminalAllowlist": []' in perms.read_text(encoding="utf-8"):
        print("OK    permissions terminalAllowlist empty")
    else:
        print("FAIL  permissions terminalAllowlist not empty")
        ok = False

    print()
    if ok:
        print("RESULT: PASS — transport configs present on this branch")
        return 0
    print("RESULT: FAIL — merge PR #71 or cherry-pick transport commits")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
