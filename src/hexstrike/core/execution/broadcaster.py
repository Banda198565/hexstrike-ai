"""Safe transaction broadcaster: gas estimation, slippage guard, human approval gate."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from typing import Any

from hexstrike.bus.context_bus import ContextBus
from hexstrike.paths import PENDING_ACTION, RPC_CONFIG, ROOT

sys.path.insert(0, str(ROOT / "scripts"))
from crypto_rpc_orchestrator import load_config, rpc_with_fallback  # noqa: E402


@dataclass
class PreflightResult:
    ok: bool
    gas_estimate: int | None = None
    gas_price_wei: int | None = None
    max_slippage_bps: int = 50
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ExecutionBroadcaster:
    """Controlled execution layer — never broadcasts without operator approval."""

    bus: ContextBus
    config_path: Any = RPC_CONFIG
    default_slippage_bps: int = 50
    require_approval: bool = True

    def _rpc_endpoints(self) -> list[str]:
        cfg = load_config(self.config_path)
        return [cfg["primary"], *cfg.get("fallbacks", [])]

    def preflight(
        self,
        tx: dict[str, Any],
        *,
        max_slippage_bps: int | None = None,
    ) -> PreflightResult:
        """Estimate gas and validate slippage bounds before any broadcast."""
        slippage = max_slippage_bps if max_slippage_bps is not None else self.default_slippage_bps
        result = PreflightResult(ok=False, max_slippage_bps=slippage)
        endpoints = self._rpc_endpoints()

        try:
            _, gas_resp = rpc_with_fallback(endpoints, "eth_estimateGas", [tx], timeout=12.0)
            if gas_resp.get("error"):
                result.errors.append(str(gas_resp["error"]))
            else:
                result.gas_estimate = int(gas_resp.get("result", "0x0"), 16)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"gas_estimate failed: {exc}")

        try:
            _, price_resp = rpc_with_fallback(endpoints, "eth_gasPrice", [], timeout=8.0)
            if price_resp.get("result"):
                result.gas_price_wei = int(price_resp["result"], 16)
        except Exception as exc:  # noqa: BLE001
            result.warnings.append(f"gas_price unavailable: {exc}")

        if slippage > 500:
            result.warnings.append(f"slippage {slippage}bps exceeds recommended 500bps cap")

        result.ok = not result.errors
        self.bus.publish(
            "execution.preflight",
            {
                "ok": result.ok,
                "gas_estimate": result.gas_estimate,
                "gas_price_wei": result.gas_price_wei,
                "slippage_bps": slippage,
                "errors": result.errors,
            },
            source="core.execution",
        )
        return result

    def queue_for_approval(self, tx: dict[str, Any], *, reason: str = "") -> dict[str, Any]:
        """Write pending action — human-in-the-loop via mcp_execution_gate."""
        payload = {
            "status": "awaiting_operator_review",
            "action": "broadcast_tx",
            "reason": reason,
            "transaction": tx,
            "preflight": None,
        }
        pre = self.preflight(tx)
        payload["preflight"] = {
            "ok": pre.ok,
            "gas_estimate": pre.gas_estimate,
            "gas_price_wei": pre.gas_price_wei,
            "errors": pre.errors,
        }

        if self.require_approval:
            PENDING_ACTION.parent.mkdir(parents=True, exist_ok=True)
            PENDING_ACTION.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
            self.bus.publish("execution.queued", payload, source="core.execution")
            return {"queued": True, "path": str(PENDING_ACTION)}

        return {"queued": False, "reason": "approval_required_disabled"}

    def broadcast(self, signed_tx_hex: str, *, approved: bool = False) -> dict[str, Any]:
        """Broadcast only when explicitly approved by operator."""
        if self.require_approval and not approved:
            self.bus.publish(
                "execution.denied",
                {"reason": "missing_operator_approval"},
                source="core.execution",
            )
            return {"success": False, "error": "Operator approval required"}

        endpoints = self._rpc_endpoints()
        try:
            url, resp = rpc_with_fallback(
                endpoints, "eth_sendRawTransaction", [signed_tx_hex], timeout=15.0
            )
            if resp.get("error"):
                self.bus.publish("execution.failed", resp, source="core.execution")
                return {"success": False, "error": resp["error"], "rpc": url}
            tx_hash = resp.get("result")
            self.bus.publish("execution.broadcast", {"hash": tx_hash, "rpc": url}, source="core.execution")
            return {"success": True, "hash": tx_hash, "rpc": url}
        except Exception as exc:  # noqa: BLE001
            return {"success": False, "error": str(exc)}
