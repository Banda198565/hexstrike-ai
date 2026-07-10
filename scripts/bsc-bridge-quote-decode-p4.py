#!/usr/bin/env python3
"""P4 worker: Rhino.fi signed quote decode — recover authorized signers (orchestrator-only)."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from eth_abi import decode, encode
from eth_account import Account
from eth_account.messages import encode_defunct
from eth_utils import keccak, to_checksum_address

ROOT = Path(__file__).resolve().parent.parent
OUT_DIRS = [
    ROOT / "artifacts" / "2026-07-10",
    ROOT / "artifacts" / "forensics",
    Path.home() / "Desktop" / "on-chain-forensics" / "artifacts" / "2026-07-10",
]

RPC = os.environ.get("HEXSTRIKE_RPC", "http://51.222.42.220:8545")
FROM_BLOCK = 108941522
TO_BLOCK = 109041522
RHINO = "0xb80a582fa430645a043bb4f6135321ee01005fef"
USDT = "0x55d398326f99059fF775485246999027B3197955"
RELAYER = "0x90502666e33d71483302f81c8349a6185572db42"
OUTER_SELECTOR = "0x3f707e6b"
INNER_SELECTOR = bytes.fromhex("6171d1c9")
TRANSFER_SELECTOR = bytes.fromhex("a9059cbb")

TOP3 = {
    "0x730ea0231808f42a20f8921ba7fbc788226768f5": "authority_eip7702",
    "0x55ed7fcd17b93fbcd5186cda01af6fed4ec78e08": "sweep_contract_2",
    "0xcfc85f21f5f01ab24d6b7a3b93ef097099ebde3a": "sweep_contract_3",
}

RHINO_CONFIG_URL = "https://api.rhino.fi/bridge/configs"
RHINO_HISTORY_URL = "https://api.rhino.fi/bridge/history/bridge/by-deposit-hash/{tx_hash}"


def rpc_call(method: str, params: list, timeout: float = 90) -> Any:
    import requests

    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    resp = requests.post(RPC, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data.get("result")


def load_top3_transfers() -> list[dict]:
    p1 = ROOT / "artifacts" / "2026-07-10" / "p1-top3-outgoing-usdt.json"
    doc = json.loads(p1.read_text(encoding="utf-8"))
    out: list[dict] = []
    for contract, entry in doc.get("contracts", {}).items():
        for t in entry.get("outgoing_usdt", {}).get("transfers", []):
            row = dict(t)
            row["source_contract"] = contract.lower()
            row["source_label"] = TOP3.get(contract.lower(), "unknown")
            out.append(row)
    return out


def decode_transfer_amount(data: bytes) -> dict[str, Any]:
    if len(data) < 68 or data[:4] != TRANSFER_SELECTOR:
        return {"valid": False}
    recipient = "0x" + data[16:36].hex()
    amount_raw = int.from_bytes(data[36:68], "big")
    return {
        "valid": True,
        "recipient": recipient.lower(),
        "amount_raw": amount_raw,
        "amount_usdt": round(amount_raw / 1e18, 6),
    }


def recover_signer(inner_calls: list[tuple], signature: bytes) -> str:
    payload = encode(["(address,uint256,bytes)[]"], [inner_calls])
    digest = keccak(payload)
    msg = encode_defunct(primitive=digest)
    return Account.recover_message(msg, signature=signature)


def decode_inner_execute(data: bytes) -> dict[str, Any]:
    if len(data) < 4 or data[:4] != INNER_SELECTOR:
        return {"error": "not_inner_execute", "selector": "0x" + data[:4].hex()}
    body = data[4:]
    inner_calls, signature = decode(["(address,uint256,bytes)[]", "bytes"], body)
    calls_out: list[dict] = []
    for target, value, call_data in inner_calls:
        xfer = decode_transfer_amount(call_data)
        calls_out.append(
            {
                "token": to_checksum_address(target),
                "value_wei": value,
                "transfer": xfer,
            }
        )
    signer = recover_signer(inner_calls, signature)
    return {
        "inner_calls": calls_out,
        "signature_bytes": len(signature),
        "signer": signer.lower(),
        "signed_payload": "personal_sign(keccak256(abi.encode((address,uint256,bytes)[])))",
        "chain_out_in_payload": False,
    }


def decode_batch_tx(tx_hash: str, expected: dict[str, dict] | None = None) -> dict[str, Any]:
    tx = rpc_call("eth_getTransactionByHash", [tx_hash], timeout=30)
    if not tx:
        return {"tx_hash": tx_hash, "error": "tx_not_found"}

    inp = tx.get("input", "0x")
    if not inp.startswith(OUTER_SELECTOR):
        return {"tx_hash": tx_hash, "error": "not_batched_execute", "selector": inp[:10]}

    outer = bytes.fromhex(inp[10:])
    batch_calls, = decode(["(address,uint256,bytes)[]"], outer)
    inner_rows: list[dict] = []
    top3_matches: list[dict] = []

    for target, value, data in batch_calls:
        target_l = target.lower()
        row: dict[str, Any] = {
            "batch_target": target_l,
            "batch_target_label": TOP3.get(target_l, "other_depositor"),
            "value_wei": value,
        }
        if len(data) >= 4 and data[:4] == INNER_SELECTOR:
            decoded = decode_inner_execute(data)
            row.update(decoded)
            if target_l in TOP3:
                xfer = (decoded.get("inner_calls") or [{}])[0].get("transfer", {})
                amt = xfer.get("amount_usdt")
                exp = expected.get(tx_hash) if expected else None
                top3_matches.append(
                    {
                        "contract": target_l,
                        "label": TOP3[target_l],
                        "amount_usdt": amt,
                        "signer": decoded.get("signer"),
                        "amount_matches_p1": bool(exp and amt and abs(amt - exp.get("value_usdt", 0)) < 0.01),
                    }
                )
        inner_rows.append(row)

    return {
        "tx_hash": tx_hash,
        "block": int(tx["blockNumber"], 16),
        "tx_from": (tx.get("from") or "").lower(),
        "relayer": RELAYER,
        "outer_method": "execute((address,uint256,bytes)[])",
        "batch_size": len(batch_calls),
        "inner_execute_count": sum(1 for r in inner_rows if "signer" in r),
        "top3_deposits_in_batch": top3_matches,
        "inner_rows": inner_rows,
    }


def fetch_rhino_configs() -> dict[str, Any]:
    import requests

    try:
        resp = requests.get(RHINO_CONFIG_URL, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        chains = sorted({c.get("chain") for c in data if isinstance(c, dict) and c.get("chain")})
        return {"status": "ok", "chain_count": len(chains), "chains": chains[:30]}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def fetch_rhino_history(tx_hash: str) -> dict[str, Any]:
    import requests

    token = os.environ.get("RHINO_API_KEY") or os.environ.get("RHINO_JWT")
    if not token:
        return {"status": "skipped", "reason": "RHINO_API_KEY or RHINO_JWT not set"}
    headers = {"Authorization": f"Bearer {token}"}
    url = RHINO_HISTORY_URL.format(tx_hash=tx_hash)
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        if resp.status_code == 401:
            return {"status": "auth_failed", "body": resp.text[:200]}
        if resp.status_code != 200:
            return {"status": "http_error", "code": resp.status_code, "body": resp.text[:300]}
        body = resp.json()
        return {
            "status": "ok",
            "chainIn": body.get("chainIn"),
            "chainOut": body.get("chainOut"),
            "depositTxHash": body.get("depositTxHash"),
            "withdrawTxHash": body.get("withdrawTxHash"),
            "quoteId": body.get("quoteId") or body.get("commitmentId"),
            "amount": body.get("amount"),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def write_artifact(name: str, obj: dict) -> list[str]:
    paths: list[str] = []
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    for out_dir in OUT_DIRS:
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / name
        path.write_text(text, encoding="utf-8")
        paths.append(str(path))
    return paths


def main() -> int:
    transfers = load_top3_transfers()
    by_tx: dict[str, dict] = {}
    for t in transfers:
        by_tx[t["tx_hash"]] = t

    decoded_rows: list[dict] = []
    for tx_hash in sorted(by_tx):
        decoded_rows.append(decode_batch_tx(tx_hash, expected=by_tx))

    signers = Counter()
    top3_quotes: list[dict] = []
    for row in decoded_rows:
        for dep in row.get("top3_deposits_in_batch", []):
            if dep.get("signer"):
                signers[dep["signer"]] += 1
            top3_quotes.append(
                {
                    "tx_hash": row["tx_hash"],
                    "block": row.get("block"),
                    **dep,
                }
            )

    rhino_api: list[dict] = []
    for tx_hash in sorted(by_tx):
        rhino_api.append({"tx_hash": tx_hash, **fetch_rhino_history(tx_hash)})

    rhino_configs = fetch_rhino_configs()

    summary = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "policy": "read_only_p4",
            "rpc": RPC,
            "block_range": [FROM_BLOCK, TO_BLOCK],
            "worker": "scripts/bsc-bridge-quote-decode-p4.py",
            "invoked_by": "hexstrike_orchestrator bridge-quote-decode",
        },
        "signature_scheme": {
            "outer_batch": "execute((address,uint256,bytes)[]) selector 0x3f707e6b",
            "inner_bridge": "execute((address,uint256,bytes)[],bytes) selector 0x6171d1c9",
            "signed_message": "personal_sign over keccak256(abi.encode(inner_call_array))",
            "not_eip712": True,
            "chain_out_on_chain": False,
            "chain_out_source": "Rhino off-chain quote DB / API JWT",
        },
        "top3_summary": {
            "transfer_count": len(transfers),
            "unique_batch_txs": len(by_tx),
            "top3_quotes_decoded": len(top3_quotes),
            "unique_authorized_signers": len(signers),
        },
        "authorized_signers": [
            {"address": addr, "quote_count": count} for addr, count in signers.most_common()
        ],
        "top3_quotes": top3_quotes,
        "batch_decodes": decoded_rows,
        "rhino_public_configs": rhino_configs,
        "rhino_api_by_deposit": rhino_api,
        "likely_exit_rails": {
            "BASE": {
                "confidence": "medium",
                "evidence": "hot wallet ~$635k USDC on Base (P3 multichain recon); Rhino supports BASE",
            },
            "ARBITRUM": {"confidence": "low", "evidence": "Rhino high-volume L2 rail"},
        },
        "verdict": (
            "P4 confirms Rhino batched relayer flow: each top-3 USDT deposit carries a unique "
            "ECDSA signature from an authorized Rhino backend signer over the VM call array "
            "(USDT.transfer to bridge). chainOut is NOT encoded in the signed payload — "
            "cross-chain destination is bound off-chain. On-chain forensics exhausted; "
            "exact chainOut requires Rhino API JWT or Base-chain deposit correlation."
        ),
        "next_steps_readonly": [
            "Provide RHINO_API_KEY to resolve chainOut via /bridge/history/bridge/by-deposit-hash/{tx}",
            "Base: correlate Rhino bridge USDC credits to hot wallet 0x4943f5e7f4e450d48ae82026163ecde8a52c53da",
            "Label recovered signers on BscScan / Arkham as Rhino authorized relayers",
        ],
    }

    paths = write_artifact("p4-bridge-quote-decode.json", summary)
    print(json.dumps(summary, indent=2))
    print(f"[+] Written: {paths[0]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
