#!/usr/bin/env python3
"""Forward new lines from dust-drain-alerts.jsonl to Slack Incoming Webhook.

Usage:
  export SLACK_WEBHOOK_URL="https://hooks.slack.com/services/..."
  python3 scripts/slack_forwarder.py            # follow (default)
  python3 scripts/slack_forwarder.py --once     # process unread and exit

Reads Alert schema from detect_eip7702_dust_drain.py:
  victim, operator, sink, token, amount_human, delta_sec,
  block_dust, block_drain, tx_dust, tx_drain, ...
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ALERTS = ROOT / "artifacts" / "monitor" / "dust-drain-alerts.jsonl"
DEFAULT_POS = ROOT / "artifacts" / "monitor" / "slack-forwarder.pos"


def load_dotenv(path: Path | None = None) -> None:
    env_path = path or (ROOT / ".env")
    if not env_path.is_file():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except OSError:
        return


def setup_log() -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    return logging.getLogger("slack_forwarder")


def get_pos(path: Path) -> int:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return 0


def save_pos(path: Path, pos: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(pos) + "\n")


def send_slack(webhook: str, text: str, log: logging.Logger) -> bool:
    if not webhook:
        log.warning("SLACK_WEBHOOK_URL empty — skip send")
        return False
    payload = json.dumps({"text": text[:3500]}).encode("utf-8")
    req = urllib.request.Request(
        webhook,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 300:
                log.error("Slack HTTP %s", resp.status)
                return False
        return True
    except urllib.error.HTTPError as e:
        log.error("Slack HTTPError %s %s", e.code, e.read()[:200])
        return False
    except Exception as e:
        log.error("Slack send failed: %s", e)
        return False


def format_alert(alert: dict) -> str:
    amount = alert.get("amount_human", alert.get("amount", 0))
    try:
        amount_s = f"{float(amount):.6f}"
    except (TypeError, ValueError):
        amount_s = str(amount)
    dust_amt = alert.get("dust_eth", alert.get("dust_amount"))
    tx_dust = alert.get("tx_dust", alert.get("dust_tx", ""))
    tx_drain = alert.get("tx_drain", alert.get("drain_tx", ""))
    token = alert.get("token", alert.get("token_symbol", ""))
    operator = alert.get("operator", alert.get("operator_dust", ""))
    lines = [
        "🚨 *Обнаружена атака dust → drain*",
        f"• Жертва: `{alert.get('victim', '')}`",
        f"• Оператор: `{operator}`",
        f"• Sink: `{alert.get('sink', '')}`",
        f"• Токен: {token}",
        f"• Сумма слива: {amount_s}",
        f"• Задержка: {alert.get('delta_sec', 0)} сек",
        f"• Блок: dust={alert.get('block_dust', '')} drain={alert.get('block_drain', alert.get('block', ''))}",
        f"• Хэш пыли: `{tx_dust}`",
        f"• Хэш слива: `{tx_drain}`",
    ]
    if dust_amt is not None:
        try:
            lines.insert(6, f"• Сумма пыли (ETH): {float(dust_amt):.8f}")
        except (TypeError, ValueError):
            lines.insert(6, f"• Сумма пыли (ETH): {dust_amt}")
    if tx_dust or tx_drain:
        lines.append(
            f"• links: <https://etherscan.io/tx/{tx_dust}|dust> | "
            f"<https://etherscan.io/tx/{tx_drain}|drain>"
        )
    return "\n".join(lines)


def process_new(alerts_file: Path, pos_file: Path, webhook: str, log: logging.Logger) -> int:
    if not alerts_file.is_file():
        log.info("alerts file missing yet: %s", alerts_file)
        return 0
    pos = get_pos(pos_file)
    size = alerts_file.stat().st_size
    if pos > size:
        # file truncated/rotated
        pos = 0
    sent = 0
    with alerts_file.open("r", encoding="utf-8") as f:
        f.seek(pos)
        while True:
            line_start = f.tell()
            line = f.readline()
            if not line:
                break
            stripped = line.strip()
            if not stripped:
                continue
            try:
                alert = json.loads(stripped)
            except json.JSONDecodeError as e:
                log.error("bad json: %s", e)
                continue
            msg = format_alert(alert)
            if not webhook:
                log.warning("SLACK_WEBHOOK_URL empty — dry-run victim=%s", alert.get("victim"))
                sent += 1
                continue
            if send_slack(webhook, msg, log):
                sent += 1
                log.info("sent victim=%s", alert.get("victim"))
            else:
                # do not advance past failed line — retry next run
                save_pos(pos_file, line_start)
                return sent
        save_pos(pos_file, f.tell())
    return sent


def follow(alerts_file: Path, pos_file: Path, webhook: str, log: logging.Logger, interval: float) -> None:
    log.info("follow mode alerts=%s interval=%ss", alerts_file, interval)
    while True:
        try:
            process_new(alerts_file, pos_file, webhook, log)
        except Exception as e:
            log.error("loop error: %s", e)
        time.sleep(interval)


def main() -> int:
    load_dotenv()
    log = setup_log()
    ap = argparse.ArgumentParser(description="Slack forwarder for dust-drain alerts")
    ap.add_argument("--once", action="store_true", help="Process unread alerts and exit")
    ap.add_argument("--follow", action="store_true", help="Tail alerts forever (default if not --once)")
    ap.add_argument("--alerts", default=str(DEFAULT_ALERTS))
    ap.add_argument("--pos-file", default=str(DEFAULT_POS))
    ap.add_argument("--interval", type=float, default=5.0)
    args = ap.parse_args()

    webhook = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
    alerts = Path(args.alerts)
    pos = Path(args.pos_file)

    if args.once:
        n = process_new(alerts, pos, webhook, log)
        log.info("once done sent=%s", n)
        return 0

    follow(alerts, pos, webhook, log, args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
