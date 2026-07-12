#!/usr/bin/env python3
"""BSC fork offensive MEV — real pools/prices, simulation only (no mainnet submit)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

# BSC mainnet PancakeSwap V2 WBNB/USDT pair (read-only quotes)
PANCAKE_PAIR = os.environ.get(
    "BSC_PAIR", "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae"
)
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2e08d91793bc095c"
USDT = "0x55d398326f99059fF775485246999027B3197955"
ROUTER = "0x10ED43C718714eb63d5aB7E8d58b0B6B0a0b54852"


def rpc_url() -> str:
    return os.environ.get("MEV_RPC_URL", "http://127.0.0.1:8545")


def cast(*args: str) -> str:
    proc = subprocess.run(
        ["cast", *args, "--rpc-url", rpc_url()],
        capture_output=True,
        text=True,
        check=False,
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


def cp_out(amount_in: int, reserve_in: int, reserve_out: int) -> int:
    if amount_in <= 0:
        return 0
    num = amount_in * reserve_out
    den = reserve_in + amount_in
    return num // den


def sandwich_pnl_fork(victim_bnb_wei: int, frontrun_bnb_wei: int) -> dict:
    r0, r1 = get_reserves()
    # Assume token0=WBNB token1=USDT (verify on fork)
    eth_res, tok_res = r0, r1

    fr_out = cp_out(frontrun_bnb_wei, eth_res, tok_res)
    eth_res += frontrun_bnb_wei
    tok_res -= fr_out

    vic_out = cp_out(victim_bnb_wei, eth_res, tok_res)
    eth_res += victim_bnb_wei
    tok_res -= vic_out

    eth_back = cp_out(fr_out, tok_res, eth_res)
    profit = eth_back - frontrun_bnb_wei

    return {
        "pair": PANCAKE_PAIR,
        "reserves_eth": eth_res,
        "reserves_token": tok_res,
        "victim_bnb_wei": victim_bnb_wei,
        "frontrun_bnb_wei": frontrun_bnb_wei,
        "estimated_profit_wei": profit,
        "profitable": profit > 0,
    }


def main() -> int:
    chain = cast("chain-id")
    if chain != "56":
        print(f"[FAIL] BSC fork required, got chain {chain}", file=sys.stderr)
        return 1

    victim = int(float(os.environ.get("FORK_VICTIM_BNB", "5")) * 1e18)
    frontrun = int(float(os.environ.get("FORK_FRONTRUN_BNB", "1")) * 1e18)

    print(f"[fork] scanning pair {PANCAKE_PAIR} on BSC fork...")
    r0, r1 = get_reserves()
    sim = sandwich_pnl_fork(victim, frontrun)

    payload = {
        "chain_id": 56,
        "rpc": rpc_url(),
        "router": ROUTER,
        "wbnb": WBNB,
        "usdt": USDT,
        "pair": PANCAKE_PAIR,
        "reserves_raw": [r0, r1],
        "sandwich_sim": sim,
        "builder_path": "puissant-builder.48.club (BSC)",
        "mode": "simulation_only",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    out = ROOT / "artifacts" / "sandbox" / "mev-bsc-fork-result.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0 if sim["profitable"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
