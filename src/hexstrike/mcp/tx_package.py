"""FastMCP transaction package — TxBuilder, TxSigner, ReceiptWatcher, RelayManager, VaultHandler."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hexstrike.core.execution.erc20_build import build_erc20_tx_fields
from hexstrike.core.execution.entity_gate import gate_transaction
from hexstrike.core.execution.receipt_watcher import ReceiptWatcher
from hexstrike.core.execution.nonce_recovery import fetch_nonces, sync_recommendation
from hexstrike.core.relay.puissant_relay import RelayManager
from hexstrike.core.vault.keyvault_signer import KeyVaultSigner
from hexstrike.core.vault.keystore import KeyVault, VaultError
from hexstrike.bus.context_bus import ContextBus

import hexstrike_tx as tx  # noqa: E402


class TxBuilder:
    """Build native or ERC20 transaction payloads."""

    @staticmethod
    def build(
        target: str,
        value: str = "0.001bnb",
        gas: int = 21000,
        *,
        token: str | None = None,
        amount: str | None = None,
    ) -> dict[str, Any]:
        rpc = tx._rpc_url()
        from_addr = tx._from_address()
        if token:
            recipient = target if target.startswith("0x") else f"0x{target}"
            amount_wei = tx.parse_value(amount or value)
            fields = build_erc20_tx_fields(token=token, recipient=recipient, amount_wei=amount_wei)
            built = tx._build_tx(
                from_addr=from_addr,
                to_addr=fields["to"],
                value_wei=0,
                gas=max(gas, 65000),
                rpc=rpc,
            )
            built["data"] = fields["data"]
            built["value"] = "0x0"
        else:
            to_addr = target if target.startswith("0x") else f"0x{target}"
            built = tx._build_tx(
                from_addr=from_addr,
                to_addr=to_addr,
                value_wei=tx.parse_value(value),
                gas=gas,
                rpc=rpc,
            )
        out_path = ROOT / "artifacts" / "tx" / "raw_tx.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"transaction": built}, indent=2) + "\n", encoding="utf-8")
        return {"success": True, "transaction": built, "raw_tx_path": str(out_path), "rpc": rpc}


class TxSigner:
    """Sign with EnvSigner, KeyVaultSigner, or SafeSigner."""

    @staticmethod
    def sign(raw_tx_path: str, module: str = "EnvSigner", vault_key: str | None = None) -> dict[str, Any]:
        data = json.loads(Path(raw_tx_path).read_text(encoding="utf-8"))
        tx_dict = data.get("transaction", data)
        gate = gate_transaction(tx_dict, from_addr=tx_dict.get("from") or tx._from_address())
        if not gate["allowed"]:
            return {"success": False, "error": "entity_gate_blocked", "gate": gate}
        mod_name, pk = tx._resolve_signer_module(module, vault_key=vault_key)
        signed = tx._sign_tx_dict(tx_dict, private_key=pk, rpc=tx._rpc_url())
        signed["signer_module"] = mod_name
        out_path = Path(raw_tx_path).with_name("signed_tx.json")
        out_path.write_text(json.dumps({"command": "sign", **signed}, indent=2) + "\n", encoding="utf-8")
        return {"success": True, "gate": gate, "output": str(out_path), **signed}


class ReceiptWatcherMcp:
    @staticmethod
    def watch(tx_hash: str, timeout_sec: float = 120.0) -> dict[str, Any]:
        rpc = tx._rpc_url()
        watcher = ReceiptWatcher(rpc_call=tx.rpc_call, timeout_sec=timeout_sec)
        return watcher.watch(rpc, tx_hash)


class RelayManagerMcp:
    @staticmethod
    def broadcast(signed_tx_path: str, strategy: str = "private_first") -> dict[str, Any]:
        data = json.loads(Path(signed_tx_path).read_text(encoding="utf-8"))
        raw = data.get("raw") or data.get("signed_tx")
        if not raw:
            return {"success": False, "error": "missing raw hex"}
        if not tx._live_enabled() and os.environ.get("HEXSTRIKE_TX_ALLOW_BROADCAST", "") != "1":
            return {"success": False, "error": "HEXSTRIKE_TX_LIVE=1 required for broadcast"}
        return RelayManager().broadcast(raw, strategy=strategy)


class VaultHandler:
    @staticmethod
    def status() -> dict[str, Any]:
        return KeyVault(bus=ContextBus()).status()

    @staticmethod
    def list_keys(passphrase: str | None = None) -> dict[str, Any]:
        pw = passphrase or os.environ.get("VAULT_PASSPHRASE", "")
        if not pw:
            return {"success": False, "error": "VAULT_PASSPHRASE required"}
        vault = KeyVault(bus=ContextBus())
        vault.unlock(pw)
        return {"success": True, "keys": vault.list_key_names(), **vault.status()}

    @staticmethod
    def signer_ready(vault_key: str = "bot") -> dict[str, Any]:
        try:
            KeyVaultSigner(key_name=vault_key).private_key_hex()
            return {"success": True, "module": "KeyVaultSigner", "key": vault_key}
        except VaultError as exc:
            return {"success": False, "error": str(exc)}


def register_mcp_tx_tools(mcp: Any) -> None:
    """Register tx FastMCP tools on an existing FastMCP instance."""

    @mcp.tool()
    def tx_build(
        target: str,
        value: str = "0.001bnb",
        gas: int = 21000,
        token: str = "",
        amount: str = "",
    ) -> dict[str, Any]:
        """TransactionBuilder — native BNB or ERC20 transfer payload."""
        return TxBuilder.build(target, value, gas, token=token or None, amount=amount or None)

    @mcp.tool()
    def tx_sign(raw_tx_path: str, module: str = "EnvSigner", vault_key: str = "bot") -> dict[str, Any]:
        """TransactionSigner with entity gate (EnvSigner | KeyVaultSigner | SafeSigner)."""
        return TxSigner.sign(raw_tx_path, module=module, vault_key=vault_key or None)

    @mcp.tool()
    def tx_broadcast(signed_tx_path: str, strategy: str = "private_first") -> dict[str, Any]:
        """Broadcast via Puissant relay with public fallback."""
        return RelayManagerMcp.broadcast(signed_tx_path, strategy=strategy)

    @mcp.tool()
    def tx_watch(tx_hash: str, timeout_sec: float = 120.0) -> dict[str, Any]:
        """ReceiptWatcher — poll until mined/fail/timeout."""
        return ReceiptWatcherMcp.watch(tx_hash, timeout_sec=timeout_sec)

    @mcp.tool()
    def tx_nonce(address: str = "") -> dict[str, Any]:
        """Nonce recovery — latest vs pending gap."""
        addr = address or tx._from_address()
        rpc = tx._rpc_url()
        nonces = fetch_nonces(tx.rpc_call, rpc, addr)
        return {**nonces, "recommendation": sync_recommendation(nonces)}

    @mcp.tool()
    def tx_rescue(target: str = "", value: str = "0.01bnb", dry_run: bool = True) -> dict[str, Any]:
        """RescueHandler — SAFE to GAS_HOLDER top-up."""
        import argparse
        ns = argparse.Namespace(target=target or None, value=value, gas="21000", dry_run=dry_run)
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = tx.cmd_rescue(ns)
        try:
            result = json.loads(buf.getvalue())
        except json.JSONDecodeError:
            result = {"stdout": buf.getvalue()}
        result["success"] = code == 0
        return result

    @mcp.tool()
    def vault_status() -> dict[str, Any]:
        """VaultHandler — encrypted keystore status."""
        return VaultHandler.status()

    @mcp.tool()
    def vault_signer_ready(vault_key: str = "bot") -> dict[str, Any]:
        """Check KeyVaultSigner readiness without exposing key material."""
        return VaultHandler.signer_ready(vault_key)
