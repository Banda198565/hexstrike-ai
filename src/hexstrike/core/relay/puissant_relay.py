"""Puissant eth_sendBundle + public RPC fallback (Python path)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class RelayResult:
    success: bool
    strategy: str
    tx_hash: str | None = None
    bundle_hash: str | None = None
    rpc: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "strategy": self.strategy,
            "hash": self.tx_hash,
            "bundle_hash": self.bundle_hash,
            "rpc": self.rpc,
            "error": self.error,
        }


class PuissantRelay:
    def __init__(self) -> None:
        self.builder_url = os.environ.get("PUISSANT_BUILDER_URL", "https://puissant-builder.48.club/")
        self.public_rpc = os.environ.get("RELAY_PUBLIC_RPC") or os.environ.get("RPC_URL", "")
        self.allow_public_fallback = os.environ.get("RELAY_ALLOW_PUBLIC", "1").lower() in ("1", "true", "yes")

    def _post_json(self, url: str, payload: dict[str, Any], timeout: float = 12.0) -> dict[str, Any]:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_bundle(self, raw_hex: str, *, max_block_number: int | None = None) -> RelayResult:
        if not raw_hex.startswith("0x"):
            raw_hex = "0x" + raw_hex
        params: dict[str, Any] = {"txs": [raw_hex]}
        if max_block_number:
            params["maxBlockNumber"] = max_block_number
        try:
            out = self._post_json(self.builder_url, {
                "jsonrpc": "2.0",
                "id": "hexstrike",
                "method": "eth_sendBundle",
                "params": [params],
            })
            if out.get("error"):
                return RelayResult(False, "private_bundle", error=str(out["error"]))
            bundle_hash = out.get("result")
            if isinstance(bundle_hash, str):
                bundle_hash = bundle_hash.strip('"')
            return RelayResult(True, "private_bundle", bundle_hash=str(bundle_hash))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return RelayResult(False, "private_bundle", error=str(exc))

    def send_public(self, raw_hex: str) -> RelayResult:
        if not self.public_rpc:
            return RelayResult(False, "public_mempool", error="RPC_URL not set")
        if not raw_hex.startswith("0x"):
            raw_hex = "0x" + raw_hex
        try:
            out = self._post_json(self.public_rpc, {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "eth_sendRawTransaction",
                "params": [raw_hex],
            })
            if out.get("error"):
                return RelayResult(False, "public_mempool", error=str(out["error"]), rpc=self.public_rpc)
            return RelayResult(True, "public_mempool", tx_hash=out.get("result"), rpc=self.public_rpc)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            return RelayResult(False, "public_mempool", error=str(exc), rpc=self.public_rpc)

    def submit(self, raw_hex: str, *, prefer_private: bool = True, public_fallback: bool | None = None) -> RelayResult:
        fallback = self.allow_public_fallback if public_fallback is None else public_fallback
        if prefer_private and os.environ.get("RELAY_STRATEGY", "private_first").lower() != "public_only":
            bundle = self.send_bundle(raw_hex)
            if bundle.success:
                return bundle
            if not fallback:
                return bundle
        return self.send_public(raw_hex)


class RelayManager:
    """Unified relay entry for agents."""

    def __init__(self) -> None:
        self.puissant = PuissantRelay()

    def broadcast(self, raw_hex: str, *, strategy: str = "private_first") -> dict[str, Any]:
        if strategy == "public_only":
            result = self.puissant.send_public(raw_hex)
        elif strategy == "private_only":
            result = self.puissant.submit(raw_hex, prefer_private=True, public_fallback=False)
        else:
            result = self.puissant.submit(raw_hex, prefer_private=True, public_fallback=True)
        out = result.to_dict()
        if result.success and not out.get("hash"):
            out["hash"] = self._hash_from_raw(raw_hex)
        return out

    @staticmethod
    def _hash_from_raw(raw_hex: str) -> str | None:
        return None
