"""TxBuilder — native and ERC20 raw payload formation."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hexstrike.bus.context_bus import ContextBus
from hexstrike.core.execution.broadcaster import ExecutionBroadcaster
from hexstrike.core.execution.erc20_build import build_erc20_tx_fields
from hexstrike.paths import RPC_CONFIG

import hexstrike_tx as tx  # noqa: E402


class TxBuilder:
    """Form raw transaction payloads with preflight gas estimate."""

    def __init__(self, artifacts_dir: Path | None = None) -> None:
        self.artifacts_dir = artifacts_dir or (ROOT / "artifacts" / "tx")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def build_native(self, target: str, value: str = "0.001bnb", gas: int = 21000) -> dict[str, Any]:
        rpc = tx._rpc_url()
        to_addr = target if target.startswith("0x") else f"0x{target}"
        built = tx._build_tx(
            from_addr=tx._from_address(),
            to_addr=to_addr,
            value_wei=tx.parse_value(value),
            gas=gas,
            rpc=rpc,
        )
        return self._finalize(built, rpc, kind="native")

    def build_erc20(
        self,
        recipient: str,
        token: str,
        amount: str,
        gas: int = 65000,
    ) -> dict[str, Any]:
        rpc = tx._rpc_url()
        to_addr = recipient if recipient.startswith("0x") else f"0x{recipient}"
        amount_wei = tx.parse_value(amount)
        fields = build_erc20_tx_fields(token=token, recipient=to_addr, amount_wei=amount_wei)
        built = tx._build_tx(
            from_addr=tx._from_address(),
            to_addr=fields["to"],
            value_wei=0,
            gas=max(gas, 65000),
            rpc=rpc,
        )
        built["data"] = fields["data"]
        built["value"] = "0x0"
        built["erc20_recipient"] = to_addr
        built["erc20_amount_wei"] = amount_wei
        return self._finalize(built, rpc, kind="erc20")

    def estimate_gas(self, transaction: dict[str, Any]) -> dict[str, Any]:
        pre = ExecutionBroadcaster(bus=ContextBus(), config_path=RPC_CONFIG).preflight(transaction)
        return {
            "ok": pre.ok,
            "gas_estimate": pre.gas_estimate,
            "gas_price_wei": pre.gas_price_wei,
            "errors": pre.errors,
            "warnings": pre.warnings,
        }

    def _finalize(self, built: dict[str, Any], rpc: str, *, kind: str) -> dict[str, Any]:
        preflight = self.estimate_gas(built)
        out_path = self.artifacts_dir / "raw_tx.json"
        out_path.write_text(json.dumps({"transaction": built}, indent=2) + "\n", encoding="utf-8")
        return {
            "success": preflight["ok"],
            "kind": kind,
            "transaction": built,
            "raw_tx_path": str(out_path),
            "preflight": preflight,
            "rpc": rpc,
        }

    # Back-compat alias
    def build(self, target: str, value: str = "0.001bnb", gas: int = 21000, *, token: str | None = None, amount: str | None = None) -> dict[str, Any]:
        if token:
            return self.build_erc20(recipient=target, token=token, amount=amount or value, gas=gas)
        return self.build_native(target, value, gas)
