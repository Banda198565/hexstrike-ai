#!/usr/bin/env python3
"""Unified offensive pipeline: live mempool → classify → PnL → builder sim (read-only)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ART = ROOT / "artifacts" / "sandbox"
MEV_DIR = ROOT / "scripts" / "sandbox" / "mev"


def _run(script: str, extra_env: dict[str, str] | None = None) -> None:
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(MEV_DIR / script)],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
    )
    if proc.stdout:
        print(proc.stdout, end="")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"{script} failed")


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def run_pipeline() -> dict[str, Any]:
    steps: list[dict[str, Any]] = []

    # 1) Live mempool (read-only public BSC RPC)
    _run("mempool_live.py")
    mempool = _load(ART / "mev-live-mempool-scan.json")
    steps.append({"step": "mempool_live", "candidates": mempool.get("candidate_count", 0), "mode": mempool.get("mode")})

    # Copy for fork_offensive loader
    (ART / "mev-bsc-mempool-scan.json").write_text(json.dumps(mempool, indent=2) + "\n", encoding="utf-8")

    # 2) Reserves + PnL (BSC fork if available, else live RPC pair read via fork_offensive)
    fork_mode = os.environ.get("PIPELINE_USE_FORK", "1")
    if fork_mode == "1":
        try:
            subprocess.run(
                ["bash", str(ROOT / "scripts" / "sandbox" / "setup-bsc-fork.sh")],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                timeout=120,
                check=True,
            )
            os.environ["MEV_RPC_URL"] = os.environ.get("MEV_RPC_URL", "http://127.0.0.1:8545")
            os.environ["MEV_ALLOWED_CHAINS"] = "56"
        except Exception as exc:
            steps.append({"step": "bsc_fork_setup", "warning": str(exc)})

    _run("fork_offensive.py", {"FORK_SCAN_MEMPOOL": "1", "FORK_FLUSH_MEMPOOL": "0"})
    fork = _load(ART / "mev-bsc-fork-result.json")
    steps.append({
        "step": "fork_offensive",
        "mempool_candidates": fork.get("mempool_candidate_count", 0),
        "skipped": fork.get("skipped"),
        "mode": fork.get("mode"),
    })

    # 3) Builder dry-run
    _run("builder_sim.py", {"BUILDER_SIM_ONLY": "1"})
    builder = _load(ART / "mev-builder-sim.json")
    steps.append({
        "step": "builder_sim",
        "should_execute": builder.get("should_execute"),
        "skip_reason": builder.get("skip_reason"),
    })

    sandwich = fork.get("sandwich_sim") or {}
    payload = {
        "chain_id": 56,
        "pipeline": "offensive_live",
        "simulation_only": True,
        "mempool": mempool,
        "sandwich_sim": sandwich,
        "mempool_analysis": fork.get("mempool"),
        "builder_sim": builder,
        "should_execute": bool(sandwich.get("should_execute")) and bool(builder.get("should_execute")),
        "skip_reason": sandwich.get("skip_reason") or builder.get("skip_reason"),
        "steps": steps,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return payload


def main() -> int:
    if os.environ.get("MEV_SANDBOX_ONLY", "1") != "1":
        print("[FAIL] pipeline is sandbox-only", file=sys.stderr)
        return 1
    if os.environ.get("MEV_MAINNET_SUBMIT") == "1":
        print("[FAIL] MEV_MAINNET_SUBMIT blocked", file=sys.stderr)
        return 1

    print("[pipeline] offensive live: mempool → classify → builder sim")
    result = run_pipeline()
    out = ART / "mev-live-pipeline-result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"[pipeline] → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
