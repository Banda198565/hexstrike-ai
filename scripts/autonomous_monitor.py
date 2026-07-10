#!/usr/bin/env python3
"""Autonomous mempool monitor: master_context + RAG + unified indexer integration."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from context_utils import load_master_context
from api_auth import api_headers, get_api_key, hexstrike_handshake, load_dotenv
from crypto_rpc_orchestrator import (
    iter_txpool_txs,
    load_config,
    normalize_addr,
    rpc_with_fallback,
)
from rag_core import RagStorageError, search_history

DEFAULT_CONFIG = ROOT / "config" / "rpc_config.json"
ALERTS_LOG = ROOT / "artifacts" / "alerts.log"
DESKTOP_ALERT = Path.home() / "Desktop" / "on-chain-forensics" / "latest-alert.json"
EVA_ALERT = Path("/Volumes/Eva/alerts/latest-alert.json")
STATE_FILE = ROOT / "artifacts" / "monitor" / "autonomous_state.json"
PENDING_ACTION = ROOT / "artifacts" / "pending_action.json"

# Known bridge/sink addresses from prior investigations
SINK_KEYWORDS = ("bridge", "rhino", "sink", "offramp", "swap")
HIGH_RISK_LABELS = ("bridge", "sink", "rhino", "hot_wallet", "authority")
ADDR_RE = re.compile(r"0x[a-fA-F0-9]{40}")

RECONNECT_DELAY = 5.0
INDEXER_COOLDOWN_SEC = 60


def resolve_hexstrike_api(cfg: dict[str, Any]) -> tuple[str, str]:
    """Resolve server URL and API key from config + environment."""
    load_dotenv()
    api_cfg = cfg.get("hexstrike_api", {})
    server = api_cfg.get("server", "http://127.0.0.1:8888")
    env_name = api_cfg.get("api_key_env", "HEXSTRIKE_API_KEY")
    api_key = api_cfg.get("api_key") or os.environ.get(env_name, "") or get_api_key()
    return server, api_key.strip()


def api_handshake(cfg: dict[str, Any]) -> dict[str, Any]:
    server, api_key = resolve_hexstrike_api(cfg)
    result = hexstrike_handshake(server, api_key)
    result["server"] = server
    return result


def fetch_context_via_api(cfg: dict[str, Any]) -> dict[str, Any] | None:
    server, api_key = resolve_hexstrike_api(cfg)
    headers = api_headers(api_key)
    if not headers:
        return None
    try:
        resp = requests.get(f"{server.rstrip('/')}/api/context/latest", headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        body = resp.json()
        return body.get("context") or body
    except requests.RequestException:
        return None


def extract_addresses(obj: Any, found: dict[str, set[str]] | None = None, label: str = "") -> dict[str, set[str]]:
    """Recursively collect Ethereum addresses from nested JSON."""
    if found is None:
        found = {"all": set(), "labeled": set()}

    if isinstance(obj, dict):
        for key, val in obj.items():
            key_lower = str(key).lower()
            child_label = key_lower if any(k in key_lower for k in HIGH_RISK_LABELS) else label
            if isinstance(val, str) and ADDR_RE.fullmatch(val):
                addr = normalize_addr(val)
                found["all"].add(addr)
                if child_label:
                    found["labeled"].add(addr)
            else:
                extract_addresses(val, found, child_label)
    elif isinstance(obj, list):
        for item in obj:
            extract_addresses(item, found, label)
    elif isinstance(obj, str):
        for match in ADDR_RE.findall(obj):
            found["all"].add(normalize_addr(match))

    return found


def load_watched_addresses(config: dict[str, Any]) -> dict[str, Any]:
    """Build watchlist from master_context.json + rpc_config monitoring targets."""
    watched: set[str] = set()
    sinks: set[str] = set()
    sources: list[str] = []

    ctx = fetch_context_via_api(config) or load_master_context()
    if ctx:
        sources.append("master_context.json")
        for entry in ctx.get("entries", []):
            data = entry.get("data", entry)
            extracted = extract_addresses(data)
            watched.update(extracted["all"])
            sinks.update(extracted["labeled"])

    mon = config.get("monitoring", {})
    for addr in mon.get("target_contracts", []):
        watched.add(normalize_addr(addr))
        sources.append("rpc_config.monitoring.target_contracts")

    # Explicit sinks from forensics knowledge base
    for addr in (
        "0xb80a582fa430645a043bb4f6135321ee01005fef",  # Rhino.fi
        "0x4943f5e7f4e450d48ae82026163ecde8a52c53da",  # hot wallet
        "0x730ea0231808f42a20f8921ba7fbc788226768f5",  # authority
    ):
        norm = normalize_addr(addr)
        watched.add(norm)
        sinks.add(norm)

    return {
        "watched": watched,
        "sinks": sinks,
        "sources": sources,
    }


def tx_context_hits(tx: dict[str, Any], watched: set[str]) -> list[str]:
    frm = normalize_addr(tx.get("from"))
    to = normalize_addr(tx.get("to"))
    hits = []
    if frm in watched:
        hits.append(f"from:{frm}")
    if to in watched:
        hits.append(f"to:{to}")
    return hits


def is_high_risk(tx: dict[str, Any], sinks: set[str]) -> tuple[bool, str]:
    frm = normalize_addr(tx.get("from"))
    to = normalize_addr(tx.get("to"))
    if to in sinks:
        return True, "interaction_with_known_sink"
    if frm in sinks:
        return True, "funds_from_known_sink"
    input_lower = (tx.get("input") or "").lower()
    if any(kw in input_lower for kw in SINK_KEYWORDS):
        return True, "calldata_bridge_keyword"
    return False, ""


def rag_lookup(tx: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    """Search RAG history; return hits and whether pattern looks unknown."""
    frm = tx.get("from", "")
    to = tx.get("to", "")
    query = (
        f"on-chain transaction from {frm} to {to} "
        f"bridge sink rhino offramp pattern history"
    )
    try:
        hits = search_history(query, top_k=3)
    except (RagStorageError, OSError, ImportError) as exc:
        return [], True

    if not hits:
        return [], True

    combined = " ".join(h.get("snippet", "") for h in hits).lower()
    frm_l = normalize_addr(frm)
    to_l = normalize_addr(to)
    known = frm_l in combined or to_l in combined or "rhino" in combined or "bridge" in combined
    # LanceDB cosine distance: lower = more similar
    best_score = min((h.get("score") or 1.0) for h in hits)
    unknown = not known or best_score > 0.85
    return hits, unknown


def write_alert(alert: dict[str, Any]) -> None:
    ALERTS_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(alert, ensure_ascii=False)
    with ALERTS_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")

    payload = json.dumps(alert, indent=2, ensure_ascii=False) + "\n"
    DESKTOP_ALERT.parent.mkdir(parents=True, exist_ok=True)
    DESKTOP_ALERT.write_text(payload, encoding="utf-8")

    if EVA_ALERT.parent.parent.exists():
        EVA_ALERT.parent.mkdir(parents=True, exist_ok=True)
        EVA_ALERT.write_text(payload, encoding="utf-8")

    pending = {
        "status": "awaiting_operator_review",
        "created_at": alert.get("timestamp"),
        "alert_type": alert.get("alert_type"),
        "message": alert.get("message"),
        "transaction": {
            "hash": alert.get("hash"),
            "from": alert.get("from"),
            "to": alert.get("to"),
            "value": alert.get("value"),
            "pool": alert.get("pool"),
        },
        "rag_context": alert.get("rag_hits", [])[:2],
        "recommended_actions": [
            "Review alert in artifacts/alerts.log",
            "Cross-check RAG snippets against master_context.json",
            "Manual decision required — no auto-broadcast",
        ],
    }
    PENDING_ACTION.write_text(json.dumps(pending, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def trigger_indexer() -> dict[str, Any]:
    script = ROOT / "scripts" / "unified_indexer.py"
    proc = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    return {
        "returncode": proc.returncode,
        "stdout": proc.stdout.strip(),
        "stderr": proc.stderr.strip(),
    }


def load_state() -> dict[str, Any]:
    if not STATE_FILE.is_file():
        return {"seen_hashes": [], "last_indexer_run": 0}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"seen_hashes": [], "last_indexer_run": 0}


def save_state(state: dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def process_transaction(
    tx: dict[str, Any],
    watched: set[str],
    sinks: set[str],
    rpc_url: str,
) -> dict[str, Any] | None:
    hits = tx_context_hits(tx, watched)
    if not hits:
        return None

    high_risk, risk_reason = is_high_risk(tx, sinks)
    rag_hits, unknown_pattern = rag_lookup(tx)

    if not (high_risk or unknown_pattern):
        return None

    alert_type = "HIGH_RISK_REPEAT" if rag_hits and not unknown_pattern else "HIGH_RISK_UNKNOWN"
    if high_risk and rag_hits and not unknown_pattern:
        message = (
            f"Pattern match: {tx.get('from')} -> {tx.get('to')} "
            f"matches prior documentation ({risk_reason})."
        )
    elif high_risk:
        message = f"HIGH RISK: {risk_reason} — {tx.get('from')} -> {tx.get('to')}"
    else:
        message = f"UNKNOWN pattern: {tx.get('from')} -> {tx.get('to')} — not in RAG history"

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "alert_type": alert_type,
        "message": message,
        "rpc": rpc_url,
        "pool": tx.get("pool"),
        "hash": tx.get("hash"),
        "from": tx.get("from"),
        "to": tx.get("to"),
        "value": tx.get("value"),
        "context_hits": hits,
        "high_risk": high_risk,
        "risk_reason": risk_reason,
        "unknown_pattern": unknown_pattern,
        "rag_hits": rag_hits,
    }


def run_monitor(
    config_path: Path,
    poll_interval: float = 1.0,
    timeout: float = 8.0,
    duration_seconds: int | None = None,
) -> dict[str, Any]:
    cfg = load_config(config_path)
    endpoints = [cfg["primary"], *cfg.get("fallbacks", [])]
    poll_interval = float(cfg.get("monitoring", {}).get("poll_interval_seconds", poll_interval))

    handshake = api_handshake(cfg)
    if handshake.get("success"):
        print(f"[handshake] OK — {handshake['server']} (entries={handshake.get('data', {}).get('entry_count', '?')})")
    else:
        print(f"[handshake] WARN — {handshake.get('error')} (falling back to local context files)")

    watch = load_watched_addresses(cfg)
    watched = watch["watched"]
    sinks = watch["sinks"]

    state = load_state()
    seen_hashes: set[str] = set(state.get("seen_hashes", []))
    last_indexer_run = float(state.get("last_indexer_run", 0))

    print(f"[monitor] RPC primary: {cfg['primary']}")
    print(f"[monitor] Watching {len(watched)} addresses | sinks={len(sinks)}")
    print(f"[monitor] Context sources: {', '.join(watch['sources']) or 'rpc_config only'}")
    print(f"[monitor] Alerts log: {ALERTS_LOG}")
    print(f"[monitor] Desktop alert: {DESKTOP_ALERT}")

    start = time.time()
    polls = 0
    alerts_count = 0
    txs_seen = 0
    active_rpc = cfg["primary"]

    while True:
        polls += 1
        try:
            active_rpc, resp = rpc_with_fallback(endpoints, "txpool_content", [], timeout=timeout)
            content = resp.get("result") or {}
        except Exception as exc:
            print(f"[warn] RPC error (poll {polls}): {exc} — reconnect in {RECONNECT_DELAY}s")
            time.sleep(RECONNECT_DELAY)
            if duration_seconds and time.time() - start >= duration_seconds:
                break
            continue

        for tx in iter_txpool_txs(content):
            tx_hash = tx.get("hash")
            if not tx_hash or tx_hash in seen_hashes:
                continue
            seen_hashes.add(tx_hash)
            txs_seen += 1

            alert = process_transaction(tx, watched, sinks, active_rpc)
            if not alert:
                continue

            alerts_count += 1
            write_alert(alert)
            print(f"[ALERT] {alert['alert_type']} {tx_hash}")
            print(f"        {alert['message']}")
            if alert.get("rag_hits"):
                top = alert["rag_hits"][0]
                print(f"        RAG: {top.get('source_file')} (score={top.get('score')})")

            now = time.time()
            if now - last_indexer_run >= INDEXER_COOLDOWN_SEC:
                idx = trigger_indexer()
                last_indexer_run = now
                print(f"[indexer] unified_indexer exit={idx['returncode']}")

        if polls % 10 == 0:
            save_state({
                "seen_hashes": list(seen_hashes)[-10000:],
                "last_indexer_run": last_indexer_run,
                "last_poll": polls,
                "rpc": active_rpc,
            })

        if duration_seconds and time.time() - start >= duration_seconds:
            break
        time.sleep(poll_interval)

    save_state({
        "seen_hashes": list(seen_hashes)[-10000:],
        "last_indexer_run": last_indexer_run,
        "last_poll": polls,
        "rpc": active_rpc,
    })

    return {
        "polls": polls,
        "txs_seen": txs_seen,
        "alerts": alerts_count,
        "duration_sec": round(time.time() - start, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Autonomous mempool monitor with RAG + unified context")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG))
    parser.add_argument("--duration", type=int, default=None, help="Run N seconds then exit (default: infinite)")
    parser.add_argument("--timeout", type=float, default=8.0)
    args = parser.parse_args()

    try:
        summary = run_monitor(
            Path(args.config),
            timeout=args.timeout,
            duration_seconds=args.duration,
        )
    except KeyboardInterrupt:
        print("\n[monitor] stopped by user")
        return 0

    print(json.dumps({"success": True, **summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
