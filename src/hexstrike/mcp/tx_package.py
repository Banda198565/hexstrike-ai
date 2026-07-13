"""FastMCP transaction tools — re-exports combat package and MCP registration."""

from __future__ import annotations

from typing import Any

from hexstrike.mcp.fastmcp import (
    AllowlistManager,
    EntityGate,
    FastMCPCombat,
    ReceiptWatcherMcp,
    RelayManagerMcp,
    TxBuilder,
    TxPackage,
    TxSigner,
    VaultHandler,
)

__all__ = [
    "AllowlistManager",
    "EntityGate",
    "FastMCPCombat",
    "ReceiptWatcherMcp",
    "RelayManagerMcp",
    "TxBuilder",
    "TxPackage",
    "TxSigner",
    "VaultHandler",
    "register_mcp_tx_tools",
]


def register_mcp_tx_tools(mcp: Any) -> None:
    """Register combat tx FastMCP tools."""

    combat = FastMCPCombat()

    @mcp.tool()
    def tx_build(
        target: str,
        value: str = "0.001bnb",
        gas: int = 21000,
        token: str = "",
        amount: str = "",
    ) -> dict:
        """TxBuilder — native BNB or ERC20 transfer payload."""
        if token:
            return combat.builder.build_erc20(recipient=target, token=token, amount=amount or value, gas=gas)
        return combat.builder.build_native(target, value, gas)

    @mcp.tool()
    def tx_sign(raw_tx_path: str, module: str = "EnvSigner", vault_key: str = "bot") -> dict:
        """TxSigner — sign with entity gate (EnvSigner | KeyVaultSigner | SafeSigner)."""
        return combat.signer.sign_raw(raw_tx_path, module=module, vault_key=vault_key or None)

    @mcp.tool()
    def tx_broadcast(signed_tx_path: str, strategy: str = "private_first") -> dict:
        """RelayManager — Puissant bundle + public fallback."""
        return combat.relay.send_via_relay(signed_tx_path, strategy=strategy)

    @mcp.tool()
    def tx_watch(tx_hash: str, timeout_sec: float = 120.0) -> dict:
        """ReceiptWatcher — poll until mined/fail/timeout."""
        return combat.watcher.watch(tx_hash)

    @mcp.tool()
    def tx_execute_cycle(
        target: str,
        value: str = "0.001bnb",
        module: str = "KeyVaultSigner",
        vault_key: str = "bot",
        strategy: str = "private_first",
        dry_run: bool = True,
    ) -> dict:
        """TxPackage — full build → sign → broadcast → watch cycle."""
        return combat.package.execute_cycle(
            target, value, module=module, vault_key=vault_key, strategy=strategy, dry_run=dry_run
        )

    @mcp.tool()
    def tx_rescue_check() -> dict:
        """TxPackage.rescue_check — GAS_HOLDER balance vs minimum."""
        return combat.package.rescue_check()

    @mcp.tool()
    def tx_nonce(address: str = "") -> dict:
        """Nonce recovery — latest vs pending gap."""
        return combat.package.nonce_status(address)

    @mcp.tool()
    def relay_latency_probe() -> dict:
        """RelayManager.check_latency + fallback RPC probes."""
        return combat.relay.fallback_rpc()

    @mcp.tool()
    def entity_gate_evaluate(raw_tx_path: str) -> dict:
        """EntityGate — evaluate allowlist without signing."""
        import json
        from pathlib import Path
        import hexstrike_tx as tx_mod
        data = json.loads(Path(raw_tx_path).read_text(encoding="utf-8"))
        tx_dict = data.get("transaction", data)
        return combat.gate.evaluate(tx_dict, from_addr=tx_dict.get("from") or tx_mod._from_address())

    @mcp.tool()
    def allowlist_add_recipient(address: str) -> dict:
        """AllowlistManager — authorize payroll/outflow recipient."""
        return combat.allowlist.add_recipient(address)

    @mcp.tool()
    def allowlist_add_contract(address: str) -> dict:
        """AllowlistManager — authorize token rail / contract."""
        return combat.allowlist.add_contract(address)

    @mcp.tool()
    def allowlist_list() -> dict:
        """AllowlistManager — current authorized recipients and contracts."""
        data = combat.allowlist.load()
        return {
            "path": str(combat.allowlist.path),
            "hot_wallet": data.get("hot_wallet"),
            "authorized_recipients": data.get("authorized_recipients", []),
            "authorized_contracts": data.get("authorized_contracts", []),
        }

    @mcp.tool()
    def vault_status() -> dict:
        """VaultHandler — encrypted keystore status."""
        return combat.vault.status()

    @mcp.tool()
    def vault_init() -> dict:
        """VaultHandler.init_vault — create encrypted keystore."""
        return combat.vault.init_vault()

    @mcp.tool()
    def vault_signer_ready(vault_key: str = "bot") -> dict:
        """VaultHandler — KeyVaultSigner readiness check."""
        return combat.vault.signer_ready(vault_key)
