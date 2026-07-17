#!/usr/bin/env python3
"""Fire a synthetic critical alert to verify paging (Slack/PagerDuty webhook).

Usage:
  export ALERT_PAGING_ENABLED=true
  export ALERT_WEBHOOK_URL=https://hooks.slack.com/services/...
  python3 scripts/ops/paging_drill.py

Artifacts: artifacts/ops/paging-delivery.jsonl + artifacts/ops/paging-drill-<ts>.json
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "sandbox"))

from alert_paging import page_alert, should_page  # noqa: E402
from balance_guard import append_alert  # noqa: E402


def main() -> int:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "artifacts" / "ops"
    out_dir.mkdir(parents=True, exist_ok=True)

    entry = {
        "type": "paging_drill",
        "severity": "critical",
        "kind": "paging_drill",
        "detail": f"hexstrike paging drill {ts}",
        "critical": True,
        "ts": datetime.now(timezone.utc).isoformat(),
    }

    enabled = os.getenv("ALERT_PAGING_ENABLED", "")
    url = os.getenv("ALERT_WEBHOOK_URL", "")
    report = {
        "ts": ts,
        "ALERT_PAGING_ENABLED": enabled,
        "webhook_configured": bool(url.strip()),
        "should_page": should_page(entry),
    }

    # Also exercise production append_alert path (jsonl + maybe_page)
    append_alert(entry)
    delivery = page_alert(entry) if report["should_page"] else {"ok": False, "skipped": True}
    report["delivery"] = delivery
    report["verdict"] = "PASS" if delivery.get("ok") else ("SKIP_NO_CONFIG" if not url.strip() else "FAIL")

    path = out_dir / f"paging-drill-{ts}.json"
    path.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if report["verdict"] == "FAIL":
        return 1
    if report["verdict"] == "SKIP_NO_CONFIG":
        print("operator-owned: set ALERT_PAGING_ENABLED=true and ALERT_WEBHOOK_URL", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
