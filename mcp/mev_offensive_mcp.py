#!/usr/bin/env python3
"""MCP: read-only MEV offensive tools (mempool scan, fork PnL, builder sim)."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

ROOT = Path(__file__).resolve().parents[1]
MEV_DIR = ROOT / "scripts" / "sandbox" / "mev"
ART = ROOT / "artifacts" / "sandbox"

sys.path.insert(0, str(MEV_DIR))

from builder_sim import load_sandwich_sim, simulate_bundle  # noqa: E402
from fork_mempool import PANCAKE_ROUTER, scan_mempool  # noqa: E402
from fork_offensive import get_reserves  # noqa: E402
from mempool_live import scan_live_mempool  # noqa: E402
from offensive_pipeline import run_pipeline  # noqa: E402
from hot_wallet_watch import run_watch  # noqa: E402

mcp = FastMCP("mev-offensive-mcp")


def _sandbox_gate() -> dict[str, str] | None:
    if os.environ.get("MEV_SANDBOX_ONLY", "1") != "1":
        return {"error": "MEV_SANDBOX_ONLY must be 1 (read-only sandbox)"}
    if os.environ.get("MEV_MAINNET_SUBMIT") == "1":
        return {"error": "MEV_MAINNET_SUBMIT is blocked"}
    return None


def _write_artifact(name: str, payload: dict[str, Any]) -> str:
    ART.mkdir(parents=True, exist_ok=True)
    path = ART / name
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return str(path)


@mcp.tool()
def scan_live_mempool_tool(block_depth: int = 5) -> dict[str, Any]:
    """Scan live BSC mempool for Pancake swap candidates (read-only, multi-RPC failover)."""
    gate = _sandbox_gate()
    if gate:
        return gate
    os.environ.setdefault("MEV_MEMPOOL_BLOCK_DEPTH", str(block_depth))
    payload = scan_live_mempool()
    path = _write_artifact("mev-live-mempool-scan.json", payload)
    return {"artifact": path, **payload}


@mcp.tool()
def scan_fork_mempool_tool(rpc_url: str = "") -> dict[str, Any]:
    """Scan fork/local RPC mempool (txpool or pending block) for swap candidates."""
    gate = _sandbox_gate()
    if gate:
        return gate
    if rpc_url:
        os.environ["MEV_RPC_URL"] = rpc_url
    payload = scan_mempool(rpc_url or None)
    path = _write_artifact("mev-bsc-mempool-scan.json", payload)
    return {"artifact": path, **payload}


@mcp.tool()
def get_fork_reserves_tool(rpc_url: str = "", pair: str = "") -> dict[str, Any]:
    """Read Pancake V2 pair reserves from fork or BSC RPC (eth_call getReserves)."""
    gate = _sandbox_gate()
    if gate:
        return gate
    if rpc_url:
        os.environ["MEV_RPC_URL"] = rpc_url
    if pair:
        os.environ["BSC_PAIR"] = pair
    reserve_eth, reserve_token = get_reserves()
    payload = {
        "pair": pair or os.environ.get("BSC_PAIR", "0x16b9a82891338f9ba80e2d6970fdda79d1eb0dae"),
        "rpc": os.environ.get("MEV_RPC_URL", "http://127.0.0.1:8545"),
        "reserve_eth": reserve_eth,
        "reserve_token": reserve_token,
        "router": PANCAKE_ROUTER,
        "simulation_only": True,
    }
    path = _write_artifact("mev-fork-reserves.json", payload)
    return {"artifact": path, **payload}


@mcp.tool()
def builder_sim_dry_run(
    gross_profit_wei: int = 0,
    network_fee_wei: int = 630_000_000_000_000,
    builder_tip_wei: int | None = None,
) -> dict[str, Any]:
    """Puissant/48.club builder dry-run — never submits bundles (would_submit=false)."""
    gate = _sandbox_gate()
    if gate:
        return gate
    os.environ["BUILDER_SIM_ONLY"] = "1"
    sim = load_sandwich_sim()
    if sim:
        payload = simulate_bundle(
            gross_profit_wei=int(sim.get("estimated_profit_wei", 0)),
            network_fee_wei=int(sim.get("network_fee_wei", network_fee_wei)),
            builder_tip_wei=builder_tip_wei,
            victim_tx=sim.get("victim_tx"),
        )
    else:
        payload = simulate_bundle(
            gross_profit_wei=gross_profit_wei,
            network_fee_wei=network_fee_wei,
            builder_tip_wei=builder_tip_wei,
        )
    path = _write_artifact("mev-builder-sim.json", payload)
    return {"artifact": path, **payload}


@mcp.tool()
def watch_hot_wallet_mempool(
    block_depth: int = 20,
    watch_addresses: str = "",
) -> dict[str, Any]:
    """Live alerts on hot-wallet outgoing USDT + pending native txs (read-only)."""
    gate = _sandbox_gate()
    if gate:
        return gate
    os.environ.setdefault("HOT_WATCH_BLOCK_DEPTH", str(block_depth))
    os.environ.setdefault("HOT_WATCH_ONCE", "1")
    if watch_addresses.strip():
        os.environ["HOT_WALLET_WATCH"] = watch_addresses.strip()
    payload = run_watch(once=True)
    path = _write_artifact("hot-wallet-watch.json", payload)
    return {"artifact": path, **payload}


@mcp.tool()
def run_offensive_pipeline_tool(use_fork: bool = True) -> dict[str, Any]:
    """Full pipeline: live mempool → fork PnL classify → builder sim (read-only)."""
    gate = _sandbox_gate()
    if gate:
        return gate
    os.environ["PIPELINE_USE_FORK"] = "1" if use_fork else "0"
    os.environ["BUILDER_SIM_ONLY"] = "1"
    result = run_pipeline()
    path = _write_artifact("mev-live-pipeline-result.json", result)
    return {"artifact": path, **result}


if __name__ == "__main__":
    mcp.run()
