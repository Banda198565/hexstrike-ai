"""mcp_shodan — read-only Shodan OSINT for IP and infrastructure analysis."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any

import requests

from hexstrike.bus.context_bus import ContextBus
from hexstrike.core.stealth.transport import StealthConfig, StealthTransport
from hexstrike.paths import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
from crypto_rpc_orchestrator import GETH_NODES  # noqa: E402


@dataclass
class ShodanMcp:
    """Passive Shodan host lookup — falls back to cached lab node list without API key."""

    bus: ContextBus
    api_key: str | None = field(default=None)
    base_url: str = "https://api.shodan.io"
    transport: StealthTransport = field(default_factory=lambda: StealthTransport(StealthConfig()))

    def __post_init__(self) -> None:
        self.api_key = self.api_key or os.environ.get("SHODAN_API_KEY")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        params = dict(params or {})
        if self.api_key:
            params["key"] = self.api_key
        self.transport._jitter()
        resp = self.transport._session.get(
            f"{self.base_url}{path}",
            params=params,
            headers=self.transport._headers(),
            timeout=12,
        )
        resp.raise_for_status()
        return resp.json()

    def host_lookup(self, ip: str) -> dict[str, Any]:
        """Return Shodan host profile for an IP (read-only)."""
        if not self.api_key:
            cached = next((n for n in GETH_NODES if n["ip"] == ip), None)
            result = {
                "ip": ip,
                "source": "cached_lab_list",
                "configured": False,
                "note": "Set SHODAN_API_KEY for live Shodan queries",
                "cached": cached,
            }
            self.bus.publish("mcp.shodan.host", {"ip": ip, "cached": True}, source="mcp_shodan")
            return result

        data = self._get(f"/shodan/host/{ip}")
        result = {
            "ip": ip,
            "source": "shodan_api",
            "configured": True,
            "org": data.get("org"),
            "country": data.get("country_name"),
            "ports": data.get("ports", []),
            "tags": data.get("tags", []),
            "vulns": list((data.get("vulns") or {}).keys()),
            "hostnames": data.get("hostnames", []),
        }
        self.bus.publish("mcp.shodan.host", {"ip": ip, "ports": len(result["ports"])}, source="mcp_shodan")
        return result

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        """Search Shodan index (read-only). Requires SHODAN_API_KEY."""
        if not self.api_key:
            matches = [
                {"ip": n["ip"], "org": n["org"], "country": n["country"]}
                for n in GETH_NODES[:limit]
            ]
            return {
                "query": query,
                "source": "cached_lab_list",
                "configured": False,
                "matches": matches,
                "total": len(matches),
            }

        data = self._get("/shodan/host/search", {"query": query})
        matches = [
            {
                "ip": m.get("ip_str"),
                "port": m.get("port"),
                "org": m.get("org"),
                "product": m.get("product"),
            }
            for m in data.get("matches", [])[:limit]
        ]
        self.bus.publish("mcp.shodan.search", {"query": query[:80], "hits": len(matches)}, source="mcp_shodan")
        return {"query": query, "source": "shodan_api", "configured": True, "matches": matches, "total": data.get("total", 0)}

    def list_cached_geth_nodes(self) -> list[dict[str, str]]:
        """Return operator lab Geth node list (Shodan-sourced, read-only)."""
        return list(GETH_NODES)

    def status(self) -> dict[str, Any]:
        return {
            "configured": bool(self.api_key),
            "api_key_env": "SHODAN_API_KEY",
            "cached_nodes": len(GETH_NODES),
        }
