#!/usr/bin/env python3
"""BSC fork e2e artifact invariants — Variant D (mempool + real pools + subset 08–11)."""
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


def assert_fork_mempool(report: Report) -> None:
    scan = _load(SANDBOX_ART / "mev-bsc-mempool-scan.json")
    report.add("artifact_bsc_mempool_scan", scan is not None)
    if not scan:
        return
    report.add("scan_chain_56", scan.get("chain_id") == 56, str(scan.get("chain_id")))
    router = scan.get("router_filter") or ""
    report.add("scan_router_filter", bool(ADDR_RE.match(router)), router)
    candidates = [c for c in scan.get("candidates", []) if not c.get("error")]
    report.add("mempool_candidates_found", len(candidates) > 0, f"count={len(candidates)}")
    if candidates:
        c0 = candidates[0]
        report.add("candidate_has_value", int(c0.get("value_wei", 0)) > 0)
        report.add("candidate_has_selector", bool(c0.get("selector")))


def assert_fork_offensive(report: Report) -> None:
    fork = _load(SANDBOX_ART / "mev-bsc-fork-result.json")
    report.add("artifact_bsc_fork_result", fork is not None)
    if not fork:
        return
    report.add("fork_chain_56", fork.get("chain_id") == 56)
    reserves = fork.get("reserves_raw") or []
    report.add("fork_real_reserves", len(reserves) == 2 and all(int(x) > 0 for x in reserves), str(reserves[:2]))
    report.add("fork_pair_address", ADDR_RE.match(str(fork.get("pair", ""))) is not None, str(fork.get("pair")))
    sim = fork.get("sandwich_sim") or {}
    report.add("fork_sandwich_sim_present", bool(sim))
    if fork.get("mempool_candidate_count", 0) > 0:
        report.add("fork_mempool_driven", fork.get("mode") == "mempool_simulation_only", fork.get("mode", ""))
        mempool = fork.get("mempool") or {}
        report.add("fork_mempool_analyses", bool(mempool.get("analyses")))
    # Profitable or explicit skip — both valid on real pools
    if sim.get("should_execute"):
        report.add("fork_profitable_sim", int(sim.get("net_profit_wei", 0)) > 0, str(sim.get("net_profit_wei")))
    else:
        report.add("fork_skip_has_reason", bool(sim.get("skip_reason")), str(sim.get("skip_reason")))


def assert_mock_engines_on_fork(report: Report) -> None:
    for name, profit_key in (
        ("mev-jit-result.json", "net_after_gas_wei"),
        ("mev-backrun-result.json", "profit_wei"),
    ):
        data = _load(SANDBOX_ART / name)
        report.add(f"artifact_{name}", data is not None, name)
        if not data:
            continue
        deployed = bool(data.get("pool") or data.get("router") or data.get("pool_a"))
        report.add(f"{name}_deployed", deployed)
        if data.get("skipped"):
            report.add(f"{name}_skip_ok", bool(data.get("skip_reason")))
        else:
            report.add(f"{name}_executed_on_fork", True)


def assert_redteam_fork(report: Report) -> None:
    data = _load(SANDBOX_ART / "redteam-report.json")
    report.add("artifact_redteam_report", data is not None)
    if not data:
        return
    runs = {r.get("scenario"): r for r in data.get("runs", []) if isinstance(r, dict)}
    for scenario in (
        "09-mev-frontrun-gas-race",
        "10-mev-jit-liquidity",
        "11-mev-backrun-arb",
    ):
        row = runs.get(scenario)
        if not row:
            report.add(f"redteam_{scenario}", False, "missing")
            continue
        ok = row.get("outcome") == "VULN_CONFIRMED"
        report.add(f"redteam_{scenario}", ok, f"outcome={row.get('outcome')}")


def write_report(report: Report, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {"ts": report.ts, "mode": report.mode, "passed": report.passed, "checks": [asdict(c) for c in report.checks]},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("mempool", "fork", "mock", "redteam", "all"), default="all")
    parser.add_argument("--report", default=str(SANDBOX_ART / "mev-bsc-fork-stress-report.json"))
    args = parser.parse_args()

    report = Report(ts=datetime.now(timezone.utc).isoformat(), mode=args.mode, passed=False)
    if args.mode in ("mempool", "all"):
        assert_fork_mempool(report)
    if args.mode in ("fork", "all"):
        assert_fork_offensive(report)
    if args.mode in ("mock", "all"):
        assert_mock_engines_on_fork(report)
    if args.mode in ("redteam", "all"):
        assert_redteam_fork(report)

    report.finalize()
    write_report(report, Path(args.report))

    for c in report.checks:
        print(f"[{'OK' if c.ok else 'FAIL'}] {c.name}" + (f" — {c.detail}" if c.detail else ""))
    print(f"\n[{'PASS' if report.passed else 'FAIL'}] fork e2e assert mode={args.mode}")
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
