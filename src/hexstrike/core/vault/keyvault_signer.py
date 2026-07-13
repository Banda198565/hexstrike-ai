"""KeyVault-backed transaction signer — keys from encrypted local vault."""

from __future__ import annotations

import os

from hexstrike.bus.context_bus import ContextBus
from hexstrike.core.vault.keystore import KeyVault, VaultError


class KeyVaultSigner:
    """Sign using a named key from KeyVault (never logs private material)."""

    MODULE_NAME = "KeyVaultSigner"

    def __init__(self, *, key_name: str | None = None, passphrase: str | None = None) -> None:
        self.key_name = key_name or os.environ.get("VAULT_KEY_NAME", "bot")
        self.passphrase = passphrase or os.environ.get("VAULT_PASSPHRASE", "")

    def private_key_hex(self) -> str:
        if not self.passphrase:
            raise VaultError("VAULT_PASSPHRASE not set — cannot unlock KeyVaultSigner")
        vault = KeyVault(bus=ContextBus(), prefer_ramdisk=True)
        vault.unlock(self.passphrase)
        return vault.get_key(self._resolve_key_name(vault))

    def _resolve_key_name(self, vault: KeyVault) -> str:
        names = vault.list_key_names()
        if self.key_name in names:
            return self.key_name
        aliases = {
            "bot": ("bot", "BOT", "operator", "funder"),
            "safe": ("safe", "SAFE", "gas_rescue"),
        }
        for canonical, alts in aliases.items():
            if self.key_name.lower() in alts:
                for n in names:
                    if n.lower() in alts or n.lower() == canonical:
                        return n
        raise VaultError(f"Vault key not found: {self.key_name} (available: {names or 'none'})")
