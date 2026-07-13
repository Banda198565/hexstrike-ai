"""TxPackage — unified build → sign → broadcast → watch cycle."""

from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hexstrike.core.execution.nonce_recovery import fetch_nonces, sync_recommendation
from hexstrike.mcp.fastmcp.allowlist_manager import AllowlistManager
from hexstrike.mcp.fastmcp.entity_gate import EntityGate
from hexstrike.mcp.fastmcp.receipt_watcher import ReceiptWatcher
from hexstrike.mcp.fastmcp.relay_manager import RelayManager
from hexstrike.mcp.fastmcp.tx_builder import TxBuilder
from hexstrike.mcp.fastmcp.tx_signer import TxSigner
from hexstrike.mcp.fastmcp.vault_handler import VaultHandler

import hexstrike_tx as tx  # noqa: E402


class TxPackage:
    """Combat FastMCP facade — full live transaction cycle."""

    def __init__(self) -> None:
        self.allowlist = AllowlistManager()
        self.gate = EntityGate(self.allowlist)
        self.builder = TxBuilder()
        self.signer = TxSigner(self.gate)
        self.watcher = ReceiptWatcher()
        self.relay = RelayManager()
        self.vault = VaultHandler()
        self.run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def execute_live_tx(
        self,
        target: str,
        value: str = "0.001bnb",
        *,
        module: str = "KeyVaultSigner",
        vault_key: str = "bot",
        strategy: str = "private_first",
        token: str | None = None,
        amount: str | None = None,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        """build → sign → broadcast → watch (dry-run stops before broadcast)."""
        live = dry_run if dry_run is not None else not tx._live_enabled()
        if token:
            built = self.builder.build_erc20(recipient=target, token=token, amount=amount or value)
        else:
            built = self.builder.build_native(target, value)
        if not built.get("success"):
            return {"success": False, "step": "build", **built}

        signed = self.signer.sign_raw(
            built["transaction"],
            module=module,
            vault_key=vault_key,
        )
        if not signed.get("success"):
            return {"success": False, "step": "sign", **signed}

        result: dict[str, Any] = {
            "success": True,
            "run_id": self.run_id,
            "build": built,
            "sign": {k: v for k, v in signed.items() if k != "raw"},
            "dry_run": live,
        }
        if live:
            result["note"] = "dry_run — broadcast skipped"
            self.archive_logs(result)
            return result

        broadcast = self.relay.send_via_relay(signed, strategy=strategy)
        result["broadcast"] = broadcast
        if not broadcast.get("success"):
            result["success"] = False
            result["step"] = "broadcast"
            self.archive_logs(result)
            return result

        tx_hash = broadcast.get("hash")
        if tx_hash:
            result["watch"] = self.watcher.watch(tx_hash)
            result["success"] = result["watch"].get("success", False)
        self.archive_logs(result)
        return result

    def execute_cycle(self, target: str, value: str = "0.001bnb", **kwargs: Any) -> dict[str, Any]:
        return self.execute_live_tx(target, value, **kwargs)

    def rescue_check(self) -> dict[str, Any]:
        rpc = tx._rpc_url()
        holder = os.environ.get("GAS_HOLDER_ADDRESS", "")
        if not holder:
            return {"success": False, "error": "GAS_HOLDER_ADDRESS not set"}
        bal_wei = int(tx.rpc_call(rpc, "eth_getBalance", [holder, "latest"])["result"], 16)
        min_bnb = float(os.environ.get("RESCUE_MIN_BNB", "0.005"))
        bal_bnb = bal_wei / 1e18
        return {
            "success": True,
            "gas_holder": holder,
            "balance_bnb": round(bal_bnb, 8),
            "min_bnb": min_bnb,
            "need_rescue": bal_bnb < min_bnb,
        }

    def archive_logs(self, payload: dict[str, Any]) -> dict[str, Any]:
        d = ROOT / "tx_logs" / self.run_id
        d.mkdir(parents=True, exist_ok=True)
        summary = d / "fastmcp_cycle.json"
        summary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        for name in ("raw_tx.json", "signed_tx.json"):
            src = ROOT / "artifacts" / "tx" / name
            if src.is_file():
                shutil.copy2(src, d / name)
        latest = ROOT / "tx_logs" / "latest"
        latest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(summary, latest / "fastmcp_cycle.json")
        return {"archived": True, "path": str(d)}

    def nonce_status(self, address: str = "") -> dict[str, Any]:
        rpc = tx._rpc_url()
        addr = address or tx._from_address()
        nonces = fetch_nonces(tx.rpc_call, rpc, addr)
        return {**nonces, "recommendation": sync_recommendation(nonces)}


class FastMCPCombat:
    """Named facade matching operator docs."""

    def __init__(self) -> None:
        self.package = TxPackage()
        self.builder = self.package.builder
        self.signer = self.package.signer
        self.watcher = self.package.watcher
        self.relay = self.package.relay
        self.vault = self.package.vault
        self.gate = self.package.gate
        self.allowlist = self.package.allowlist

    def execute_live_tx(self, target: str, value: str) -> dict[str, Any]:
        return self.package.execute_live_tx(target, value)
