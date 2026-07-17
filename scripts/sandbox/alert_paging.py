"""Critical alert paging sink (webhook → Slack/PagerDuty/compatible).

Env:
  ALERT_PAGING_ENABLED=true|1
  ALERT_WEBHOOK_URL=https://...   (Slack incoming, PagerDuty Events v2 enqueue proxy, etc.)
  ALERT_PAGING_TIMEOUT_SEC=5
  ALERT_PAGING_SEVERITIES=critical,high   (comma; default critical)

Delivery failures are logged to artifacts but do **not** suppress local jsonl
(detection stays fail-closed via kill switch; paging is best-effort + drillable).
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
PAGE_LOG = ROOT / "artifacts" / "ops" / "paging-delivery.jsonl"

CRITICAL_KINDS = frozenset(
    {
        "rpc_mismatch",
        "direct_rpc_unavailable",
        "BLOCK_COMPROMISED_FUNDER",
        "post_sign_drift",
        "BLOCK_DIRECT_RPC_DOWN",
        "BLOCK_GUARD_BYPASS",
        "BLOCK_MAINNET_KEYS",
        "kill_switch",
        "value_cap",
        "paging_drill",
    }
)


def _enabled() -> bool:
    return os.getenv("ALERT_PAGING_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _severities() -> set[str]:
    raw = os.getenv("ALERT_PAGING_SEVERITIES", "critical")
    return {p.strip().lower() for p in raw.split(",") if p.strip()}


def should_page(entry: dict[str, Any]) -> bool:
    if not _enabled():
        return False
    if not os.getenv("ALERT_WEBHOOK_URL", "").strip():
        return False
    sev = str(entry.get("severity", "")).lower()
    kind = str(entry.get("type") or entry.get("kind") or entry.get("alert") or "")
    if sev in _severities():
        return True
    if kind in CRITICAL_KINDS:
        return True
    if str(entry.get("critical", "")).lower() in ("1", "true", "yes"):
        return True
    return False


def page_alert(entry: dict[str, Any]) -> dict[str, Any]:
    """POST JSON payload to ALERT_WEBHOOK_URL. Returns delivery record."""
    url = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    timeout = float(os.getenv("ALERT_PAGING_TIMEOUT_SEC", "5"))
    payload = {
        "text": (
            f"[HexStrike CRITICAL] {entry.get('type') or entry.get('kind') or 'alert'}: "
            f"{entry.get('detail') or entry.get('reason') or entry}"
        ),
        "severity": entry.get("severity", "critical"),
        "source": "hexstrike",
        "ts": datetime.now(timezone.utc).isoformat(),
        "alert": entry,
    }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "hexstrike-paging/1"},
        method="POST",
    )
    record: dict[str, Any] = {
        "ts": payload["ts"],
        "url_host": urllib.parse.urlparse(url).netloc if url else "",
        "ok": False,
    }
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            record["status"] = getattr(resp, "status", 200)
            record["ok"] = 200 <= int(record["status"]) < 300
            record["body_prefix"] = resp.read()[:200].decode("utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 — delivery must not raise into hot path
        record["error"] = str(exc)
        record["ok"] = False
    try:
        PAGE_LOG.parent.mkdir(parents=True, exist_ok=True)
        with PAGE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return record


def maybe_page(entry: dict[str, Any]) -> None:
    if should_page(entry):
        page_alert(entry)
