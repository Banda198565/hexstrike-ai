#!/usr/bin/env python3
"""sms_alert.py — unified SMS alert channel (SIM800C for now).

Reads incidents from artifacts/alerts.log or --message, sends via SIM800C AT.
Safe defaults: rate-limits (max 5 SMS / hour), dry-run when --port missing.

Usage:
  python3 scripts/sms_alert.py --to +7... --message "HW_ALERT hot wallet outflow"
  python3 scripts/sms_alert.py --to +7... --tail-alerts 5     # send last N unseen alerts
  python3 scripts/sms_alert.py --dry-run --message "test"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

RATE_STATE = ROOT / "artifacts" / "sms_alerts_state.json"
ALERTS_LOG = ROOT / "artifacts" / "alerts.log"
DEFAULT_MAX_PER_HOUR = 5


def _load_state() -> dict:
    if RATE_STATE.is_file():
        try:
            return json.loads(RATE_STATE.read_text())
        except Exception:
            pass
    return {"sent_timestamps": [], "last_alert_line": 0}


def _save_state(state: dict) -> None:
    RATE_STATE.parent.mkdir(parents=True, exist_ok=True)
    RATE_STATE.write_text(json.dumps(state, indent=2))


def _rate_ok(state: dict, max_per_hour: int) -> bool:
    now = time.time()
    cutoff = now - 3600
    state["sent_timestamps"] = [t for t in state.get("sent_timestamps", []) if t > cutoff]
    return len(state["sent_timestamps"]) < max_per_hour


def send_sms(port: str, baud: int, to: str, text: str, pin: str | None = None, dry_run: bool = False) -> dict:
    import sim800c_at
    sim = sim800c_at.SIM800C(port, baud, timeout=3.0, dry_run=dry_run)
    sim.open()
    result = {"to": to, "sent": False, "dry_run": dry_run}
    try:
        sim.send("AT")
        sim.send("ATE0")
        pin_state = sim.send("AT+CPIN?")
        if "SIM PIN" in pin_state["response"] and pin:
            sim.send(f'AT+CPIN="{pin}"', wait=1.5)
        sim.send("AT+CMGF=1")
        sim.send('AT+CSCS="GSM"')
        if dry_run:
            result["sent"] = True
            result["note"] = "dry-run — SMS not delivered"
        else:
            assert sim.ser is not None
            sim.ser.write(f'AT+CMGS="{to}"\r'.encode())
            time.sleep(0.6)
            resp = sim.ser.read(4096).decode("utf-8", errors="replace")
            if ">" not in resp:
                result["error"] = f"no prompt: {resp[:200]}"
                return result
            sim.ser.write(text.encode("utf-8", errors="ignore") + b"\x1a")
            sim.ser.flush()
            time.sleep(4.0)
            resp = sim.ser.read(8192).decode("utf-8", errors="replace")
            result["response"] = resp.strip()[:400]
            result["sent"] = "+CMGS:" in resp
    finally:
        sim.close()
    return result


def tail_new_alerts(n: int, state: dict) -> list[str]:
    if not ALERTS_LOG.is_file():
        return []
    lines = ALERTS_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
    start = state.get("last_alert_line", 0)
    new = lines[start:]
    state["last_alert_line"] = len(lines)
    return new[-n:] if n > 0 else new


def main() -> int:
    p = argparse.ArgumentParser(description="SMS alert channel (SIM800C)")
    p.add_argument("--port", default=os.environ.get("SIM800C_PORT"))
    p.add_argument("--baud", type=int, default=int(os.environ.get("SIM800C_BAUD", 115200)))
    p.add_argument("--to", default=os.environ.get("SIM800C_TO"))
    p.add_argument("--pin", default=os.environ.get("SIM800C_PIN"))
    p.add_argument("--message")
    p.add_argument("--tail-alerts", type=int, default=0, help="Send last N unseen lines from artifacts/alerts.log")
    p.add_argument("--max-per-hour", type=int, default=DEFAULT_MAX_PER_HOUR)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    if not args.to:
        raise SystemExit("--to or SIM800C_TO required")

    messages: list[str] = []
    if args.message:
        messages.append(args.message)
    if args.tail_alerts > 0:
        state = _load_state()
        new_alerts = tail_new_alerts(args.tail_alerts, state)
        messages.extend(new_alerts)
        _save_state(state)
    if not messages:
        raise SystemExit("nothing to send: pass --message or --tail-alerts N")

    state = _load_state()
    results: list[dict] = []
    for msg in messages[: args.max_per_hour]:
        if not _rate_ok(state, args.max_per_hour):
            results.append({"skipped": True, "reason": f"rate limit >= {args.max_per_hour}/hour"})
            break
        if not args.port and not args.dry_run:
            raise SystemExit("--port or SIM800C_PORT required (or --dry-run)")
        text = msg.strip()[:160]
        r = send_sms(args.port or "/dev/null", args.baud, args.to, text, args.pin, args.dry_run)
        if r.get("sent") and not args.dry_run:
            state["sent_timestamps"].append(time.time())
            _save_state(state)
        results.append({"message": text, **r})

    print(json.dumps({"command": "sms_alert", "count": len(results), "results": results}, indent=2))
    return 0 if all(r.get("sent") or r.get("skipped") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
