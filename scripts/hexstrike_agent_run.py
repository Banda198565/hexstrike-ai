#!/usr/bin/env python3
"""hexstrike agent run — combat agents dispatcher."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMBAT = ROOT / "agents" / "combat-agents.json"


def load_combat() -> dict:
    return json.loads(COMBAT.read_text(encoding="utf-8"))


def run_agent(name: str, mode: str) -> dict:
    cfg = load_combat()["agents"].get(name)
    if not cfg:
        return {"success": False, "error": f"Unknown agent: {name}", "known": list(load_combat()["agents"])}

    if "workflow" in cfg:
        cmd = [sys.executable, str(ROOT / "scripts" / "hexstrike-orchestrator.py"), "run", cfg["workflow"], "--quiet"]
        proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
        return {
            "agent": name,
            "mode": mode,
            "type": "workflow",
            "success": proc.returncode == 0,
            "stdout": proc.stdout[-2000:],
            "stderr": proc.stderr[-500:],
        }

    script = ROOT / cfg["script"]
    env = {"HEXSTRIKE_TASK": mode}
    proc = subprocess.run(
        [sys.executable, str(script), mode],
        cwd=str(ROOT),
        env={**dict(**{k: v for k, v in __import__("os").environ.items()}), **env},
        capture_output=True,
        text=True,
    )
    return {
        "agent": name,
        "mode": mode,
        "success": proc.returncode == 0,
        "stdout": proc.stdout[-3000:],
        "stderr": proc.stderr[-500:],
    }


def run_pipeline(name: str) -> int:
    pipelines = load_combat().get("pipelines", {})
    if name not in pipelines:
        print(json.dumps({"error": f"Unknown pipeline: {name}", "known": list(pipelines)}))
        return 1

    import os

    pipe = pipelines[name]
    results: list[dict] = []
    live = os.environ.get("HEXSTRIKE_TX_LIVE") == "1"

    parallel = pipe.get("parallel", [])
    if parallel:
        with ThreadPoolExecutor(max_workers=len(parallel)) as ex:
            futs = {}
            for s in parallel:
                mode = s.get("mode", "scan")
                if s.get("agent") == "transaction" and live:
                    mode = "full"
                futs[ex.submit(run_agent, s["agent"], mode)] = s
            for fut in as_completed(futs):
                results.append(fut.result())

    for step in pipe.get("sequential_after", []):
        results.append(run_agent(step["agent"], step.get("mode", "check")))

    out = {"pipeline": name, "results": results, "success": all(r.get("success") for r in results)}
    print(json.dumps(out, indent=2))
    return 0 if out["success"] else 1


def main() -> int:
    p = argparse.ArgumentParser(prog="hexstrike agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("agent", help="transaction|rescue|discovery|forensics|pipeline")
    run_p.add_argument("--mode", default="dry-run")
    run_p.add_argument("--trace", action="store_true", help="discovery trace mode")
    run_p.add_argument("--pipeline", help="Run named pipeline e.g. transaction-discovery")

    args = p.parse_args()
    if args.agent == "pipeline" or args.pipeline:
        return run_pipeline(args.pipeline or "transaction-discovery")

    mode = args.mode
    if args.agent == "discovery" and args.trace:
        mode = "trace"
    if args.agent == "transaction" and mode == "full":
        mode = "full"

    result = run_agent(args.agent, mode)
    print(json.dumps(result, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
