#!/usr/bin/env python3
"""Live BSC mempool ingest — read-only multi-RPC (no tx submit)."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from fork_mempool import PANCAKE_ROUTER, is_swap_candidate, normalize_candidate

ROOT = Path(__file__).resolve().parents[3]
ART = ROOT / "artifacts" / "sandbox"

DEFAULT_RPCS = [
    "https://bsc-dataseed.binance.org",
    "https://bsc-dataseed1.binance.org",
    "https://bsc-dataseed2.binance.org",
    "https://rpc.ankr.com/bsc",
]


def rpc_urls() -> list[str]:
    urls: list[str] = []
    for key in ("BSC_HTTP_URL", "BSC_HTTP_FALLBACK", "BSC_HTTP_FALLBACK_2"):
        v = os.environ.get(key, "").strip()
        if v and v not in urls:
            urls.append(v)
    for u in DEFAULT_RPCS:
        if u not in urls:
            urls.append(u)
    # Local fork RPC only when explicitly requested
    if os.environ.get("MEV_LIVE_USE_LOCAL_RPC") == "1":
        v = os.environ.get("MEV_RPC_URL", "").strip()
        if v and v not in urls:
            urls.insert(0, v)
    return urls


def _rpc(url: str, method: str, params: list[Any], timeout: float = 8) -> Any:
    body = json.dumps({"jsonrpc": "2.0", "method": method, "params": params, "id": 1}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    return payload.get("result")


def chain_id(url: str) -> int:
    raw = _rpc(url, "eth_chainId", [])
    return int(raw, 16) if isinstance(raw, str) else int(raw)


def try_pending_filter(url: str, *, polls: int = 3, interval: float = 0.5) -> list[dict[str, Any]]:
    """eth_newPendingTransactionFilter + getFilterChanges (when supported)."""
    try:
        filt = _rpc(url, "eth_newPendingTransactionFilter", [])
    except Exception:
        return []
    if not filt:
        return []
    hits: list[dict[str, Any]] = []
    router = PANCAKE_ROUTER.lower()
    min_wei = int(os.environ.get("MIN_VICTIM_WEI", str(int(0.1e18))))
    try:
        for _ in range(polls):
            time.sleep(interval)
            hashes = _rpc(url, "eth_getFilterChanges", [filt]) or []
            for h in hashes[: int(os.environ.get("MEV_MEMPOOL_MAX_CANDIDATES", "50"))]:
                if not isinstance(h, str):
                    continue
                try:
                    tx = _rpc(url, "eth_getTransactionByHash", [h])
                except Exception:
                    continue
                if not isinstance(tx, dict) or not is_swap_candidate(tx, router=router):
                    continue
                if int(tx.get("value", "0x0"), 16) < min_wei:
                    continue
                hits.append(normalize_candidate(tx, 56))
    finally:
        try:
            _rpc(url, "eth_uninstallFilter", [filt])
        except Exception:
            pass
    return hits


def scan_pending_block(url: str) -> list[dict[str, Any]]:
    try:
        block = _rpc(url, "eth_getBlockByNumber", ["pending", True])
    except Exception:
        return []
    if not isinstance(block, dict):
        return []
    router = PANCAKE_ROUTER.lower()
    min_wei = int(os.environ.get("MIN_VICTIM_WEI", str(int(0.1e18))))
    hits: list[dict[str, Any]] = []
    for tx in block.get("transactions") or []:
        if not isinstance(tx, dict) or not is_swap_candidate(tx, router=router):
            continue
        if int(tx.get("value", "0x0"), 16) < min_wei:
            continue
        hits.append(normalize_candidate(tx, 56))
    return hits


def scan_recent_blocks(url: str, *, depth: int | None = None) -> list[dict[str, Any]]:
    """Fallback: Pancake router swaps in last N mined blocks."""
    depth = depth or int(os.environ.get("MEV_MEMPOOL_BLOCK_DEPTH", "5"))
    latest_hex = _rpc(url, "eth_blockNumber", [])
    latest = int(latest_hex, 16)
    router = PANCAKE_ROUTER.lower()
    min_wei = int(os.environ.get("MIN_VICTIM_WEI", str(int(0.1e18))))
    hits: list[dict[str, Any]] = []
    for i in range(depth):
        num = latest - i
        if num < 0:
            break
        block = _rpc(url, "eth_getBlockByNumber", [hex(num), True])
        if not isinstance(block, dict):
            continue
        for tx in block.get("transactions") or []:
            if not isinstance(tx, dict) or not is_swap_candidate(tx, router=router):
                continue
            if int(tx.get("value", "0x0"), 16) < min_wei:
                continue
            row = normalize_candidate(tx, 56)
            row["source_block"] = num
            row["mode"] = "recent_blocks"
            hits.append(row)
    return hits


def scan_live_mempool() -> dict[str, Any]:
    """Multi-RPC live scan with failover."""
    errors: list[str] = []
    polls = int(os.environ.get("MEV_MEMPOOL_POLL_COUNT", "3"))
    interval = float(os.environ.get("MEV_MEMPOOL_POLL_MS", "500")) / 1000.0

    for url in rpc_urls():
        try:
            cid = chain_id(url)
            if cid != 56:
                errors.append(f"{url}: chain={cid}")
                continue

            merged: list[dict[str, Any]] = []
            mode = "pending_filter"
            merged.extend(try_pending_filter(url, polls=polls, interval=interval))
            if not merged:
                mode = "pending_block"
                merged.extend(scan_pending_block(url))
            if not merged:
                mode = "recent_blocks"
                merged.extend(scan_recent_blocks(url))

            seen: set[str] = set()
            deduped: list[dict[str, Any]] = []
            for row in merged:
                h = (row.get("hash") or "").lower()
                if h and h in seen:
                    continue
                if h:
                    seen.add(h)
                deduped.append(row)

            return {
                "rpc": url,
                "chain_id": 56,
                "router_filter": PANCAKE_ROUTER,
                "mode": mode,
                "candidate_count": len(deduped),
                "candidates": deduped[: int(os.environ.get("MEV_MEMPOOL_MAX_CANDIDATES", "50"))],
                "errors": errors,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        except Exception as exc:
            errors.append(f"{url}: {exc}")
            continue

    return {
        "rpc": None,
        "chain_id": 56,
        "mode": "failed",
        "candidate_count": 0,
        "candidates": [],
        "errors": errors,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main() -> int:
    if os.environ.get("MEV_SANDBOX_ONLY", "1") != "1":
        print("[FAIL] live mempool is sandbox read-only", file=sys.stderr)
        return 1
    if os.environ.get("MEV_MAINNET_SUBMIT") == "1":
        print("[FAIL] MEV_MAINNET_SUBMIT forbidden for mempool_live", file=sys.stderr)
        return 1

    payload = scan_live_mempool()
    out = ART / "mev-live-mempool-scan.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(
        f"[live] mode={payload.get('mode')} candidates={payload.get('candidate_count')} "
        f"rpc={payload.get('rpc')} → {out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
