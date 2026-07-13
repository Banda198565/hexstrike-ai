"""Entity gate — filter recipients before signing live outflows."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from hot_wallet_ir import classify_hot_wallet_outflow, decode_erc20_transfer, normalize_addr  # noqa: E402

from hexstrike.mcp.fastmcp.allowlist_manager import AllowlistManager


def _tx_value_wei(tx: dict[str, Any]) -> int:
    v = tx.get("value", "0x0")
    if isinstance(v, int):
        return v
    if isinstance(v, str):
        return int(v, 16) if v.startswith("0x") else int(v)
    return 0


class EntityGate:
    """Evaluate whether a transaction may proceed to signing."""

    def __init__(self, allowlist: AllowlistManager | None = None) -> None:
        self.allowlist = allowlist or AllowlistManager()

    def evaluate(self, tx: dict[str, Any], *, from_addr: str) -> dict[str, Any]:
        data = self.allowlist.load()
        hot = normalize_addr(data.get("hot_wallet") or from_addr)
        classification = classify_hot_wallet_outflow(tx, hot, allowlist=data)

        erc20_to, _ = decode_erc20_transfer(tx.get("data") or tx.get("input") or "0x")
        to_addr = normalize_addr(tx.get("to"))
        effective = erc20_to or to_addr

        allowed = True
        reasons: list[str] = []

        ok, reason = self.allowlist.is_authorized(effective, token_contract=to_addr if erc20_to else None)
        if ok:
            reasons.append(reason)
        elif to_addr in self.allowlist.authorized_contracts() and erc20_to:
            allowed = False
            reasons.append("blocked_unknown_erc20_recipient")
        elif _tx_value_wei(tx) == 0 and not erc20_to:
            reasons.append("empty_call_allowed_for_review")
        elif os.environ.get("HEXSTRIKE_TX_ALLOW_UNKNOWN", "").lower() in ("1", "true", "yes"):
            reasons.append("override_HEXSTRIKE_TX_ALLOW_UNKNOWN")
        else:
            allowed = False
            reasons.append("blocked_unknown_recipient")

        if classification.get("ir_trigger"):
            reasons.append("ir_trigger_classification")

        return {
            "allowed": allowed,
            "reasons": reasons,
            "classification": classification,
            "effective_to": effective,
        }

    def assert_allowed(self, tx: dict[str, Any], *, from_addr: str) -> None:
        gate = self.evaluate(tx, from_addr=from_addr)
        if not gate["allowed"]:
            raise PermissionError(f"entity_gate_blocked: {gate['reasons']}")
