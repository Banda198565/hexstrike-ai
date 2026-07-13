"""Allowlist management for live transaction outflows."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "scripts"))

from hot_wallet_ir import load_allowlist, normalize_addr  # noqa: E402

DEFAULT_PATH = ROOT / "config" / "hot-wallet-allowlist.json"


class AllowlistManager:
    """Load and mutate hot-wallet allowlist (recipients + token rails)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or DEFAULT_PATH

    def load(self) -> dict[str, Any]:
        return load_allowlist(self.path)

    def save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def authorized_recipients(self) -> set[str]:
        data = self.load()
        return {normalize_addr(a) for a in data.get("authorized_recipients", [])}

    def authorized_contracts(self) -> set[str]:
        data = self.load()
        return {normalize_addr(a) for a in data.get("authorized_contracts", [])}

    def add_recipient(self, address: str) -> dict[str, Any]:
        data = self.load()
        addr = normalize_addr(address)
        recipients = data.setdefault("authorized_recipients", [])
        if addr not in {normalize_addr(a) for a in recipients}:
            recipients.append(addr)
        self.save(data)
        return {"success": True, "added": addr, "path": str(self.path)}

    def add_contract(self, address: str) -> dict[str, Any]:
        data = self.load()
        addr = normalize_addr(address)
        contracts = data.setdefault("authorized_contracts", [])
        if addr not in {normalize_addr(a) for a in contracts}:
            contracts.append(addr)
        self.save(data)
        return {"success": True, "added": addr, "path": str(self.path)}

    def is_authorized(self, effective_to: str, *, token_contract: str | None = None) -> tuple[bool, str]:
        eff = normalize_addr(effective_to)
        token = normalize_addr(token_contract) if token_contract else ""
        if eff in self.authorized_recipients():
            return True, "allowlist_recipient"
        if token and token in self.authorized_contracts() and eff in self.authorized_recipients():
            return True, "allowlist_token_rail"
        if eff in self.authorized_contracts():
            return True, "allowlist_contract"
        return False, "unknown_recipient"
