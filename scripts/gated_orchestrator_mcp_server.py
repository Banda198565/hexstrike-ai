#!/usr/bin/env python3
"""Gated Orchestrator MCP — read-only RPC + controlled filesystem for R1 transport layer.

Tools enforce allowlists from config/gated-mcp.json. No eth_sendTransaction, no source edits by default.

Usage:
  python3 scripts/gated_orchestrator_mcp_server.py
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

from hexstrike.mcp import gated_fs_runner as fs
from hexstrike.mcp import gated_rpc_runner as rpc

mcp = FastMCP("gated_orchestrator_mcp")


def _out(result: dict, tool: str) -> str:
    result.setdefault("tool", tool)
    result.setdefault("gated", True)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def rpc_get_block(chain: str, block_number: str = "latest") -> str:
    """Read-only block metadata (eth_getBlockByNumber). Keys from MCP env only."""
    return _out(rpc.rpc_get_block(chain, block_number), "rpc_get_block")


@mcp.tool()
def rpc_get_contract_state(
    chain: str,
    address: str,
    slot_keys: list[str],
    abi: Optional[str] = None,
) -> str:
    """Read-only contract storage slots (eth_getStorageAt). No writes."""
    return _out(rpc.rpc_get_contract_state(chain, address, slot_keys, abi=abi), "rpc_get_contract_state")


@mcp.tool()
def rpc_get_events(
    chain: str,
    address: str,
    from_block: str,
    to_block: str,
    topics: Optional[list[str]] = None,
) -> str:
    """Read-only event logs (eth_getLogs) with server-side block range cap."""
    return _out(
        rpc.rpc_get_events(chain, address, from_block, to_block, topics=topics),
        "rpc_get_events",
    )


@mcp.tool()
def rpc_trace_transaction(
    chain: str,
    tx_hash: str,
    trace_type: str = "call",
) -> str:
    """Read-only transaction trace (debug_traceTransaction when RPC supports it)."""
    return _out(rpc.rpc_trace_transaction(chain, tx_hash, trace_type=trace_type), "rpc_trace_transaction")


@mcp.tool()
def rpc_simulate_call(
    chain: str,
    to: str,
    data: str = "0x",
    from_address: str = "0x0000000000000000000000000000000000000000",
    value: str = "0x0",
) -> str:
    """Read-only eth_call simulation — never broadcasts transactions."""
    return _out(
        rpc.rpc_simulate_call(chain, to, data=data, from_address=from_address, value=value),
        "rpc_simulate_call",
    )


@mcp.tool()
def fs_list_dir(path: str) -> str:
    """List directory under allowlisted read roots — no writes."""
    return _out(fs.fs_list_dir(path), "fs_list_dir")


@mcp.tool()
def fs_read_file(path: str) -> str:
    """Read file from allowlisted paths — contracts/, config/, reports/, etc."""
    return _out(fs.fs_read_file(path), "fs_read_file")


@mcp.tool()
def fs_create_report_file(
    directory: str,
    filename: str,
    content: str,
    overwrite: bool = False,
) -> str:
    """Create audit report in reports/ or artifacts/web3-audit/ only. overwrite=false by default."""
    return _out(
        fs.fs_create_report_file(directory, filename, content, overwrite=overwrite),
        "fs_create_report_file",
    )


@mcp.tool()
def fs_read_report_index(directory: str = "reports") -> str:
    """List existing reports in allowlisted directory."""
    return _out(fs.fs_read_report_index(directory), "fs_read_report_index")


@mcp.tool()
def fs_edit_file(
    path: str,
    original_snippet: str,
    new_snippet: str,
    dry_run: bool = True,
) -> str:
    """Preview file edit diff — dry_run=true by default; apply requires HEXSTRIKE_FS_APPLY=1."""
    return _out(
        fs.fs_edit_file(path, original_snippet, new_snippet, dry_run=dry_run),
        "fs_edit_file",
    )


@mcp.tool()
def gated_mcp_status() -> str:
    """Return gated MCP allowlists and RPC env status (no secrets)."""
    from hexstrike.mcp.web3_rpc_runner import detect_rpc_config

    cfg_path = ROOT / "config" / "gated-mcp.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.is_file() else {}
    return _out(
        {
            "success": True,
            "config_path": str(cfg_path.relative_to(ROOT)),
            "rpc_tools": [
                "rpc_get_block",
                "rpc_get_contract_state",
                "rpc_get_events",
                "rpc_trace_transaction",
                "rpc_simulate_call",
            ],
            "fs_tools": [
                "fs_list_dir",
                "fs_read_file",
                "fs_create_report_file",
                "fs_read_report_index",
                "fs_edit_file",
            ],
            "forbidden_rpc": cfg.get("rpc", {}).get("forbidden_methods"),
            "read_roots": cfg.get("filesystem", {}).get("read_roots"),
            "write_roots": cfg.get("filesystem", {}).get("write_roots"),
            "rpc_env": detect_rpc_config(),
        },
        "gated_mcp_status",
    )


if __name__ == "__main__":
    mcp.run()
