#!/usr/bin/env python3
"""Anvil e2e artifact invariants for MEV offensive stack (attacks 08–11)."""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SANDBOX_ART = ROOT / "artifacts" / "sandbox"
ADDR_RE = re.compile(r"^0x[0-9a-fA-F]{40}$")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


@dataclass
class Report:
    ts: str
    mode: str
    passed: bool
    checks: list[Check] = field(default_factory=list)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name=name, ok=ok, detail=detail))

    def finalize(self) -> None:
        self.passed = all(c.ok for c in self.checks)


def _load(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _is_addr(v: Any) -> bool:
    return isinstance(v, str) and bool(ADDR_RE.match(v))


def assert_full_stack(report: Report) -> None:
    scan = _load(SANDBOX_ART / "mev-mempool-scan.json")
    sandwich = _load(SANDBOX_ART / "mev-sandwich-result.json")
    jit = _load(SANDBOX_ART / "mev-jit-result.json")
    backrun = _load(SANDBOX_ART / "mev-backrun-result.json")

    report.add("artifact_mempool_scan", scan is not None, "mev-mempool-scan.json")
    report.add("artifact_sandwich", sandwich is not None, "mev-sandwich-result.json")
    report.add("artifact_jit", jit is not None, "mev-jit-result.json")
    report.add("artifact_backrun", backrun is not None, "mev-backrun-result.json")

    if scan:
        report.add("scan_has_rpc", bool(scan.get("rpc")), str(scan.get("rpc", "")))
        report.add("scan_candidates_list", isinstance(scan.get("candidates"), list))

    if sandwich:
        report.add("sandwich_deployed_amm", _is_addr(sandwich.get("amm")), str(sandwich.get("amm")))
        profit = int(sandwich.get("profit_wei", 0))
        report.add("sandwich_profit_positive", profit > 0, f"profit_wei={profit}")
        report.add("sandwich_success", bool(sandwich.get("success")), f"success={sandwich.get('success')}")

    if jit:
        report.add("jit_deployed_pool", _is_addr(jit.get("pool")), str(jit.get("pool")))
        skipped = bool(jit.get("skipped"))
        if skipped:
            report.add("jit_skip_has_reason", bool(jit.get("skip_reason")), str(jit.get("skip_reason")))
        else:
            net = int(jit.get("net_after_gas_wei", 0))
            report.add("jit_net_after_gas_positive", net > 0, f"net_after_gas_wei={net}")
            report.add("jit_success", bool(jit.get("success")), f"success={jit.get('success')}")
            clf = jit.get("classifier") or {}
            report.add("jit_classifier_executed", clf.get("should_execute") is True)

    if backrun:
        report.add("backrun_pool_a", _is_addr(backrun.get("pool_a")), str(backrun.get("pool_a")))
        report.add("backrun_pool_b", _is_addr(backrun.get("pool_b")), str(backrun.get("pool_b")))
        report.add("backrun_router", _is_addr(backrun.get("router")), str(backrun.get("router")))
        skipped = bool(backrun.get("skipped"))
        if skipped:
            report.add("backrun_skip_has_reason", bool(backrun.get("skip_reason")), str(backrun.get("skip_reason")))
        else:
            profit = int(backrun.get("profit_wei", 0))
            report.add("backrun_profit_positive", profit > 0, f"profit_wei={profit}")
            report.add("backrun_success", bool(backrun.get("success")), f"success={backrun.get('success')}")


def assert_jit_skip_gate(report: Report) -> None:
    jit = _load(SANDBOX_ART / "mev-jit-skip-gate.json")
    report.add("artifact_jit_skip_gate", jit is not None, "mev-jit-skip-gate.json")
    if not jit:
        return
    report.add("jit_gate_skipped", bool(jit.get("skipped")), f"skipped={jit.get('skipped')}")
    report.add("jit_gate_no_tx_success", jit.get("success") is False)
    clf = jit.get("classifier") or {}
    report.add("jit_gate_classifier_blocked", clf.get("should_execute") is False, str(clf.get("skip_reason")))


def assert_redteam(report: Report) -> None:
    data = _load(SANDBOX_ART / "redteam-report.json")
    report.add("artifact_redteam_report", data is not None, "redteam-report.json")
    if not data:
        return

    runs = {r.get("scenario"): r for r in data.get("runs", []) if isinstance(r, dict)}
    expected = {
        "08-mev-sandwich-sim": "VULN_CONFIRMED",
        "09-mev-frontrun-gas-race": "VULN_CONFIRMED",
        "10-mev-jit-liquidity": "VULN_CONFIRMED",
        "11-mev-backrun-arb": "VULN_CONFIRMED",
    }
    for scenario, want in expected.items():
        row = runs.get(scenario)
        if not row:
            report.add(f"redteam_{scenario}", False, "missing")
            continue
        got = row.get("outcome", "")
        report.add(f"redteam_{scenario}", got == want, f"outcome={got} want={want}")


def write_report(report: Report, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ts": report.ts,
        "mode": report.mode,
        "passed": report.passed,
        "checks": [asdict(c) for c in report.checks],
    }
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="MEV Anvil e2e artifact assertions")
    parser.add_argument(
        "--mode",
        choices=("full-stack", "jit-skip-gate", "redteam", "all"),
        default="all",
    )
    parser.add_argument(
        "--report",
        default=str(SANDBOX_ART / "mev-stress-report.json"),
        help="Unified stress report output path",
    )
    args = parser.parse_args()

    report = Report(
        ts=datetime.now(timezone.utc).isoformat(),
        mode=args.mode,
        passed=False,
    )

    if args.mode in ("full-stack", "all"):
        assert_full_stack(report)
    if args.mode in ("jit-skip-gate", "all"):
        assert_jit_skip_gate(report)
    if args.mode in ("redteam", "all"):
        assert_redteam(report)

    report.finalize()
    write_report(report, Path(args.report))

    for c in report.checks:
        status = "OK" if c.ok else "FAIL"
        suffix = f" — {c.detail}" if c.detail else ""
        print(f"[{status}] {c.name}{suffix}")

    print(f"\n[{'PASS' if report.passed else 'FAIL'}] mev e2e assert mode={args.mode}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
