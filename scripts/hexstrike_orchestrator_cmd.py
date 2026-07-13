#!/usr/bin/env python3
"""hexstrike orchestrator reload — manifest + MCP sync + combat agents verify."""
from __future__ import annotations

import json
import os
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

    # FastMCP contour presence (scripts + package) — never arms live on VPS
    fastmcp_files = [
        ROOT / "scripts" / "fastmcp_verify.sh",
        ROOT / "scripts" / "fastmcp_live_cycle.sh",
        ROOT / "scripts" / "fastmcp_status.sh",
        ROOT / "scripts" / "vps-fastmcp-ops.sh",
        ROOT / "src" / "hexstrike" / "mcp" / "fastmcp" / "tx_package.py",
    ]
    steps.append({
        "step": "verify_fastmcp_files",
        "ok": all(p.is_file() for p in fastmcp_files),
        "missing": [str(p.relative_to(ROOT)) for p in fastmcp_files if not p.is_file()],
    })

    live_forbidden_ok = os.environ.get("HEXSTRIKE_TX_LIVE", "") != "1" or os.environ.get("HEXSTRIKE_HOST_ROLE") == "mac"
    # On Linux /opt path, LIVE must be unset
    host_role = os.environ.get("HEXSTRIKE_HOST_ROLE", "")
    if not host_role:
        host_role = "vps" if str(ROOT) == "/opt/hexstrike-ai" or sys.platform.startswith("linux") else "mac"
    if host_role == "vps" and os.environ.get("HEXSTRIKE_TX_LIVE") == "1":
        live_forbidden_ok = False
    steps.append({"step": "live_gate_vps", "ok": live_forbidden_ok, "host_role": host_role})

    status = subprocess.run(["bash", str(ROOT / "scripts" / "fastmcp_status.sh")], cwd=str(ROOT), capture_output=True, text=True)
    status_ok = status.returncode == 0
    steps.append({"step": "fastmcp_status", "ok": status_ok})

    out = {
        "command": "orchestrator_reload",
        "steps": steps,
        "success": all(s["ok"] for s in steps),
        "host_role": host_role,
    }
    print(json.dumps(out, indent=2))
    return 0 if out["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
