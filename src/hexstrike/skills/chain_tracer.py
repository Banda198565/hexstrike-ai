"""chain_tracer — recipient depth analysis and entity resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from hexstrike.bus.context_bus import ContextBus
from hexstrike.core.forensics.engine import ForensicsEngine


@dataclass
class ChainTracerSkill:
    """Multichain recipient depth traversal with entity labels."""

    bus: ContextBus
    forensics: ForensicsEngine
    max_depth: int = 3

    def trace(self, root_address: str, depth: int | None = None) -> dict[str, Any]:
        depth = min(depth or self.max_depth, self.max_depth)
        entity = self.forensics.resolve_entity(root_address)
        graph: dict[str, Any] = {
            "root": root_address.lower(),
            "depth": depth,
            "nodes": [{**entity, "level": 0}],
            "edges": [],
        }

        # Depth-1 placeholder: emit trace request for external Blockscout/multichain workers
        for hop in range(1, depth + 1):
            node = {
                "address": f"hop_{hop}_unresolved",
                "level": hop,
                "labels": ["pending_resolution"],
            }
            graph["nodes"].append(node)
            graph["edges"].append({"from": root_address.lower(), "to": node["address"], "hop": hop})

        self.bus.publish("skill.chain_tracer.result", graph, source="chain_tracer")
        return graph
