#!/usr/bin/env python3
"""Puissant/48.club builder dry-run simulation — no bundle submit."""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
ART = ROOT / "artifacts" / "sandbox"

PUISSANT_ENDPOINT = os.environ.get("PUISSANT_ENDPOINT", "https://puissant-builder.48.club/")
GAS_BUMP_STEPS = [int(x) for x in os.environ.get("BUILDER_GAS_BUMP_STEPS", "0,15,25").split(",") if x.strip()]


def simulate_bundle(
    *,
    gross_profit_wei: int,
    network_fee_wei: int,
    builder_tip_wei: int | None = None,
    victim_tx: str | None = None,
    attack_type: str = "sandwich",
) -> dict[str, Any]:
    tip = builder_tip_wei if builder_tip_wei is not None else int(
        os.environ.get("BUILDER_TIP_WEI", str(int(0.05e18)))
    )
    max_blocks = int(os.environ.get("BUILDER_MAX_WAIT_BLOCKS", "3"))

    attempts: list[dict[str, Any]] = []
    best_net = -(10**30)
    best: dict[str, Any] | None = None

    for bump in GAS_BUMP_STEPS:
        bump_cost = network_fee_wei * bump // 100 if bump > 0 else 0
        total_cost = network_fee_wei + tip + bump_cost
        net = gross_profit_wei - total_cost
        row = {
            "gas_bump_pct": bump,
            "network_fee_wei": network_fee_wei,
            "builder_tip_wei": tip,
            "bump_cost_wei": bump_cost,
            "gross_profit_wei": gross_profit_wei,
            "net_profit_wei": net,
            "would_submit": False,
        }
        if net > 0 and net > best_net:
            best_net = net
            best = row
        attempts.append(row)

    should_execute = best is not None and best["net_profit_wei"] > 0
    skip_reason = None
    if gross_profit_wei <= 0:
        skip_reason = "zero_or_negative_gross_spread"
    elif tip >= gross_profit_wei:
        skip_reason = "builder_tip_exceeds_gross"
    elif best is None or best["net_profit_wei"] <= 0:
        skip_reason = "builder_costs_exceed_profit"

    return {
        "endpoint": PUISSANT_ENDPOINT,
        "strategy": "private_bundle",
        "attack_type": attack_type,
        "victim_tx": victim_tx,
        "max_wait_blocks": max_blocks,
        "gas_bump_steps": GAS_BUMP_STEPS,
        "builder_tip_wei": tip,
        "attempts": attempts,
        "best_attempt": best,
        "should_execute": should_execute,
        "skip_reason": skip_reason,
        "would_submit": False,
        "simulation_only": True,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def load_sandwich_sim() -> dict[str, Any] | None:
    for name in ("mev-bsc-fork-result.json", "mev-live-pipeline-result.json"):
        path = ART / name
        if not path.is_file():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        sim = data.get("sandwich_sim") or data.get("best_opportunity", {}).get("sandwich_sim")
        if sim:
            return sim
    return None


def main() -> int:
    if os.environ.get("BUILDER_SIM_ONLY", "1") != "1":
        print("[FAIL] builder_sim requires BUILDER_SIM_ONLY=1", file=sys.stderr)
        return 1
    if os.environ.get("MEV_MAINNET_SUBMIT") == "1":
        print("[FAIL] MEV_MAINNET_SUBMIT blocked in builder_sim", file=sys.stderr)
        return 1

    sim = load_sandwich_sim()
    if not sim:
        gross = int(os.environ.get("BUILDER_GROSS_WEI", "0"))
        network = int(os.environ.get("FORK_NETWORK_FEE_WEI", str(210_000 * 3_000_000_000)))
        payload = simulate_bundle(gross_profit_wei=gross, network_fee_wei=network)
    else:
        payload = simulate_bundle(
            gross_profit_wei=int(sim.get("estimated_profit_wei", 0)),
            network_fee_wei=int(sim.get("network_fee_wei", 0)),
            victim_tx=sim.get("victim_tx"),
        )

    out = ART / "mev-builder-sim.json"
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
