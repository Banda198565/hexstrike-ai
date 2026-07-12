#!/usr/bin/env python3
"""BSC fork mempool helpers — seed pending swaps and classify candidates."""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]

# PancakeSwap V2 (BSC mainnet addresses — valid on fork)
PANCAKE_ROUTER = os.environ.get(
    "BSC_ROUTER", "0x10ED43C718714eb63d5aA57B78B54704E256024E"
)
WBNB = "0xbb4CdB9CBd36B01bD1cBaEBF2De08d9173bc095c"
USDT = "0x55d398326f99059fF775485246999027B3197955"

# Uniswap V2 / Pancake router swap selectors (ETH/BNB in)
SWAP_SELECTORS = {
    "7ff36ab5": "swapExactETHForTokens",
    "b6f9de95": "swapExactETHForTokensSupportingFeeOnTransferTokens",
    "18cbafe5": "swapExactTokensForETH",
    "38ed1739": "swapExactTokensForTokens",
    "fb3bdb41": "swapETHForExactTokens",
    "791ac947": "swapExactTokensForETHSupportingFeeOnTransferTokens",
}

MNEMONIC = os.environ.get(
    "ANVIL_MNEMONIC", "test test test test test test test test test test test junk"
)


def rpc_url() -> str:
    return os.environ.get("MEV_RPC_URL", "http://127.0.0.1:8545")


def _cast(*args: str, timeout: float = 30) -> str:
    proc = subprocess.run(
        ["cast", *args, "--rpc-url", rpc_url()],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def _rpc(method: str, params: list[Any]) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    import urllib.request

    req = urllib.request.Request(
        rpc_url(), data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        payload = json.loads(resp.read())
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return payload.get("result")


def wallet(index: int) -> tuple[str, str]:
    addr = subprocess.run(
        ["cast", "wallet", "address", "--mnemonic", MNEMONIC, "--mnemonic-index", str(index)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    key = subprocess.run(
        ["cast", "wallet", "private-key", "--mnemonic", MNEMONIC, "--mnemonic-index", str(index)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    return addr, key


def is_swap_candidate(tx: dict[str, Any], *, router: str | None = None) -> bool:
    if not isinstance(tx, dict):
        return False
    value = int(tx.get("value", "0x0"), 16) if isinstance(tx.get("value"), str) else int(tx.get("value") or 0)
    data = tx.get("input") or tx.get("data") or "0x"
    if len(data) < 10:
        return False
    sel = data[2:10].lower()
    if sel not in SWAP_SELECTORS:
        return False
    # BNB-in swaps need value; token swaps may have value=0
    if sel in ("7ff36ab5", "b6f9de95", "fb3bdb41") and value <= 0:
        return False
    to_addr = (tx.get("to") or "").lower()
    if router and to_addr and to_addr != router.lower():
        return False
    return True


def normalize_candidate(tx: dict[str, Any], chain_id: int | str) -> dict[str, Any]:
    data = tx.get("input") or tx.get("data") or "0x"
    sel = data[2:10].lower()
    value = int(tx.get("value", "0x0"), 16) if isinstance(tx.get("value"), str) else int(tx.get("value") or 0)
    return {
        "hash": tx.get("hash"),
        "from": tx.get("from"),
        "to": tx.get("to"),
        "value_wei": value,
        "selector": "0x" + sel,
        "selector_name": SWAP_SELECTORS.get(sel, "unknown"),
        "chain_id": int(chain_id) if str(chain_id).isdigit() else chain_id,
        "gas_price_wei": int(tx.get("gasPrice", "0x0"), 16)
        if isinstance(tx.get("gasPrice"), str)
        else int(tx.get("gasPrice") or 0),
    }


def scan_txpool_content(url: str, *, router: str | None = None) -> list[dict[str, Any]]:
    """Anvil exposes txpool_content — richer than pending block on forks."""
    try:
        pool = _rpc("txpool_content", [])
    except Exception:
        return []
    if not isinstance(pool, dict):
        return []

    chain = _rpc("eth_chainId", [])
    chain_id = int(chain, 16) if isinstance(chain, str) else chain
    router_l = router.lower() if router else None
    hits: list[dict[str, Any]] = []
    for section in ("pending", "queued"):
        bucket = pool.get(section) or {}
        if not isinstance(bucket, dict):
            continue
        for _sender, by_nonce in bucket.items():
            if not isinstance(by_nonce, dict):
                continue
            for _nonce, tx in by_nonce.items():
                if not is_swap_candidate(tx, router=router_l):
                    continue
                hits.append(normalize_candidate(tx, chain_id))
    return hits


def scan_pending_block(url: str, *, router: str | None = None) -> list[dict[str, Any]]:
    try:
        block = _rpc("eth_getBlockByNumber", ["pending", True])
    except Exception as exc:
        return [{"error": str(exc)}]
    if not isinstance(block, dict):
        return []
    chain = _rpc("eth_chainId", [])
    chain_id = int(chain, 16) if isinstance(chain, str) else chain
    router_l = router.lower() if router else None
    hits: list[dict[str, Any]] = []
    for tx in block.get("transactions") or []:
        if not isinstance(tx, dict):
            continue
        if not is_swap_candidate(tx, router=router_l):
            continue
        hits.append(normalize_candidate(tx, chain_id))
    return hits


def scan_mempool(url: str | None = None, *, chain_id: int | None = None) -> dict[str, Any]:
    """Unified mempool scan — txpool first, then pending block."""
    url = url or rpc_url()
    router = PANCAKE_ROUTER if chain_id == 56 else os.environ.get("MEV_ROUTER_FILTER")

    txpool_hits = scan_txpool_content(url, router=router)
    pending_hits = scan_pending_block(url, router=router)

    # Dedupe by hash
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for hit in txpool_hits + pending_hits:
        if hit.get("error"):
            merged.append(hit)
            continue
        h = (hit.get("hash") or "").lower()
        if h and h in seen:
            continue
        if h:
            seen.add(h)
        merged.append(hit)

    return {
        "rpc": url,
        "chain_id": chain_id,
        "router_filter": router,
        "source": "txpool_content+pending",
        "candidates": merged,
    }


def build_swap_calldata(amount_out_min: int = 0, deadline: int | None = None) -> str:
    if deadline is None:
        deadline = int(time.time()) + 3600
    victim = wallet(3)[0]
    path = f"[{WBNB},{USDT}]"
    proc = subprocess.run(
        [
            "cast",
            "calldata",
            "swapExactETHForTokens(uint256,address[],address,uint256)",
            str(amount_out_min),
            path,
            victim,
            str(deadline),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def seed_pending_swaps(count: int = 3) -> list[str]:
    """Queue Pancake BNB→USDT swaps in mempool (anvil_setAutomine false)."""
    victim, victim_key = wallet(3)
    _cast("rpc", "anvil_setBalance", victim, hex(int(50e18)))
    _cast("rpc", "anvil_setAutomine", "false")

    amounts = [
        int(os.environ.get("FORK_SEED_VICTIM_1_WEI", str(int(5e18)))),
        int(os.environ.get("FORK_SEED_VICTIM_2_WEI", str(int(2e18)))),
        int(os.environ.get("FORK_SEED_VICTIM_3_WEI", str(int(0.5e18)))),
    ][:count]

    tx_hashes: list[str] = []
    victim_addr = victim
    deadline = int(time.time()) + 3600
    path = f"[{WBNB},{USDT}]"
    for i, wei in enumerate(amounts):
        gas_price = 1_000_000_000 + i * 500_000_000  # 1–2 gwei stagger
        out = subprocess.run(
            [
                "cast",
                "send",
                PANCAKE_ROUTER,
                "swapExactETHForTokens(uint256,address[],address,uint256)",
                "0",
                path,
                victim_addr,
                str(deadline),
                "--value",
                str(wei),
                "--private-key",
                victim_key,
                "--gas-price",
                str(gas_price),
                "--async",
                "--rpc-url",
                rpc_url(),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or out.stdout.strip() or "cast send failed")
        line = out.stdout + out.stderr
        for token in line.split():
            if token.startswith("0x") and len(token) == 66:
                tx_hashes.append(token)
                break

    return tx_hashes


def flush_mempool() -> None:
    """Re-enable automine and clear queued pending txs."""
    try:
        _cast("rpc", "anvil_setAutomine", "true")
        _cast("rpc", "anvil_mine", "1")
    except RuntimeError:
        pass
