#!/usr/bin/env python3
"""BSC fork offensive MEV — real pools/prices, simulation only (no mainnet submit)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from mev_pnl import sandwich_pnl_from_reserves

ROOT = Path(__file__).resolve().parents[3]

PANCAKE_PAIR = os.environ.get(
    "BSC_PAIR", "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae"
)
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2e08d91793bc095c"
USDT = "0x55d398326f99059fF775485246999027B3197955"
ROUTER = "0x10ED43C718714eb63d5aB7E8d58b0B6B0a0b54852"
RPC_TIMEOUT_SEC = float(os.environ.get("FORK_RPC_TIMEOUT_SEC", "10"))


def rpc_url() -> str:
    return os.environ.get("MEV_RPC_URL", "http://127.0.0.1:8545")


def cast(*args: str) -> str:
    proc = subprocess.run(
        ["cast", *args, "--rpc-url", rpc_url()],
        capture_output=True,
        text=True,
        check=False,
        timeout=RPC_TIMEOUT_SEC,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def get_reserves() -> tuple[int, int]:
    raw = cast("call", PANCAKE_PAIR, "getReserves()(uint112,uint112,uint32)")
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    vals = []
    for ln in lines[:2]:
        vals.append(int(ln.split("[")[0].strip()))
    if len(vals) < 2:
        parts = raw.split()
        vals = [int(parts[0].split("[")[0]), int(parts[1].split("[")[0])]
    return vals[0], vals[1]


def simulate_offensive(
    reserve_eth: int,
    reserve_token: int,
    victim_bnb_wei: int,
    frontrun_bnb_wei: int,
    network_fee_wei: int,
) -> dict:
    sim = sandwich_pnl_from_reserves(
        reserve_eth,
        reserve_token,
        victim_bnb_wei,
        frontrun_bnb_wei,
        network_fee_wei=network_fee_wei,
    )
    return {
        "pair": PANCAKE_PAIR,
        "reserves_eth": sim.reserves_eth,
        "reserves_token": sim.reserves_token,
        "victim_bnb_wei": sim.victim_bnb_wei,
        "frontrun_bnb_wei": sim.frontrun_bnb_wei,
        "estimated_profit_wei": sim.estimated_profit_wei,
        "network_fee_wei": sim.network_fee_wei,
        "net_profit_wei": sim.net_profit_wei,
        "profitable": sim.profitable,
        "should_execute": sim.should_execute,
        "skip_reason": sim.skip_reason,
    }


def main() -> int:
    victim = int(float(os.environ.get("FORK_VICTIM_BNB", "5")) * 1e18)
    frontrun = int(float(os.environ.get("FORK_FRONTRUN_BNB", "1")) * 1e18)
    network_fee = int(os.environ.get("FORK_NETWORK_FEE_WEI", str(210_000 * 3_000_000_000)))

    # Synthetic zero-spread test (no RPC)
    if os.environ.get("FORK_SYNTHETIC_ZERO_SPREAD") == "1":
        r = int(1e21)
        sim = simulate_offensive(r, r, victim, frontrun, network_fee_wei=network_fee * 100)
        payload = {
            "chain_id": 56,
            "mode": "synthetic_zero_spread",
            "sandwich_sim": sim,
            "skipped": not sim["should_execute"],
        }
        out = ROOT / "artifacts" / "sandbox" / "mev-bsc-fork-result.json"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 0

    try:
        chain = cast("chain-id")
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"[fork] RPC unavailable: {exc}", file=sys.stderr)
        payload = {"error": str(exc), "skipped": True, "skip_reason": "rpc_timeout"}
        out = ROOT / "artifacts" / "sandbox" / "mev-bsc-fork-result.json"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        return 0

    if chain != "56":
        print(f"[FAIL] BSC fork required, got chain {chain}", file=sys.stderr)
        return 1

    print(f"[fork] scanning pair {PANCAKE_PAIR} on BSC fork...")
    try:
        r0, r1 = get_reserves()
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        payload = {"error": str(exc), "skipped": True, "skip_reason": "rpc_timeout"}
        out = ROOT / "artifacts" / "sandbox" / "mev-bsc-fork-result.json"
        out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(payload, indent=2))
        return 0

    sim = simulate_offensive(r0, r1, victim, frontrun, network_fee)

    payload = {
        "chain_id": 56,
        "rpc": rpc_url(),
        "router": ROUTER,
        "wbnb": WBNB,
        "usdt": USDT,
        "pair": PANCAKE_PAIR,
        "reserves_raw": [r0, r1],
        "sandwich_sim": sim,
        "skipped": not sim["should_execute"],
        "builder_path": "puissant-builder.48.club (BSC)",
        "mode": "simulation_only",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    out = ROOT / "artifacts" / "sandbox" / "mev-bsc-fork-result.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if sim["should_execute"] else 0  # skip is success exit for fork sim


if __name__ == "__main__":
    raise SystemExit(main())
