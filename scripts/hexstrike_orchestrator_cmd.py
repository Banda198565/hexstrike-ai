#!/usr/bin/env python3
"""hexstrike orchestrator reload — manifest + MCP sync + combat agents verify."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    steps: list[dict] = []

    sync = subprocess.run([sys.executable, str(ROOT / "scripts" / "hexstrike_sync.py"), "--mcp"], cwd=str(ROOT), capture_output=True, text=True)
    steps.append({"step": "sync_mcp", "ok": sync.returncode == 0})

    manifest = subprocess.run([sys.executable, str(ROOT / "hexstrike_orchestrator.py"), "manifest"], cwd=str(ROOT), capture_output=True, text=True)
    steps.append({"step": "manifest", "ok": manifest.returncode == 0})

    verify = subprocess.run(["bash", str(ROOT / "scripts" / "verify-exploit-integration.sh"), str(ROOT)], capture_output=True, text=True)
    steps.append({"step": "verify_exploit", "ok": verify.returncode == 0})

    combat = subprocess.run(["bash", str(ROOT / "scripts" / "verify-combat-integration.sh"), str(ROOT)], capture_output=True, text=True)
    steps.append({"step": "verify_combat", "ok": combat.returncode == 0})

    out = {"command": "orchestrator_reload", "steps": steps, "success": all(s["ok"] for s in steps)}
    print(json.dumps(out, indent=2))
    return 0 if out["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
