#!/usr/bin/env python3
"""HexStrike sync — verify MCP bindings and orchestrator integration."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BINDINGS = ROOT / "mcp" / "agent-bindings.json"
VERIFY = ROOT / "scripts" / "verify-exploit-integration.sh"


def sync_mcp() -> int:
    report: dict = {"command": "sync", "mode": "mcp", "root": str(ROOT), "checks": []}

    if BINDINGS.is_file():
        data = json.loads(BINDINGS.read_text(encoding="utf-8"))
        agents = list((data.get("agents") or {}).keys())
        report["checks"].append({"mcp_bindings": "ok", "agents": agents})
    else:
        report["checks"].append({"mcp_bindings": "missing", "path": str(BINDINGS)})
        print(json.dumps(report, indent=2))
        return 1

    if VERIFY.is_file():
        proc = subprocess.run(["bash", str(VERIFY), str(ROOT)], capture_output=True, text=True)
        report["checks"].append({
            "verify_exploit_integration": "ok" if proc.returncode == 0 else "fail",
            "tail": proc.stdout.strip().splitlines()[-1] if proc.stdout else proc.stderr[-200:],
        })
        if proc.returncode != 0:
            print(json.dumps(report, indent=2))
            return 1
    else:
        report["checks"].append({"verify_exploit_integration": "skipped"})

    report["result"] = "ok"
    print(json.dumps(report, indent=2))
    return 0


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--mcp":
        return sync_mcp()
    print(json.dumps({"error": "Usage: hexstrike sync --mcp"}, indent=2))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
