#!/usr/bin/env python3
"""Agent-Transaction-01 — формирование, подпись, бродкаст (via tx_control)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = ROOT / "artifacts" / "agents" / "transaction_agent.log"
OUT = ROOT / "artifacts" / "agents" / "transaction_result.json"


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] {msg}\n"
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line)


def run(mode: str = "dry-run") -> dict:
    target = os.environ.get("TARGET_ADDRESS", os.environ.get("TARGET_WALLET", ""))
    if not target:
        return {"agent": "transaction", "success": False, "error": "TARGET_ADDRESS not set"}

    script = ROOT / "scripts" / "tx_control.sh"
    cmd = ["bash", str(script)]
    if mode == "full":
        cmd.append("--live")
    else:
        cmd.append("--dry-run-only")
    if target:
        cmd.append(target)

    _log(f"run mode={mode} target={target}")
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    result = {
        "agent": "transaction",
        "agent_id": "Agent-Transaction-01",
        "mode": mode,
        "success": proc.returncode == 0,
        "exit_code": proc.returncode,
        "stdout_tail": proc.stdout[-3000:],
        "stderr_tail": proc.stderr[-1000:],
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    mode = os.environ.get("HEXSTRIKE_TASK", sys.argv[1] if len(sys.argv) > 1 else "dry-run")
    return 0 if run(mode).get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
