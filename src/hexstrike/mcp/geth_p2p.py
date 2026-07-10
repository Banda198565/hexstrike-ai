"""mcp_geth_p2p — P2P surface recon via devp2p TCP probes and optional geth devp2p CLI."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from hexstrike.bus.context_bus import ContextBus
from hexstrike.skills.enode_crawl import EnodeCrawlSkill


@dataclass
class GethP2pMcp:
    """Read-only P2P recon — TCP :30303 probes; discv4 only when geth devp2p is available."""

    bus: ContextBus
    crawl_skill: EnodeCrawlSkill | None = None

    def __post_init__(self) -> None:
        if self.crawl_skill is None:
            self.crawl_skill = EnodeCrawlSkill(bus=self.bus)

    def probe(self, ip: str, port: int = 30303) -> dict[str, Any]:
        """Single TCP probe on devp2p port."""
        return self.crawl_skill.probe_p2p_port(ip, port)

    def crawl(self, ip: str, ports: list[int] | None = None) -> dict[str, Any]:
        """Multi-port passive surface map."""
        return self.crawl_skill.crawl(ip, ports=ports)

    def discv4_ping(self, node_enode: str) -> dict[str, Any]:
        """Run `geth devp2p ping` when geth is installed (read-only, authorized lab only)."""
        geth = shutil.which("geth")
        if not geth:
            return {
                "success": False,
                "error": "geth_not_found",
                "note": "Install go-ethereum for discv4 peer discovery",
            }

        try:
            proc = subprocess.run(
                [geth, "devp2p", "ping", node_enode],
                capture_output=True,
                text=True,
                timeout=20,
            )
            result = {
                "success": proc.returncode == 0,
                "enode": node_enode,
                "stdout": proc.stdout.strip(),
                "stderr": proc.stderr.strip(),
                "policy": "read_only_discv4_ping",
            }
            self.bus.publish("mcp.geth_p2p.ping", {"enode": node_enode[:40]}, source="mcp_geth_p2p")
            return result
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "timeout", "enode": node_enode}

    def status(self) -> dict[str, Any]:
        return {
            "geth_available": bool(shutil.which("geth")),
            "default_ports": [30303, 30304, 8545],
            "policy": "passive_tcp_probe_no_rlpx_injection",
        }
