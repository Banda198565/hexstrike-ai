"""Nonce inspection and pending sync helpers."""

from __future__ import annotations

from typing import Any, Callable


def fetch_nonces(rpc_call: Callable[..., dict[str, Any]], rpc: str, address: str) -> dict[str, Any]:
    addr = address if address.startswith("0x") else f"0x{address}"
    latest = int(rpc_call(rpc, "eth_getTransactionCount", [addr, "latest"])["result"], 16)
    pending = int(rpc_call(rpc, "eth_getTransactionCount", [addr, "pending"])["result"], 16)
    gap = pending - latest
    return {
        "address": addr,
        "nonce_latest": latest,
        "nonce_pending": pending,
        "pending_gap": gap,
        "stuck": gap > 0,
        "recommended_nonce": pending,
    }


def sync_recommendation(nonces: dict[str, Any]) -> dict[str, Any]:
    if not nonces.get("stuck"):
        return {"action": "ok", "use_nonce": nonces["nonce_pending"]}
    return {
        "action": "pending_tx_detected",
        "use_nonce": nonces["nonce_latest"],
        "note": "Wait for pending txs or bump gas on stuck tx before reusing nonce",
    }
