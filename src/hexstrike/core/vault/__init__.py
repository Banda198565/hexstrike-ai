"""core.vault — encrypted local key management (AES-256)."""

from hexstrike.core.vault.keystore import KeyVault, VaultError
from hexstrike.core.vault.keyvault_signer import KeyVaultSigner

__all__ = ["KeyVault", "VaultError", "KeyVaultSigner"]
