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

    def bootstrap(self, *, import_env_keys: bool = True) -> dict[str, Any]:
        """First-run: create vault if missing and import BOT/SAFE keys from env."""
        vault = self._vault()
        st = vault.status()
        report: dict[str, Any] = {
            "command": "vault_bootstrap",
            "vault_existed": st.get("exists", False),
            "actions": [],
        }
        pw = os.environ.get("VAULT_PASSPHRASE", "")
        if not pw:
            report["success"] = False
            report["skipped"] = True
            report["error"] = "VAULT_PASSPHRASE not set — bootstrap skipped"
            return report

        try:
            vault.unlock(pw)
            if not st.get("exists"):
                vault._save(pw)
                report["actions"].append("init_vault")
            if import_env_keys:
                for name, env_name in (("bot", "BOT_PRIVATE_KEY"), ("safe", "SAFE_PRIVATE_KEY")):
                    raw = os.environ.get(env_name, "").strip()
                    if not raw:
                        continue
                    if name in vault.list_key_names():
                        report["actions"].append(f"skip_{name}_exists")
                        continue
                    key = raw if raw.startswith("0x") else f"0x{raw}"
                    vault.store_key(name, key, pw)
                    report["actions"].append(f"imported_{name}_from_env")
            report["success"] = True
            report.update(vault.status())
            report["keys"] = vault.list_key_names()
            return report
        except VaultError as exc:
            return {"success": False, "error": str(exc), **report}

    def signer_ready(self, vault_key: str = "bot") -> dict[str, Any]:
        try:
            self.retrieve_key(vault_key)
            return {"success": True, "module": "KeyVaultSigner", "key": vault_key}
        except VaultError as exc:
            return {"success": False, "error": str(exc)}
