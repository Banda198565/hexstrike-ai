#!/usr/bin/env python3
"""HexStrike Web3 RPC MCP Server — read-only JSON-RPC with env-injected keys.

RPC credentials live in MCP server env (mcp.json `env` block), NOT in agent prompts:
  WEB3_RPC_URL, WEB3_RPC_KEY
  WEB3_RPC_URL_MAINNET, WEB3_RPC_KEY_POLYGON, etc.

Tools:
  - detect_rpc_config
  - rpc_contract_audit
  - rpc_tx_trace
  - rpc_wallet_risk
  - rpc_event_intel

Usage:
  python3 scripts/web3_rpc_mcp_server.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mcp.server.fastmcp import FastMCP

from hexstrike.mcp import web3_rpc_runner as wrr

mcp = FastMCP("web3_rpc_mcp")


def _maybe_trace(tool: str, input_data: dict, output: dict) -> None:
    trace_id = os.environ.get("HEXSTRIKE_TRACE_ID", "").strip()
    if not trace_id:
        return
    try:
        log_path = ROOT / "artifacts" / "workflow" / "traces" / f"{trace_id}.json"
        if not log_path.is_file():
            return
        data = json.loads(log_path.read_text(encoding="utf-8"))
        seq = len(data.get("steps", [])) + 1
        data.setdefault("steps", []).append(
            {
                "seq": seq,
                "tool": tool,
                "tool_kind": "mcp",
                "phase": "web3_rpc",
                "input": input_data,
                "output": {
                    "success": output.get("success"),
                    "finding_count": output.get("finding_count")
                    or output.get("suspicious_step_count")
                    or output.get("log_count"),
                    "raw_report_path": output.get("raw_report_path"),
                },
                "status": "success" if output.get("success") else "failed",
            }
        )
        log_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


def _dump(result: dict, tool: str, inp: dict) -> str:
    _maybe_trace(tool, inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def detect_rpc_config() -> str:
    """Check WEB3_RPC_URL/WEB3_RPC_KEY env — redacted URLs only, never exposes keys."""
    return json.dumps(wrr.detect_rpc_config(), ensure_ascii=False)


@mcp.tool()
def rpc_contract_audit(address: str, chain: str = "mainnet") -> str:
    """Read-only contract audit by address: bytecode, proxy, dangerous opcodes."""
    inp = {"address": address, "chain": chain}
    return _dump(wrr.rpc_contract_audit(address, chain=chain), "rpc_contract_audit", inp)


@mcp.tool()
def rpc_tx_trace(tx_hash: str, chain: str = "mainnet") -> str:
    """Read-only tx trace/receipt analysis — delegatecall/revert pattern flags."""
    inp = {"tx_hash": tx_hash[:18] + "...", "chain": chain}
    return _dump(wrr.rpc_tx_trace(tx_hash, chain=chain), "rpc_tx_trace", inp)


@mcp.tool()
def rpc_wallet_risk(address: str, chain: str = "mainnet") -> str:
    """Read-only wallet/address risk triage — contract vs EOA, heuristic flags."""
    inp = {"address": address, "chain": chain}
    return _dump(wrr.rpc_wallet_risk(address, chain=chain), "rpc_wallet_risk", inp)


@mcp.tool()
def rpc_event_intel(
    address: str,
    chain: str = "mainnet",
    topic: Optional[str] = None,
    from_block: str = "latest",
    to_block: str = "latest",
) -> str:
    """Read-only event log aggregation — Transfer spikes, log bursts."""
    inp = {"address": address, "chain": chain, "topic": topic, "from_block": from_block}
    return _dump(
        wrr.rpc_event_intel(
            address,
            chain=chain,
            topic=topic,
            from_block=from_block,
            to_block=to_block,
        ),
        "rpc_event_intel",
        inp,
    )


if __name__ == "__main__":
    mcp.run()
