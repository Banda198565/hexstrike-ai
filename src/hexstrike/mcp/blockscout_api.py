"""mcp_blockscout_api — multichain explorer API for depth-3 on-chain tracing."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import requests

from hexstrike.bus.context_bus import ContextBus
from hexstrike.core.stealth.transport import StealthConfig, StealthTransport

# Read-only explorer endpoints (Etherscan-compatible API)
_CHAIN_ENDPOINTS: dict[str, dict[str, str]] = {
    "ethereum": {
        "url": "https://api.etherscan.io/api",
        "key_env": "ETHERSCAN_API_KEY",
    },
    "bsc": {
        "url": "https://api.bscscan.com/api",
        "key_env": "BSCSCAN_API_KEY",
    },
    "base": {
        "url": "https://api.basescan.org/api",
        "key_env": "BASESCAN_API_KEY",
    },
}


@dataclass
class BlockscoutApiMcp:
    """Multichain explorer client — address info, transfers, depth-limited trace."""

    bus: ContextBus
    transport: StealthTransport = field(default_factory=lambda: StealthTransport(StealthConfig()))
    max_depth: int = 3

    def _api_call(self, chain: str, params: dict[str, Any]) -> dict[str, Any]:
        meta = _CHAIN_ENDPOINTS.get(chain)
        if not meta:
            return {"success": False, "error": f"unsupported_chain:{chain}"}

        api_key = os.environ.get(meta["key_env"], "")
        if not api_key:
            return {
                "success": False,
                "error": f"missing_api_key:{meta['key_env']}",
                "chain": chain,
                "note": "Read-only explorer queries require operator API key",
            }

        params = {**params, "apikey": api_key}
        self.transport._jitter()
        resp = self.transport._session.get(meta["url"], params=params, timeout=15)
        resp.raise_for_status()
        payload = resp.json()
        self.bus.publish(
            "mcp.blockscout.call",
            {"chain": chain, "module": params.get("module"), "action": params.get("action")},
            source="mcp_blockscout_api",
        )
        return payload

    def address_summary(self, address: str, chain: str = "ethereum") -> dict[str, Any]:
        """Balance + tx count for an address."""
        balance = self._api_call(
            chain,
            {"module": "account", "action": "balance", "address": address, "tag": "latest"},
        )
        tx_count = self._api_call(
            chain,
            {"module": "proxy", "action": "eth_getTransactionCount", "address": address, "tag": "latest"},
        )
        return {
            "address": address.lower(),
            "chain": chain,
            "balance": balance,
            "tx_count": tx_count,
        }

    def normal_txs(self, address: str, chain: str = "ethereum", limit: int = 10) -> dict[str, Any]:
        """Recent normal transactions for an address."""
        data = self._api_call(
            chain,
            {
                "module": "account",
                "action": "txlist",
                "address": address,
                "startblock": 0,
                "endblock": 99999999,
                "page": 1,
                "offset": limit,
                "sort": "desc",
            },
        )
        txs = data.get("result") if isinstance(data.get("result"), list) else []
        return {"address": address.lower(), "chain": chain, "transactions": txs, "count": len(txs)}

    def trace_depth(self, root_address: str, chain: str = "ethereum", depth: int | None = None) -> dict[str, Any]:
        """Depth-limited recipient graph (read-only, max depth 3)."""
        depth = min(depth or self.max_depth, self.max_depth)
        root = root_address.lower()
        graph: dict[str, Any] = {
            "root": root,
            "chain": chain,
            "depth": depth,
            "nodes": [{"address": root, "level": 0}],
            "edges": [],
            "policy": "read_only_depth_limited",
        }

        frontier = [root]
        seen = {root}
        for level in range(1, depth + 1):
            next_frontier: list[str] = []
            for addr in frontier:
                tx_data = self.normal_txs(addr, chain=chain, limit=5)
                if not tx_data.get("transactions"):
                    continue
                for tx in tx_data["transactions"]:
                    recipient = (tx.get("to") or "").lower()
                    if not recipient or recipient in seen:
                        continue
                    seen.add(recipient)
                    graph["nodes"].append({"address": recipient, "level": level})
                    graph["edges"].append(
                        {
                            "from": addr,
                            "to": recipient,
                            "tx_hash": tx.get("hash"),
                            "hop": level,
                        }
                    )
                    next_frontier.append(recipient)
            frontier = next_frontier
            if not frontier:
                break

        self.bus.publish(
            "mcp.blockscout.trace",
            {"root": root, "nodes": len(graph["nodes"]), "edges": len(graph["edges"])},
            source="mcp_blockscout_api",
        )
        return graph

    def status(self) -> dict[str, Any]:
        keys = {
            chain: bool(os.environ.get(meta["key_env"]))
            for chain, meta in _CHAIN_ENDPOINTS.items()
        }
        return {"chains": list(_CHAIN_ENDPOINTS.keys()), "api_keys_configured": keys, "max_depth": self.max_depth}
