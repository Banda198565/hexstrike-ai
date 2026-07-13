"""VaultHandler — init, store, retrieve encrypted operator keys."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.bus.context_bus import ContextBus
from hexstrike.core.vault.keyvault_signer import KeyVaultSigner
from hexstrike.core.vault.keystore import KeyVault, VaultError


class VaultHandler:
    """Encrypted keystore operations (RAM-disk preferred)."""

    def __init__(self, prefer_ramdisk: bool = True) -> None:
        self.prefer_ramdisk = prefer_ramdisk

    def _vault(self) -> KeyVault:
        return KeyVault(bus=ContextBus(), prefer_ramdisk=self.prefer_ramdisk)

    def _passphrase(self, passphrase: str | None = None) -> str:
        pw = passphrase or os.environ.get("VAULT_PASSPHRASE", "")
        if not pw:
            raise VaultError("VAULT_PASSPHRASE required")
        return pw

    def init_vault(self, passphrase: str | None = None) -> dict[str, Any]:
        vault = self._vault()
        pw = self._passphrase(passphrase)
        vault.unlock(pw)
        if not vault.vault_path.is_file():
            vault._save(pw)
        return {"success": True, "command": "init_vault", **vault.status()}

    def store_key(self, name: str, private_key_hex: str, passphrase: str | None = None) -> dict[str, Any]:
        vault = self._vault()
        pw = self._passphrase(passphrase)
        vault.unlock(pw)
        key = private_key_hex if private_key_hex.startswith("0x") else f"0x{private_key_hex}"
        vault.store_key(name, key, pw)
        return {"success": True, "command": "store_key", "name": name, **vault.status()}

    def retrieve_key(self, name: str = "bot", passphrase: str | None = None) -> str:
        pw = passphrase or self._passphrase()
        signer = KeyVaultSigner(key_name=name, passphrase=pw)
        return signer.private_key_hex()

    def list_keys(self, passphrase: str | None = None) -> dict[str, Any]:
        vault = self._vault()
        pw = self._passphrase(passphrase)
        vault.unlock(pw)
        return {"success": True, "keys": vault.list_key_names(), **vault.status()}

    def status(self) -> dict[str, Any]:
        return {"success": True, **self._vault().status()}

    def signer_ready(self, vault_key: str = "bot") -> dict[str, Any]:
        try:
            self.retrieve_key(vault_key)
            return {"success": True, "module": "KeyVaultSigner", "key": vault_key}
        except VaultError as exc:
            return {"success": False, "error": str(exc)}
