"""Chain analysis engine: Blockscout/multichain traces + cex-cluster-map."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hexstrike.bus.context_bus import ContextBus
from hexstrike.paths import ARTIFACTS_DIR, MASTER_CONTEXT, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
from context_utils import get_cex_cluster_payload, load_master_context  # noqa: E402


@dataclass
class ForensicsEngine:
    """Unified forensics context loader and on-chain entity resolver."""

    bus: ContextBus
    context_path: Path = MASTER_CONTEXT
    out_dir: Path = field(default_factory=lambda: ARTIFACTS_DIR / "forensics")

    def load_context(self) -> dict[str, Any] | None:
        ctx = load_master_context(self.context_path)
        self.bus.publish(
            "forensics.context_loaded",
            {"entries": len((ctx or {}).get("entries", [])), "path": str(self.context_path)},
            source="core.forensics",
        )
        return ctx

    def load_cex_clusters(self) -> dict[str, Any] | None:
        clusters = get_cex_cluster_payload(self.context_path)
        if clusters:
            self.bus.publish(
                "forensics.cex_clusters",
                {"cluster_count": len(clusters.get("clusters", clusters))},
                source="core.forensics",
            )
        return clusters

    def resolve_entity(self, address: str) -> dict[str, Any]:
        """Resolve address labels from master context and CEX map."""
        address = address.lower()
        result: dict[str, Any] = {"address": address, "labels": [], "sources": []}

        ctx = self.load_context()
        if ctx:
            for entry in ctx.get("entries", []):
                blob = json.dumps(entry.get("data", entry), default=str).lower()
                if address in blob:
                    meta = entry.get("_meta", {})
                    result["labels"].append(meta.get("entity_type", "indexed_artifact"))
                    result["sources"].append(meta.get("source_file", "master_context"))

        clusters = self.load_cex_clusters() or {}
        for cluster in clusters.get("clusters", []):
            addrs = [a.lower() for a in cluster.get("addresses", [])]
            if address in addrs:
                result["labels"].append(cluster.get("label", "cex_cluster"))
                result["sources"].append("cex-cluster-map")

        self.bus.publish("forensics.entity_resolved", result, source="core.forensics")
        return result

    def trace_recipient_depth(self, address: str, depth: int = 2) -> dict[str, Any]:
        """Placeholder depth analysis — emits bus event for chain_tracer skill."""
        payload = {
            "root": address.lower(),
            "depth": depth,
            "status": "queued",
            "note": "Use skills.chain_tracer for full multichain traversal",
        }
        self.bus.publish("forensics.trace_request", payload, source="core.forensics")
        return payload
