"""RelayManager — private Puissant bundle + public RPC fallback."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hexstrike.core.relay.puissant_relay import PuissantRelay, RelayManager as CoreRelay

import hexstrike_tx as tx  # noqa: E402


class RelayManager:
    """Send signed transactions via relay strategy."""

    def __init__(self) -> None:
        self._puissant = PuissantRelay()

    def send_via_relay(self, signed_tx: str | dict[str, Any], strategy: str = "private_first") -> dict[str, Any]:
        if isinstance(signed_tx, (str, Path)):
            data = json.loads(Path(signed_tx).read_text(encoding="utf-8"))
        else:
            data = signed_tx
        raw = data.get("raw") or data.get("signed_tx")
        if not raw:
            return {"success": False, "error": "missing raw hex"}
        if not tx._live_enabled() and __import__("os").environ.get("HEXSTRIKE_TX_ALLOW_BROADCAST", "") != "1":
            return {"success": False, "error": "HEXSTRIKE_TX_LIVE=1 required for broadcast"}
        result = CoreRelay().broadcast(raw, strategy=strategy)
        if result.get("success") and not result.get("hash"):
            result["hash"] = data.get("hash")
        return result

    def check_latency(self, rpc: str | None = None) -> dict[str, Any]:
        rpc = rpc or tx._rpc_url()
        t0 = time.monotonic()
        try:
            tx.rpc_call(rpc, "eth_blockNumber", [])
            ms = int((time.monotonic() - t0) * 1000)
            return {"rpc": rpc, "latency_ms": ms, "ok": True}
        except Exception as exc:  # noqa: BLE001
            return {"rpc": rpc, "ok": False, "error": str(exc)}

    def fallback_rpc(self) -> dict[str, Any]:
        from crypto_rpc_orchestrator import load_config
        from hexstrike.paths import RPC_CONFIG
        cfg = load_config(RPC_CONFIG)
        primary = cfg.get("primary")
        fallbacks = cfg.get("fallbacks", [])
        results = [self.check_latency(primary)] if primary else []
        for fb in fallbacks[:3]:
            results.append(self.check_latency(fb))
        return {"primary": primary, "probes": results}


class RelayManagerMcp:
    @staticmethod
    def broadcast(signed_tx_path: str, strategy: str = "private_first") -> dict[str, Any]:
        return RelayManager().send_via_relay(signed_tx_path, strategy=strategy)
