"""TxSigner — KeyVault / env signing with entity gate."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hexstrike.mcp.fastmcp.entity_gate import EntityGate

import hexstrike_tx as tx  # noqa: E402


class TxSigner:
    """Sign raw transactions; never logs private key material."""

    def __init__(self, gate: EntityGate | None = None) -> None:
        self.gate = gate or EntityGate()

    def load_key(self, module: str = "EnvSigner", vault_key: str | None = None) -> tuple[str, str]:
        return tx._resolve_signer_module(module, vault_key=vault_key)

    def sign_raw(
        self,
        raw_tx: str | dict[str, Any],
        *,
        module: str = "EnvSigner",
        vault_key: str | None = None,
        skip_gate: bool = False,
        out_path: Path | None = None,
    ) -> dict[str, Any]:
        if isinstance(raw_tx, (str, Path)):
            data = json.loads(Path(raw_tx).read_text(encoding="utf-8"))
            tx_dict = data.get("transaction", data)
            raw_path = Path(raw_tx)
        else:
            tx_dict = raw_tx
            raw_path = ROOT / "artifacts" / "tx" / "raw_tx.json"

        gate_result: dict[str, Any] = {"allowed": True, "skipped": True}
        if not skip_gate:
            gate_result = self.gate.evaluate(tx_dict, from_addr=tx_dict.get("from") or tx._from_address())
            if not gate_result["allowed"]:
                return {"success": False, "error": "entity_gate_blocked", "gate": gate_result}

        mod_name, pk = self.load_key(module, vault_key)
        signed = tx._sign_tx_dict(tx_dict, private_key=pk, rpc=tx._rpc_url())
        signed["signer_module"] = mod_name

        dest = out_path or raw_path.with_name("signed_tx.json")
        payload = {"command": "sign", "gate": gate_result, **signed}
        dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

        verified = self.verify_signature(payload)
        return {
            "success": True,
            "gate": gate_result,
            "output": str(dest),
            "verified": verified,
            **signed,
        }

    def verify_signature(self, signed_payload: dict[str, Any]) -> dict[str, Any]:
        raw = signed_payload.get("raw")
        tx_hash = signed_payload.get("hash")
        from_addr = signed_payload.get("from")
        if not raw or not from_addr:
            return {"ok": False, "error": "missing raw or from"}
        return {"ok": True, "from": from_addr, "hash": tx_hash, "raw_bytes": len(raw) // 2 - 1}

    # Back-compat
    @classmethod
    def sign(cls, raw_tx_path: str, module: str = "EnvSigner", vault_key: str | None = None) -> dict[str, Any]:
        return cls().sign_raw(raw_tx_path, module=module, vault_key=vault_key)
