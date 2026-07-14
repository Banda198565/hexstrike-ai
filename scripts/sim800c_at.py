#!/usr/bin/env python3
"""sim800c_at.py — SIM800C AT-command tool + SMS alert channel.

Usage:
  # basic diagnostics (no SIM required)
  python3 scripts/sim800c_at.py probe --port /dev/tty.usbserial-A50285BI

  # network + signal + SIM state
  python3 scripts/sim800c_at.py status --port /dev/ttyUSB0

  # send SMS (SIM + PIN required)
  python3 scripts/sim800c_at.py sms --port /dev/ttyUSB0 --to +7... --text "hot wallet alert"

  # interactive AT shell
  python3 scripts/sim800c_at.py shell --port /dev/ttyUSB0

  # dry-run (no serial hardware) — validates command flow
  python3 scripts/sim800c_at.py probe --dry-run

Env overrides:
  SIM800C_PORT=/dev/ttyUSB0
  SIM800C_BAUD=115200
  SIM800C_PIN=1234
  SIM800C_TO=+7...
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


DEFAULT_BAUD = 115200
COMMON_PORTS = [
    "/dev/tty.usbserial-A50285BI",
    "/dev/tty.usbserial-0001",
    "/dev/tty.SLAB_USBtoUART",
    "/dev/tty.wchusbserial14210",
    "/dev/ttyUSB0",
    "/dev/ttyUSB1",
    "/dev/ttyAMA0",
    "/dev/serial0",
]


def _load_serial():
    try:
        import serial  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("pip install pyserial") from exc
    return serial


def _list_ports() -> list[str]:
    ports: list[str] = []
    try:
        from serial.tools import list_ports  # type: ignore[import-not-found]
        ports = [p.device for p in list_ports.comports()]
    except Exception:
        pass
    for p in COMMON_PORTS:
        if Path(p).exists() and p not in ports:
            ports.append(p)
    return ports


class SIM800C:
    def __init__(self, port: str, baud: int = DEFAULT_BAUD, timeout: float = 2.0, dry_run: bool = False) -> None:
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.dry_run = dry_run
        self.ser = None
        self._transcript: list[dict[str, Any]] = []

    def open(self) -> None:
        if self.dry_run:
            return
        serial = _load_serial()
        self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
        # Flush any boot noise
        time.sleep(0.2)
        try:
            self.ser.reset_input_buffer()
        except Exception:
            pass

    def close(self) -> None:
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass

    def send(self, cmd: str, wait: float = 0.6, expect: str | None = "OK") -> dict[str, Any]:
        entry: dict[str, Any] = {"cmd": cmd, "response": "", "ok": False, "expect": expect}
        if self.dry_run:
            entry["response"] = f"[dry-run] {cmd} -> OK"
            entry["ok"] = True
            self._transcript.append(entry)
            return entry
        assert self.ser is not None
        self.ser.write((cmd + "\r\n").encode("ascii", errors="ignore"))
        self.ser.flush()
        time.sleep(wait)
        raw = b""
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            chunk = self.ser.read(4096)
            if not chunk:
                if b"OK" in raw or b"ERROR" in raw or b">" in raw:
                    break
                time.sleep(0.05)
                continue
            raw += chunk
            if b"OK\r\n" in raw or b"ERROR" in raw or raw.endswith(b"> "):
                break
        text = raw.decode("utf-8", errors="replace").strip()
        entry["response"] = text
        if expect is None:
            entry["ok"] = True
        else:
            entry["ok"] = expect in text
        self._transcript.append(entry)
        return entry

    def send_raw(self, data: bytes, wait: float = 0.4) -> str:
        if self.dry_run:
            return "[dry-run] raw bytes sent"
        assert self.ser is not None
        self.ser.write(data)
        self.ser.flush()
        time.sleep(wait)
        return self.ser.read(4096).decode("utf-8", errors="replace")

    def transcript(self) -> list[dict[str, Any]]:
        return list(self._transcript)


def cmd_probe(args: argparse.Namespace) -> int:
    sim = SIM800C(args.port, args.baud, args.timeout, dry_run=args.dry_run)
    sim.open()
    try:
        sim.send("AT")                    # echo test
        sim.send("ATE0")                  # disable echo
        sim.send("ATI")                   # module identity
        sim.send("AT+CGMR")               # firmware
        sim.send("AT+GSN")                # IMEI
    finally:
        sim.close()
    out = {"command": "sim800c_probe", "port": args.port, "dry_run": args.dry_run, "transcript": sim.transcript()}
    print(json.dumps(out, indent=2))
    return 0 if all(e["ok"] for e in sim.transcript()) else 1


def cmd_status(args: argparse.Namespace) -> int:
    sim = SIM800C(args.port, args.baud, args.timeout, dry_run=args.dry_run)
    sim.open()
    try:
        sim.send("AT")
        sim.send("ATE0")
        pin = sim.send("AT+CPIN?")        # SIM PIN state
        if "SIM PIN" in pin["response"] and args.pin:
            sim.send(f'AT+CPIN="{args.pin}"', wait=1.5)
        sim.send("AT+CSQ")                # signal quality (0-31, 99=unknown)
        sim.send("AT+CREG?")              # network registration
        sim.send("AT+COPS?")              # operator
        sim.send("AT+CBC")                # battery charge
        sim.send("AT+CCLK?")              # clock
    finally:
        sim.close()
    tr = sim.transcript()
    parsed: dict[str, Any] = {}
    for e in tr:
        if e["cmd"] == "AT+CSQ":
            for line in e["response"].splitlines():
                if line.startswith("+CSQ:"):
                    parts = line.split(":", 1)[1].strip().split(",")
                    try:
                        rssi = int(parts[0])
                        parsed["rssi"] = rssi
                        parsed["signal_dbm"] = -113 + 2 * rssi if 0 <= rssi <= 31 else None
                    except Exception:
                        pass
        elif e["cmd"] == "AT+CREG?":
            for line in e["response"].splitlines():
                if line.startswith("+CREG:"):
                    parts = line.split(":", 1)[1].strip().split(",")
                    if len(parts) >= 2:
                        stat_map = {"0": "not_searching", "1": "registered_home", "2": "searching", "3": "denied", "4": "unknown", "5": "registered_roaming"}
                        parsed["network_registration"] = stat_map.get(parts[1].strip(), parts[1].strip())
        elif e["cmd"] == "AT+CPIN?":
            for line in e["response"].splitlines():
                if line.startswith("+CPIN:"):
                    parsed["pin_state"] = line.split(":", 1)[1].strip()
    out = {"command": "sim800c_status", "port": args.port, "dry_run": args.dry_run, "parsed": parsed, "transcript": tr}
    print(json.dumps(out, indent=2))
    return 0


def cmd_sms(args: argparse.Namespace) -> int:
    to = args.to or os.environ.get("SIM800C_TO")
    if not to:
        raise SystemExit("--to or SIM800C_TO required")
    text = args.text
    if not text:
        raise SystemExit("--text required")
    if len(text) > 160:
        print(f"[warn] text {len(text)} > 160 chars — may split", file=sys.stderr)

    sim = SIM800C(args.port, args.baud, args.timeout, dry_run=args.dry_run)
    sim.open()
    result = {"command": "sim800c_sms", "port": args.port, "to": to, "dry_run": args.dry_run, "sent": False}
    try:
        sim.send("AT")
        sim.send("ATE0")
        # PIN
        pin_state = sim.send("AT+CPIN?")
        if "SIM PIN" in pin_state["response"] and (args.pin or os.environ.get("SIM800C_PIN")):
            sim.send(f'AT+CPIN="{args.pin or os.environ["SIM800C_PIN"]}"', wait=1.5)
        # SMS text mode
        sim.send("AT+CMGF=1")
        sim.send('AT+CSCS="GSM"')
        # Send
        if args.dry_run:
            sim.send(f'AT+CMGS="{to}"', expect=">")
            sim.send(text, expect="+CMGS:")
            result["sent"] = True
        else:
            assert sim.ser is not None
            sim.ser.write(f'AT+CMGS="{to}"\r'.encode())
            time.sleep(0.6)
            # wait for '>'
            resp = sim.ser.read(4096).decode("utf-8", errors="replace")
            if ">" not in resp:
                result["error"] = f"no prompt: {resp}"
                print(json.dumps(result, indent=2))
                return 2
            sim.ser.write(text.encode("utf-8", errors="ignore") + b"\x1a")
            sim.ser.flush()
            time.sleep(3.0)
            resp = sim.ser.read(8192).decode("utf-8", errors="replace")
            result["response"] = resp.strip()
            result["sent"] = "+CMGS:" in resp and "OK" in resp
    finally:
        sim.close()
    print(json.dumps(result, indent=2))
    return 0 if result["sent"] else 1


def cmd_shell(args: argparse.Namespace) -> int:
    sim = SIM800C(args.port, args.baud, args.timeout, dry_run=args.dry_run)
    sim.open()
    print(f"[shell] port={args.port} baud={args.baud} — type 'quit' to exit; empty line sends AT")
    try:
        while True:
            try:
                line = input("AT> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if line in ("quit", "exit"):
                break
            entry = sim.send(line or "AT", expect=None)
            print(entry["response"] or "(no response)")
    finally:
        sim.close()
    return 0


def cmd_list_ports(_: argparse.Namespace) -> int:
    ports = _list_ports()
    print(json.dumps({"command": "sim800c_list_ports", "ports": ports}, indent=2))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="SIM800C AT-command tool")
    p.add_argument("--port", default=os.environ.get("SIM800C_PORT"))
    p.add_argument("--baud", type=int, default=int(os.environ.get("SIM800C_BAUD", DEFAULT_BAUD)))
    p.add_argument("--timeout", type=float, default=2.0)
    p.add_argument("--dry-run", action="store_true", help="No hardware; simulate AT exchange")
    p.add_argument("--pin", help="SIM PIN (or SIM800C_PIN env)")

    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ports", help="List candidate serial ports").set_defaults(func=cmd_list_ports)
    sub.add_parser("probe", help="AT + ATI + IMEI").set_defaults(func=cmd_probe)
    sub.add_parser("status", help="Signal + network + PIN state").set_defaults(func=cmd_status)

    sms_p = sub.add_parser("sms", help="Send SMS")
    sms_p.add_argument("--to", help="Destination phone number (+countrycode)")
    sms_p.add_argument("--text", required=True, help="SMS body")
    sms_p.set_defaults(func=cmd_sms)

    sub.add_parser("shell", help="Interactive AT shell").set_defaults(func=cmd_shell)

    args = p.parse_args()
    if args.cmd != "ports" and not args.port and not args.dry_run:
        ports = _list_ports()
        if not ports:
            raise SystemExit("no --port and no candidate serial ports found (try scripts/sim800c_at.py ports)")
        args.port = ports[0]
        print(f"[info] auto-selected port {args.port}", file=sys.stderr)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
