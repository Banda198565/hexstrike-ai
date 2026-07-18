#!/usr/bin/env python3
"""Defensive detector: EIP-7702 style dust → ERC-20 drain within N seconds.

Read-only. Polls Ethereum blocks (HTTP JSON-RPC), correlates micro-ETH inbound
with subsequent USDT/USDC transfer from the same EOA, alerts on ≤WINDOW_SEC.

Usage:
  export ETH_RPC_URL=https://eth.llamarpc.com   # or Infura/Alchemy HTTPS
  # optional: ETH_RPC_WS=wss://... (reserved; HTTP poll is the default path)
  python3 scripts/detect_eip7702_dust_drain.py
  python3 scripts/detect_eip7702_dust_drain.py --once --from-block latest-5

Env:
  ETH_RPC_URL / ETH_HTTP_URL  — required for live mode
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID — optional alerts
  DUST_THRESHOLD_ETH (default 0.00001)
  WINDOW_SEC (default 30)
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
from collections import OrderedDict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# ========== КОНФИГУРАЦИЯ (при необходимости замените / дополните) ==========
# RPC: задайте через env ETH_RPC_URL (HTTPS предпочтительно) или --rpc
# Telegram: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID (опционально)
DEFAULT_OPERATORS = {
    "0x48de55b9ef74377008b739070d7f32554fbb38ff",  # EIP7702 dust operator
    # "0xВАШ_ОПЕРАТОР".lower(),
}
DEFAULT_SINKS = {
    "0x38380e4dc55d71be798935707b452cf936822f3b",  # validated USDT sink
    # "0xВАШ_SINK".lower(),
}
USDT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
USDC = "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"
TRANSFER_SEL = "0xa9059cbb"
# Также подхватывает IOC из artifacts/forensics/* автоматически.
# ========================================================================


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


def setup_log(log_file: Path) -> logging.Logger:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("dust_drain_detector")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    fh = logging.FileHandler(log_file)
    fh.setFormatter(fmt)
    logger.addHandler(sh)
    logger.addHandler(fh)
    return logger


def rpc(url: str, method: str, params: list[Any], timeout: int = 30) -> Any:
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json", "User-Agent": "hexstrike-dust-drain-detector/1.0"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode())
    if "error" in body:
        raise RuntimeError(body["error"])
    return body.get("result")


def norm(addr: str | None) -> str:
    if not addr:
        return ""
    return addr.lower()


def wei_to_eth(wei_hex: str | int | None) -> float:
    if wei_hex is None:
        return 0.0
    if isinstance(wei_hex, str):
        wei = int(wei_hex, 16)
    else:
        wei = int(wei_hex)
    return wei / 1e18


@dataclass
class DustEvent:
    victim: str
    ts: int
    tx_hash: str
    value_eth: float
    block: int
    operator: str


@dataclass
class Alert:
    generated_at: str
    victim: str
    operator: str
    sink: str
    token: str
    amount_raw: int
    amount_human: float
    decimals: int
    delta_sec: int
    block_dust: int
    block_drain: int
    tx_dust: str
    tx_drain: str
    pattern: str = "dust_to_drain_le_30s"


class DustCache:
    """victim -> DustEvent, capped + TTL cleanup."""

    def __init__(self, window_sec: int, max_size: int = 5000) -> None:
        self.window = window_sec
        self.max_size = max_size
        self._data: OrderedDict[str, DustEvent] = OrderedDict()

    def put(self, ev: DustEvent) -> None:
        self._data[ev.victim] = ev
        self._data.move_to_end(ev.victim)
        while len(self._data) > self.max_size:
            self._data.popitem(last=False)

    def pop_if_fresh(self, victim: str, now_ts: int) -> DustEvent | None:
        ev = self._data.get(victim)
        if not ev:
            return None
        if 0 <= now_ts - ev.ts <= self.window:
            del self._data[victim]
            return ev
        if now_ts - ev.ts > self.window:
            del self._data[victim]
        return None


def parse_erc20_transfer(input_hex: str) -> tuple[str, int] | None:
    """Return (to, amount) for transfer(address,uint256)."""
    data = (input_hex or "").lower()
    if not data.startswith(TRANSFER_SEL):
        return None
    raw = data[10:]
    if len(raw) < 128:
        return None
    to = "0x" + raw[24:64]
    amount = int(raw[64:128], 16)
    return to, amount


def telegram_alert(text: str, log: logging.Logger) -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("ALERT_TELEGRAM_BOT_TOKEN") or ""
    chat = os.environ.get("TELEGRAM_CHAT_ID") or os.environ.get("ALERT_TELEGRAM_CHAT_ID") or ""
    if not token or not chat:
        return
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": chat, "text": text[:3500]}).encode()
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=8).read()
    except Exception as e:
        log.error("telegram alert failed: %s", e)


def load_operators_sinks() -> tuple[set[str], set[str]]:
    ops = set(DEFAULT_OPERATORS)
    sinks = set(DEFAULT_SINKS)
    for rel in (
        "artifacts/forensics/eip7702-dusting-iocs-2026-07-18.json",
        "artifacts/forensics/eip7702-dust-drain-mechanics-validated-2026-07-18.json",
        "artifacts/forensics/watchlist-bridge-2026-07-18.json",
    ):
        p = ROOT / rel
        if not p.is_file():
            continue
        try:
            d = json.loads(p.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        for ioc in d.get("iocs") or []:
            if not isinstance(ioc, dict):
                continue
            addr = norm(ioc.get("address"))
            role = (ioc.get("role") or "").lower()
            if not addr:
                continue
            if "operator" in role or "dust" in role or "delegat" in role:
                ops.add(addr)
            if "sink" in role:
                sinks.add(addr)
        addrs = d.get("addresses") or {}
        if isinstance(addrs, dict):
            if addrs.get("operator"):
                ops.add(norm(addrs["operator"]))
            if addrs.get("sink"):
                sinks.add(norm(addrs["sink"]))
        for w in d.get("priority_watch") or []:
            if isinstance(w, dict) and w.get("address"):
                role = (w.get("role") or "").lower()
                if "dust" in role or "operator" in role:
                    ops.add(norm(w["address"]))
    return ops, sinks


class Detector:
    def __init__(
        self,
        rpc_url: str,
        window_sec: int,
        dust_threshold_eth: float,
        log: logging.Logger,
        alerts_path: Path,
        state_path: Path,
    ) -> None:
        self.rpc_url = rpc_url
        self.window = window_sec
        self.dust_eth = dust_threshold_eth
        self.log = log
        self.alerts_path = alerts_path
        self.state_path = state_path
        self.cache = DustCache(window_sec)
        self.operators, self.sinks = load_operators_sinks()
        self.seen_alerts: set[str] = set()
        self._load_state()
        self.alerts_path.parent.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> None:
        if self.state_path.is_file():
            try:
                d = json.loads(self.state_path.read_text())
                self.seen_alerts = set(d.get("seen_alerts") or [])
                self.log.info("state loaded seen_alerts=%d", len(self.seen_alerts))
            except (OSError, json.JSONDecodeError):
                pass

    def _save_state(self, last_block: int) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(
            json.dumps(
                {
                    "last_block": last_block,
                    "seen_alerts": sorted(self.seen_alerts)[-2000:],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
                indent=2,
            )
            + "\n"
        )

    def emit(self, alert: Alert) -> None:
        key = f"{alert.tx_dust}:{alert.tx_drain}"
        if key in self.seen_alerts:
            return
        self.seen_alerts.add(key)
        line = json.dumps(asdict(alert), ensure_ascii=False)
        with self.alerts_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        msg = (
            f"DUST→DRAIN ≤{self.window}s\n"
            f"victim={alert.victim}\n"
            f"operator={alert.operator}\n"
            f"sink={alert.sink}\n"
            f"token={alert.token} amount={alert.amount_human}\n"
            f"delta={alert.delta_sec}s\n"
            f"dust={alert.tx_dust}\n"
            f"drain={alert.tx_drain}"
        )
        self.log.warning(msg.replace("\n", " | "))
        telegram_alert(msg, self.log)

    def process_block(self, block: dict[str, Any]) -> int:
        hits = 0
        bnum = int(block["number"], 16)
        bts = int(block["timestamp"], 16)
        for tx in block.get("transactions") or []:
            if not isinstance(tx, dict):
                continue
            frm = norm(tx.get("from"))
            to = norm(tx.get("to"))
            txh = tx.get("hash") or ""
            value_eth = wei_to_eth(tx.get("value"))
            inp = tx.get("input") or "0x"

            # Dust: micro ETH to an EOA/address
            if to and value_eth > 0 and value_eth < self.dust_eth:
                # Prefer known operators; still track anonymous dust for pattern match
                op = frm if frm in self.operators or value_eth < self.dust_eth else frm
                self.cache.put(
                    DustEvent(victim=to, ts=bts, tx_hash=txh, value_eth=value_eth, block=bnum, operator=frm)
                )
                if frm in self.operators:
                    self.log.info("dust from known operator %s -> %s eth=%.10f tx=%s", frm, to, value_eth, txh)

            # ERC-20 transfer from victim
            if to in (USDT, USDC):
                parsed = parse_erc20_transfer(inp)
                if not parsed:
                    continue
                sink, amount = parsed
                dust = self.cache.pop_if_fresh(frm, bts)
                if not dust:
                    continue
                # Optional: require known sink OR any sink after known-operator dust
                if dust.operator not in self.operators and sink not in self.sinks and amount < 10_000_000:
                    # ignore tiny anonymous pairs (<10 token units raw) unless known IOC
                    if amount < 1_000_000:
                        continue
                decimals = 6
                human = amount / (10**decimals)
                alert = Alert(
                    generated_at=datetime.now(timezone.utc).isoformat(),
                    victim=frm,
                    operator=dust.operator,
                    sink=sink,
                    token="USDT" if to == USDT else "USDC",
                    amount_raw=amount,
                    amount_human=human,
                    decimals=decimals,
                    delta_sec=bts - dust.ts,
                    block_dust=dust.block,
                    block_drain=bnum,
                    tx_dust=dust.tx_hash,
                    tx_drain=txh,
                )
                self.emit(alert)
                hits += 1
        return hits

    def fetch_block(self, num: int) -> dict[str, Any]:
        return rpc(self.rpc_url, "eth_getBlockByNumber", [hex(num), True])

    def latest(self) -> int:
        return int(rpc(self.rpc_url, "eth_blockNumber", []), 16)

    def run_forever(self, start_block: int | None = None, poll_sec: float = 2.0) -> None:
        tip = self.latest()
        cur = start_block if start_block is not None else tip
        self.log.info(
            "detector start tip=%s cur=%s window=%ss dust<%s operators=%d sinks=%d",
            tip,
            cur,
            self.window,
            self.dust_eth,
            len(self.operators),
            len(self.sinks),
        )
        while True:
            try:
                tip = self.latest()
                while cur <= tip:
                    block = self.fetch_block(cur)
                    if block:
                        hits = self.process_block(block)
                        if hits:
                            self.log.info("block %s alerts=%s", cur, hits)
                    cur += 1
                    if cur % 20 == 0:
                        self._save_state(cur - 1)
                self._save_state(cur - 1)
                time.sleep(poll_sec)
            except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
                self.log.error("rpc loop error: %s — retry", e)
                time.sleep(5)

    def run_range(self, from_block: int, to_block: int) -> int:
        total = 0
        for b in range(from_block, to_block + 1):
            block = self.fetch_block(b)
            if block:
                total += self.process_block(block)
        self._save_state(to_block)
        return total


def resolve_block_spec(rpc_url: str, spec: str) -> int:
    tip = int(rpc(rpc_url, "eth_blockNumber", []), 16)
    if spec == "latest":
        return tip
    if spec.startswith("latest-"):
        n = int(spec.split("-", 1)[1])
        return max(0, tip - n)
    if spec.startswith("0x"):
        return int(spec, 16)
    return int(spec)


def main() -> int:
    load_dotenv()
    ap = argparse.ArgumentParser(description="Defensive dust→drain detector (EIP-7702 pattern)")
    ap.add_argument("--rpc", default=os.environ.get("ETH_RPC_URL") or os.environ.get("ETH_HTTP_URL") or "")
    ap.add_argument("--window", type=int, default=int(os.environ.get("WINDOW_SEC", "30")))
    ap.add_argument("--dust-eth", type=float, default=float(os.environ.get("DUST_THRESHOLD_ETH", "0.00001")))
    ap.add_argument("--once", action="store_true", help="Scan a block range once and exit")
    ap.add_argument("--from-block", default="latest-30")
    ap.add_argument("--to-block", default="latest")
    ap.add_argument("--log-file", default=str(ROOT / "artifacts" / "monitor" / "dust-drain-detector.log"))
    ap.add_argument("--alerts", default=str(ROOT / "artifacts" / "monitor" / "dust-drain-alerts.jsonl"))
    ap.add_argument("--state", default=str(ROOT / "artifacts" / "monitor" / "dust-drain-state.json"))
    args = ap.parse_args()

    log = setup_log(Path(args.log_file))
    if not args.rpc:
        log.error("ETH_RPC_URL / ETH_HTTP_URL not set")
        return 2

    det = Detector(
        rpc_url=args.rpc,
        window_sec=args.window,
        dust_threshold_eth=args.dust_eth,
        log=log,
        alerts_path=Path(args.alerts),
        state_path=Path(args.state),
    )

    if args.once:
        fb = resolve_block_spec(args.rpc, args.from_block)
        tb = resolve_block_spec(args.rpc, args.to_block)
        if fb > tb:
            fb, tb = tb, fb
        log.info("one-shot scan blocks %s..%s", fb, tb)
        hits = det.run_range(fb, tb)
        log.info("done hits=%s alerts_file=%s", hits, args.alerts)
        return 0

    det.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
