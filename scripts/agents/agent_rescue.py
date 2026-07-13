#!/usr/bin/env python3
"""Agent-Rescue-01 — мониторинг GAS_HOLDER и SAFE top-up."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from api_auth import load_dotenv
from crypto_rpc_orchestrator import rpc_call

load_dotenv(ROOT / ".env")

LOG = ROOT / "artifacts" / "agents" / "rescue_agent.log"
OUT = ROOT / "artifacts" / "agents" / "rescue_result.json"
MIN_BNB = float(os.environ.get("RESCUE_MIN_BNB", "0.005"))


def _log(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] {msg}\n")


def balance_bnb(holder: str, rpc: str) -> float:
    wei = int(rpc_call(rpc, "eth_getBalance", [holder, "latest"])["result"], 16)
    return wei / 1e18


def run(mode: str = "check") -> dict:
    rpc = os.environ.get("RPC_URL", "")
    holder = os.environ.get("GAS_HOLDER_ADDRESS", "")
    if not rpc or not holder:
        return {"agent": "rescue", "success": False, "error": "RPC_URL and GAS_HOLDER_ADDRESS required"}

    bal = balance_bnb(holder, rpc)
    need = bal < MIN_BNB
    _log(f"mode={mode} holder={holder} balance_bnb={bal:.6f} need_rescue={need}")

    result: dict = {
        "agent": "rescue",
        "agent_id": "Agent-Rescue-01",
        "mode": mode,
        "gas_holder": holder,
        "balance_bnb": round(bal, 8),
        "min_bnb": MIN_BNB,
        "need_rescue": need,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if mode == "check":
        result["success"] = True
        result["action"] = "rescue_recommended" if need else "ok"
    elif mode in ("dry-run", "full") and need:
        cmd = [str(ROOT / "hexstrike"), "tx", "rescue", f"--target={holder}", "--value=0.01bnb"]
        if mode == "dry-run":
            cmd.append("--dry-run")
        env = os.environ.copy()
        if mode == "full":
            env["HEXSTRIKE_TX_LIVE"] = "1"
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
        result["success"] = proc.returncode == 0
        result["stdout"] = proc.stdout[-2000:]
    else:
        result["success"] = True
        result["action"] = "skipped_sufficient_balance"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


def main() -> int:
    mode = os.environ.get("HEXSTRIKE_TASK", sys.argv[1] if len(sys.argv) > 1 else "check")
    return 0 if run(mode).get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
