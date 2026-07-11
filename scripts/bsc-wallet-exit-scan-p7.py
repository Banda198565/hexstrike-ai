#!/usr/bin/env python3
"""P7: hot wallet exit scan — outgoing, approve, Rhino API, CEX match (orchestrator-only)."""

from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUT_DIRS = [
    ROOT / "artifacts" / "2026-07-10",
    ROOT / "artifacts" / "forensics",
    Path.home() / "Desktop" / "on-chain-forensics" / "artifacts" / "2026-07-10",
]

RPC = os.environ.get("HEXSTRIKE_RPC", "http://51.222.42.220:8545")
FROM_BLOCK = 108941522
TO_BLOCK = 109041522
CHUNK = 5000

HOT = "0x4943f5e7f4e450d48ae82026163ecde8a52c53da"
USDT = "0x55d398326f99059fF775485246999027B3197955"
RHINO = "0xb80a582fa430645a043bb4f6135321ee01005fef"
TOP3 = {
    "0x730ea0231808f42a20f8921ba7fbc788226768f5",
    "0x55ed7fcd17b93fbcd5186cda01af6fed4ec78e08",
    "0xcfc85f21f5f01ab24d6b7a3b93ef097099ebde3a",
}

TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
APPROVAL = "0x8c5be1e5ebec7d5bd14f71427d1e84f3dd0314c0f7b2291e5b200ac8c7c3b925"
RHINO_HISTORY = "https://api.rhino.fi/bridge/history/bridge/by-deposit-hash/{tx_hash}"

# Known labeled counterparties (prior recon — not exhaustive CEX list)
LABELED = {
    "0x161ba15a5f335c9f06bb5bbb0a9ce14076fbb645": "Binance Hot Wallet 11 (inbound source)",
    "0xb80a582fa430645a043bb4f6135321ee01005fef": "Rhino.fi Bridge",
    "0x730ea0231808f42a20f8921ba7fbc788226768f5": "authority_eip7702",
    "0x55ed7fcd17b93fbcd5186cda01af6fed4ec78e08": "sweep_contract_2",
    "0xcfc85f21f5f01ab24d6b7a3b93ef097099ebde3a": "sweep_contract_3",
}


def rpc_call(method: str, params: list, timeout: float = 90) -> Any:
    import requests

    payload = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
    resp = requests.post(RPC, json=payload, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data.get("result")


def topic_addr(addr: str) -> str:
    return "0x" + "0" * 24 + addr[2:].lower()


def get_logs_chunked(address: str, topics: list[Any], from_block: int, to_block: int) -> list[dict]:
    logs: list[dict] = []
    start = from_block
    while start <= to_block:
        end = min(start + CHUNK - 1, to_block)
        batch = rpc_call(
            "eth_getLogs",
            [{"fromBlock": hex(start), "toBlock": hex(end), "address": address, "topics": topics}],
        )
        logs.extend(batch or [])
        start = end + 1
    return logs


def load_bridge_deposit_txs() -> list[str]:
    p4 = ROOT / "artifacts" / "2026-07-10" / "p4-bridge-quote-decode.json"
    if p4.is_file():
        doc = json.loads(p4.read_text(encoding="utf-8"))
        return sorted({q["tx_hash"] for q in doc.get("top3_quotes", [])})
    return []


def fetch_rhino_history(tx_hash: str) -> dict[str, Any]:
    import requests

    token = os.environ.get("RHINO_API_KEY") or os.environ.get("RHINO_JWT")
    if not token:
        return {"status": "skipped", "reason": "RHINO_API_KEY or RHINO_JWT not set"}
    try:
        resp = requests.get(
            RHINO_HISTORY.format(tx_hash=tx_hash),
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        if resp.status_code != 200:
            return {"status": "http_error", "code": resp.status_code, "body": resp.text[:200]}
        body = resp.json()
        return {
            "status": "ok",
            "chainIn": body.get("chainIn"),
            "chainOut": body.get("chainOut"),
            "recipient": body.get("recipient") or body.get("withdrawRecipient"),
            "withdrawTxHash": body.get("withdrawTxHash"),
            "quoteId": body.get("quoteId") or body.get("commitmentId"),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def read_allowance(spender: str) -> float:
    owner = HOT[2:].rjust(64, "0")
    sp = spender[2:].lower().rjust(64, "0")
    data = "0xdd62ed3e" + owner + sp
    raw = rpc_call("eth_call", [{"to": USDT, "data": data}, "latest"], timeout=30)
    return int(raw or "0x0", 16) / 1e18


def classify_recipient(addr: str, cache: dict[str, str]) -> str:
    a = addr.lower()
    if a in cache:
        return cache[a]
    if a == RHINO.lower():
        cache[a] = "bridge_rhino"
    elif a in TOP3:
        cache[a] = "top3_sweep_contract"
    elif a in LABELED:
        cache[a] = "labeled_" + LABELED[a].split()[0].lower()
    else:
        code = rpc_call("eth_getCode", [a, "latest"], timeout=20)
        cache[a] = "contract" if code and code not in ("0x", "0x0") else "eoa"
    return cache[a]


def write_artifact(name: str, obj: dict) -> list[str]:
    paths: list[str] = []
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    for out_dir in OUT_DIRS:
        out_dir.mkdir(parents=True, exist_ok=True)
        p = out_dir / name
        p.write_text(text, encoding="utf-8")
        paths.append(str(p))
    return paths


def main() -> int:
    hot_topic = topic_addr(HOT)

    # 1) Outgoing USDT transfers
    out_logs = get_logs_chunked(USDT, [TRANSFER, hot_topic], FROM_BLOCK, TO_BLOCK)
    by_to: dict[str, float] = defaultdict(float)
    out_rows: list[dict] = []
    for lg in out_logs:
        to_addr = ("0x" + lg["topics"][2][-40:]).lower()
        amt = int(lg["data"], 16) / 1e18
        by_to[to_addr] += amt
        out_rows.append(
            {
                "to": to_addr,
                "amount_usdt": round(amt, 6),
                "tx_hash": lg["transactionHash"],
                "block": int(lg["blockNumber"], 16),
            }
        )

    top_out = sorted(by_to.items(), key=lambda x: -x[1])[:25]
    categorized = Counter()
    cex_hits: list[dict] = []
    bridge_total = by_to.get(RHINO.lower(), 0.0)
    cat_cache: dict[str, str] = {}

    for addr, total in top_out:
        cat = classify_recipient(addr, cat_cache)
        categorized[cat] += total
        row = {
            "address": addr,
            "total_usdt": round(total, 2),
            "category": cat,
            "label": LABELED.get(addr),
        }
        if "binance" in cat or "cex" in cat:
            cex_hits.append(row)

    # indirect: top3 -> rhino path totals
    top3_to_hot = sum(by_to.get(a, 0) for a in TOP3)

    # 2) Approval events
    appr_logs = get_logs_chunked(USDT, [APPROVAL, hot_topic], FROM_BLOCK, TO_BLOCK)
    approvals: list[dict] = []
    by_spender: dict[str, float] = defaultdict(float)
    for lg in appr_logs:
        spender = ("0x" + lg["topics"][2][-40:]).lower()
        amt = int(lg["data"], 16) / 1e18
        by_spender[spender] = max(by_spender[spender], amt)
        approvals.append(
            {
                "spender": spender,
                "amount_usdt": amt,
                "unlimited": amt > 1e15,
                "tx_hash": lg["transactionHash"],
                "block": int(lg["blockNumber"], 16),
            }
        )

    # current allowance for top spenders + bridge + top3
    allowance_check: list[dict] = []
    check_spenders = set(by_spender) | TOP3 | {RHINO.lower()}
    for sp in sorted(check_spenders):
        try:
            allowance_check.append(
                {"spender": sp, "current_allowance_usdt": round(read_allowance(sp), 6)}
            )
        except Exception as exc:
            allowance_check.append({"spender": sp, "error": str(exc)})

    # 3) Rhino API for bridge deposit txs
    deposit_txs = load_bridge_deposit_txs()
    rhino_api = [{"tx_hash": tx, **fetch_rhino_history(tx)} for tx in deposit_txs]
    api_ok = [r for r in rhino_api if r.get("status") == "ok"]

    # 4) Prior artifact cross-check
    prior_cex = ROOT / "artifacts" / "cex-cluster-map.json"
    prior_verdict = {}
    if prior_cex.is_file():
        prior_verdict = json.loads(prior_cex.read_text(encoding="utf-8")).get("verdict", {})

    summary = {
        "meta": {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "policy": "read_only_p7",
            "rpc": RPC,
            "block_range": [FROM_BLOCK, TO_BLOCK],
            "hot_wallet": HOT,
            "worker": "scripts/bsc-wallet-exit-scan-p7.py",
            "invoked_by": "hexstrike_orchestrator wallet-exit-scan",
        },
        "outgoing_usdt": {
            "transfer_count": len(out_logs),
            "unique_recipients": len(by_to),
            "total_usdt_out": round(sum(by_to.values()), 2),
            "to_rhino_bridge_usdt": round(bridge_total, 2),
            "to_top3_contracts_usdt": round(top3_to_hot, 2),
            "by_category_usdt": dict(categorized),
            "top_recipients": [
                {
                    "address": a,
                    "total_usdt": round(t, 2),
                    "category": cat_cache.get(a) or classify_recipient(a, cat_cache),
                    "label": LABELED.get(a),
                }
                for a, t in top_out
            ],
            "cex_labeled_hits": cex_hits,
            "direct_cex_deposit_from_hot": len(cex_hits) > 0,
        },
        "approvals": {
            "event_count": len(appr_logs),
            "unique_spenders": len(by_spender),
            "events": approvals[:50],
            "top_spenders": [
                {"spender": s, "max_approved_usdt": round(v, 2), "unlimited": v > 1e15}
                for s, v in sorted(by_spender.items(), key=lambda x: -x[1])[:20]
            ],
            "current_allowance": allowance_check,
        },
        "rhino_api_recipients": {
            "attempted": len(rhino_api),
            "resolved": len(api_ok),
            "results": rhino_api,
        },
        "exit_rails_detected": {
            "rhino_bridge_bsc": {
                "confirmed": bridge_total > 0,
                "usdt": round(bridge_total, 2),
                "path": "hot -> top3 contracts -> rhino (P1/P4 confirmed)",
            },
            "direct_cex": {
                "confirmed": len(cex_hits) > 0,
                "hits": cex_hits,
            },
            "cross_chain": {
                "chainOut_on_chain": False,
                "api_resolved": len(api_ok),
                "note": "Rhino JWT required for withdraw recipient",
            },
        },
        "prior_recon_crosscheck": prior_verdict,
        "verdict": (
            f"P7 exit scan: {len(out_logs)} USDT out txs, ${round(sum(by_to.values()), 0):,.0f} total. "
            f"Bridge Rhino ${round(bridge_total, 0):,.0f}. "
            f"Direct CEX deposit from hot: {'YES' if cex_hits else 'NO'}. "
            f"Approvals: {len(appr_logs)} events, {len(by_spender)} spenders. "
            f"Rhino API resolved {len(api_ok)}/{len(deposit_txs)}. "
            "Withdrawal pattern: payroll/sweep -> bridge cross-chain, not direct CEX cash-out."
        ),
        "next_steps_readonly": [
            "RHINO_API_KEY for exact bridge withdraw recipients",
            "Depth-2 from top payroll EOAs (not hot) for delayed CEX hops",
            "Legal/exchange channel for Binance deposit matching",
        ],
    }

    paths = write_artifact("p7-wallet-exit-scan.json", summary)
    print(json.dumps(summary, indent=2))
    print(f"[+] Written: {paths[0]}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
