#!/usr/bin/env python3
"""MCP: DEX liquidity + flash-loan exposure heuristics (read-only)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

from lib.evm_client import EvmClient, OFFICIAL_USDT_BSC, WBNB_BSC, PANCAKE_FACTORY_V2

mcp = FastMCP("defi-dex-mcp")
client = EvmClient()

DEX_MARKERS = {
    "pancake_factory": "ca143ce32fe78f1f7019d7d551a6402fc5350c73",
    "pancake_router_v2": "10ed43c718714eb63d5a0b28607875659ef134",
}


@mcp.tool()
def check_dex_liquidity(
    token: str = OFFICIAL_USDT_BSC,
    quote: str = WBNB_BSC,
    rpc_url: str = "",
) -> dict:
    """Check PancakeSwap V2 pair existence and reserves."""
    c = EvmClient(rpc_url) if rpc_url else client
    pair = c.pancake_pair(token, quote)
    if not pair:
        return {"token": token, "quote": quote, "pair": None, "has_liquidity": False}
    r0, r1 = c.pair_reserves(pair)
    return {
        "token": token,
        "quote": quote,
        "factory": PANCAKE_FACTORY_V2,
        "pair": pair,
        "reserve0": r0,
        "reserve1": r1,
        "has_liquidity": (r0 + r1) > 0,
        "pancake_url": f"https://pancakeswap.finance/info/v2/pairs/{pair}",
    }


@mcp.tool()
def check_flashloan_exposure(contract: str, rpc_url: str = "") -> dict:
    """Heuristic: scan bytecode for DEX factory/router refs (oracle/flash-loan consumer signal)."""
    c = EvmClient(rpc_url) if rpc_url else client
    code = c.get_code(contract).lower()
    impl = None
    if code.startswith("0xef0100") and len(code) >= 48:
        impl = "0x" + code[8:48]
        code = c.get_code(impl).lower()
    hits = {name: (marker in code) for name, marker in DEX_MARKERS.items()}
    return {
        "contract": contract,
        "implementation": impl,
        "dex_markers": hits,
        "flash_loan_oracle_consumer_likely": any(hits.values()),
        "verdict": "If false: contract unlikely to use AMM spot price as oracle (flash-loan manipulation N/A at this layer).",
    }


if __name__ == "__main__":
    mcp.run()
