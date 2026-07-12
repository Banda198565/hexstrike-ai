#!/usr/bin/env python3
"""MCP: on-chain graph + token verification (read-only, RPC-first)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

from lib.evm_client import EvmClient, OFFICIAL_USDT_BSC

mcp = FastMCP("block-explorer-mcp")
client = EvmClient()


@mcp.tool()
def get_token_transfers(
    address: str,
    token: str = OFFICIAL_USDT_BSC,
    direction: str = "both",
    blocks: int = 10000,
    min_amount: float = 0,
    rpc_url: str = "",
) -> dict:
    """Fetch ERC20 Transfer logs for address (read-only)."""
    c = EvmClient(rpc_url) if rpc_url else client
    report = c.get_token_transfers(token, address, direction, blocks, min_amount)
    for row in report.get("transfers", []):
        for k in ("from", "to"):
            row[f"{k}_label"] = c.label(row[k])
    return report


@mcp.tool()
def verify_erc20_token(
    token: str,
    expected_address: str = OFFICIAL_USDT_BSC,
    holder: str = "",
    rpc_url: str = "",
) -> dict:
    """Verify token contract metadata and detect flash/fake spam patterns."""
    c = EvmClient(rpc_url) if rpc_url else client
    meta = c.token_meta(token)
    code = c.get_code(token)
    is_official = token.lower() == expected_address.lower()
    pair = c.pancake_pair(token, "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c")
    holder_bal = c.balance_of(token, holder) if holder else None
    return {
        "token": token,
        "expected": expected_address,
        "matches_expected": is_official,
        "metadata": meta,
        "has_contract_code": code not in ("0x", "0x0"),
        "pancake_pair_wbnb": pair,
        "has_dex_liquidity": pair is not None,
        "holder_balance": holder_bal,
        "flash_fake_likely": not (meta.get("symbol") and meta.get("decimals") is not None and (pair or is_official)),
    }


@mcp.tool()
def get_contract_abi_stub(address: str, rpc_url: str = "") -> dict:
    """Return bytecode summary when verified ABI unavailable (read-only)."""
    c = EvmClient(rpc_url) if rpc_url else client
    code = c.get_code(address)
    impl = None
    if code.startswith("0xef0100") and len(code) >= 48:
        impl = "0x" + code[8:48]
    return {
        "address": address,
        "verified_abi": False,
        "note": "Use BscScan for verified source; this tool returns on-chain bytecode facts only.",
        "bytecode_bytes": max(0, len(code) - 2) // 2,
        "eip7702_implementation": impl,
        "bscscan": f"https://bscscan.com/address/{address}#code",
    }


@mcp.tool()
def address_graph_summary(address: str, token: str = OFFICIAL_USDT_BSC, blocks: int = 20000, rpc_url: str = "") -> dict:
    """Top in/out counterparties for address over block window."""
    c = EvmClient(rpc_url) if rpc_url else client
    from collections import Counter

    out = c.get_token_transfers(token, address, "out", blocks, 100)
    inn = c.get_token_transfers(token, address, "in", blocks, 100)
    out_c, in_c = Counter(), Counter()
    for row in out["transfers"]:
        out_c[row["to"].lower()] += row["amount"]
    for row in inn["transfers"]:
        in_c[row["from"].lower()] += row["amount"]
    return {
        "address": address,
        "blocks": blocks,
        "top_out": [{"address": a, "usdt": round(v, 2), "label": c.label(a)} for a, v in out_c.most_common(10)],
        "top_in": [{"address": a, "usdt": round(v, 2), "label": c.label(a)} for a, v in in_c.most_common(10)],
    }


if __name__ == "__main__":
    mcp.run()
