#!/usr/bin/env python3
"""MCP: read-only EVM RPC tools (eth_call, balances, logs)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP

from lib.evm_client import EvmClient

mcp = FastMCP("evm-rpc-mcp")
client = EvmClient()


@mcp.tool()
def rpc_chain_id(rpc_url: str = "") -> dict:
    """Return chainId from RPC endpoint."""
    c = EvmClient(rpc_url) if rpc_url else client
    return {"chainId": int(c.rpc("eth_chainId", []), 16), "rpc": c.rpc_url}


@mcp.tool()
def get_balance(address: str, rpc_url: str = "") -> dict:
    """Native coin balance (BNB/ETH) for address."""
    c = EvmClient(rpc_url) if rpc_url else client
    wei = int(c.rpc("eth_getBalance", [address, "latest"]), 16)
    return {"address": address, "wei": wei, "native": wei / 1e18}


@mcp.tool()
def get_erc20_balance(token: str, holder: str, rpc_url: str = "") -> dict:
    """ERC20 balance via eth_call balanceOf."""
    c = EvmClient(rpc_url) if rpc_url else client
    meta = c.token_meta(token)
    bal = c.balance_of(token, holder, meta.get("decimals") or 18)
    return {"token": token, "holder": holder, "symbol": meta.get("symbol"), "balance": bal}


@mcp.tool()
def get_contract_code(address: str, rpc_url: str = "") -> dict:
    """Return contract bytecode length and EIP-7702 delegation if present."""
    c = EvmClient(rpc_url) if rpc_url else client
    code = c.get_code(address)
    out = {"address": address, "code_hex_len": max(0, len(code) - 2), "is_contract": code not in ("0x", "0x0")}
    if code.startswith("0xef0100") and len(code) >= 48:
        out["eip7702_delegation"] = "0x" + code[8:48]
    return out


@mcp.tool()
def eth_call_read(to: str, data: str, rpc_url: str = "") -> dict:
    """Raw eth_call (read-only). Pass hex calldata."""
    c = EvmClient(rpc_url) if rpc_url else client
    return {"to": to, "data": data, "result": c.eth_call(to, data)}


if __name__ == "__main__":
    mcp.run()
