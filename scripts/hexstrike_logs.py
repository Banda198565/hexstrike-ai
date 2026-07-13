#!/usr/bin/env python3
"""hexstrike logs — tail agent logs."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMBAT = ROOT / "agents" / "combat-agents.json"
TX_LOGS = ROOT / "tx_logs"


def resolve_log(name: str) -> Path | None:
    norm = name.replace("-", "_")
    if COMBAT.is_file():
        agents = json.loads(COMBAT.read_text())["agents"]
        for key, cfg in agents.items():
            if key == norm or key.replace("_", "") == norm.replace("_", ""):
                return ROOT / cfg.get("log", f"artifacts/agents/{key}_agent.log")
    candidates = [
        ROOT / f"artifacts/agents/{norm}.log",
        ROOT / f"artifacts/agents/{norm}_agent.log",
        TX_LOGS / "latest" / "tx_control.log",
    ]
    for c in candidates:
        if c.is_file():
            return c
    # latest tx_logs run
    if TX_LOGS.is_dir():
        runs = sorted(TX_LOGS.iterdir(), reverse=True)
        for run in runs:
            log = run / "tx_control.log"
            if log.is_file():
                return log
    return None


def main() -> int:
    p = argparse.ArgumentParser(prog="hexstrike logs")
    p.add_argument("agent", help="transaction_agent, discovery, rescue, ...")
    p.add_argument("--tail", type=int, default=50)
    args = p.parse_args()

    path = resolve_log(args.agent)
    if not path or not path.is_file():
        print(json.dumps({"error": f"log not found for {args.agent}"}))
        return 1

    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    tail = lines[-args.tail :]
    print(json.dumps({"agent": args.agent, "log": str(path), "lines": tail}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
