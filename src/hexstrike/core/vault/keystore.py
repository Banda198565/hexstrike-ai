"""AES-256 encrypted local keystore — keys never exposed in logs or bus payloads."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hexstrike.bus.context_bus import ContextBus
from hexstrike.paths import ARTIFACTS_DIR


class VaultError(RuntimeError):
    pass


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, 200_000, dklen=32)


def _aes_encrypt(plaintext: bytes, key: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise VaultError("cryptography package required for vault (pip install cryptography)") from exc

    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return nonce + ciphertext


def _aes_decrypt(blob: bytes, key: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise VaultError("cryptography package required for vault") from exc

    nonce, ciphertext = blob[:12], blob[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


@dataclass
class KeyVault:
    """Local encrypted key storage. Private material never published on ContextBus."""

    bus: ContextBus
    vault_path: Path = field(default_factory=lambda: ARTIFACTS_DIR / "vault" / "keystore.enc")
    _unlocked: bool = False
    _keys: dict[str, str] = field(default_factory=dict, repr=False)

    def _require_passphrase(self, passphrase: str) -> None:
        if not passphrase:
            raise VaultError("Passphrase required")

    def unlock(self, passphrase: str) -> None:
        self._require_passphrase(passphrase)
        if not self.vault_path.is_file():
            self._keys = {}
            self._unlocked = True
            self.bus.publish("vault.unlocked", {"keys": 0, "new": True}, source="core.vault")
            return

        raw = self.vault_path.read_bytes()
        salt, payload = raw[:16], raw[16:]
        key = _derive_key(passphrase, salt)
        try:
            data = json.loads(_aes_decrypt(payload, key).decode("utf-8"))
        except Exception as exc:
            raise VaultError("Invalid passphrase or corrupted vault") from exc

        self._keys = {k: v for k, v in data.items() if isinstance(v, str)}
        self._unlocked = True
        self.bus.publish("vault.unlocked", {"keys": len(self._keys)}, source="core.vault")

    def lock(self) -> None:
        self._keys.clear()
        self._unlocked = False
        self.bus.publish("vault.locked", {}, source="core.vault")

    def store_key(self, name: str, private_key_hex: str, passphrase: str) -> None:
        if not self._unlocked:
            self.unlock(passphrase)
        if not private_key_hex.startswith("0x"):
            private_key_hex = "0x" + private_key_hex
        self._keys[name] = private_key_hex
        self._save(passphrase)
        self.bus.publish("vault.key_stored", {"name": name}, source="core.vault")

    def get_key(self, name: str) -> str:
        if not self._unlocked:
            raise VaultError("Vault is locked")
        if name not in self._keys:
            raise VaultError(f"Key not found: {name}")
        return self._keys[name]

    def list_key_names(self) -> list[str]:
        return list(self._keys.keys()) if self._unlocked else []

    def _save(self, passphrase: str) -> None:
        salt = secrets.token_bytes(16)
        key = _derive_key(passphrase, salt)
        payload = json.dumps(self._keys).encode("utf-8")
        encrypted = _aes_encrypt(payload, key)
        self.vault_path.parent.mkdir(parents=True, exist_ok=True)
        self.vault_path.write_bytes(salt + encrypted)

    def status(self) -> dict[str, Any]:
        return {
            "unlocked": self._unlocked,
            "key_count": len(self._keys) if self._unlocked else None,
            "path": str(self.vault_path),
            "exists": self.vault_path.is_file(),
        }
