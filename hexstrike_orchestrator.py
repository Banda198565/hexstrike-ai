#!/usr/bin/env python3
"""HexStrike-AI orchestrator — central dispatcher for modules, skills, and MCPs."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from hexstrike.agent_manager import AgentManager
from hexstrike.bus.context_bus import ContextBus
from hexstrike.core.execution.broadcaster import ExecutionBroadcaster, SnipingProfile
from hexstrike.core.forensics.engine import ForensicsEngine
from hexstrike.core.monitor.mempool import MempoolMonitor, MonitorConfig
from hexstrike.core.stealth.transport import StealthConfig, StealthTransport
from hexstrike.core.vault.keystore import KeyVault
from hexstrike.mcp.execution_gate import ExecutionGateMcp
from hexstrike.mcp.github_bridge import GithubBridgeMcp
from hexstrike.mcp.rag_memory import RagMemoryMcp
from hexstrike.mcp.rpc_gateway import RpcGatewayMcp
from hexstrike.paths import MANIFEST_PATH, PENDING_ACTION, RPC_CONFIG
from hexstrike.skills.bytecode_deobfuscator import BytecodeDeobfuscatorSkill
from hexstrike.skills.chain_tracer import ChainTracerSkill
from hexstrike.skills.dedup_engine import DedupEngine
from hexstrike.skills.recon_osint import ReconOsintSkill
from hexstrike.skills.timing_analysis import TimingAnalysisSkill
from hexstrike.instructions import load_instruction
from hexstrike.paths import (
    ALERTS_LOG as HS_ALERTS,
    PENDING_ACTION as HS_PENDING,
    RPC_CONFIG as HS_RPC_CONFIG,
)
from hexstrike.skills.vulnerability_scanner import VulnerabilityScanner

# Monitor agent system prompt (instruction protocol)
MONITOR_AGENT_ID = "core.monitor"
MONITOR_SYSTEM_PROMPT = load_instruction(MONITOR_AGENT_ID)


class HexStrikeOrchestrator:
    """Central dispatcher: recon → forensics → execution with ContextBus."""

    def __init__(self, config_path: Path = RPC_CONFIG) -> None:
        self.bus = ContextBus()
        self.config_path = config_path

        self.stealth = StealthTransport(StealthConfig())
        self.monitor = MempoolMonitor(
            bus=self.bus,
            config=MonitorConfig(config_path=config_path, stealth_enabled=True),
        )
        self.forensics = ForensicsEngine(bus=self.bus)
        self.broadcaster = ExecutionBroadcaster(bus=self.bus, config_path=config_path, sniping=SnipingProfile())
        self.vault = KeyVault(bus=self.bus, prefer_ramdisk=True)

        self.rpc_mcp = RpcGatewayMcp(bus=self.bus, monitor=self.monitor)
        self.rag_mcp = RagMemoryMcp(bus=self.bus)
        self.execution_mcp = ExecutionGateMcp(bus=self.bus, broadcaster=self.broadcaster)
        self.github_mcp = GithubBridgeMcp(bus=self.bus)

        self.recon = ReconOsintSkill(bus=self.bus)
        self.chain_tracer = ChainTracerSkill(bus=self.bus, forensics=self.forensics)
        self.dedup = DedupEngine(bus=self.bus)
        self.timing = TimingAnalysisSkill(bus=self.bus, config_path=config_path)
        self.bytecode = BytecodeDeobfuscatorSkill(bus=self.bus, config_path=config_path)
        self.vuln_scanner = VulnerabilityScanner(bus=self.bus)

        self.agent_manager = AgentManager(
            bus=self.bus,
            mcp_registry={
                "mcp_rpc_gateway": self.rpc_mcp,
                "mcp_rag_memory": self.rag_mcp,
                "mcp_execution_gate": self.execution_mcp,
                "mcp_github_bridge": self.github_mcp,
            },
            module_registry={
                "core.monitor": self.monitor,
                "core.forensics": self.forensics,
                "core.execution": self.broadcaster,
                "skill.recon_osint": self.recon,
                "skill.timing_analysis": self.timing,
            },
        )
        self.agent_manager.initialize_all()

        self._wire_bus_logging()

    def _wire_bus_logging(self) -> None:
        def _log(event) -> None:
            if event.topic.startswith(("monitor.", "execution.", "mcp.execution.", "skill.")):
                print(f"[bus] {event.topic} ← {event.source}")

        self.bus.subscribe("*", _log)

    def health(self) -> dict[str, Any]:
        timing_best = self.timing.recommend_endpoint()
        return {
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "rpc": self.rpc_mcp.health(),
            "stealth": self.stealth.status(),
            "vault": self.vault.status(),
            "execution_gate": self.execution_mcp.status(),
            "dedup": self.dedup.snapshot(),
            "timing_best_rpc": timing_best.get("endpoint") if isinstance(timing_best, dict) else None,
            "forensics_entries": len((self.forensics.load_context() or {}).get("entries", [])),
        }

    def update_manifest(self) -> dict[str, Any]:
        manifest_path = MANIFEST_PATH
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        health = self.health()

        runtime = {
            "last_health_check": health["timestamp"],
            "rpc_status": health["rpc"].get("status"),
            "active_rpc": health["rpc"].get("active_rpc"),
            "stealth_enabled": health["stealth"].get("enabled"),
            "vault_backend": health["vault"].get("storage_backend"),
            "pending_action": health["execution_gate"].get("has_pending"),
            "dedup_pairs": health["dedup"].get("active_pairs"),
            "timing_best_rpc": health.get("timing_best_rpc"),
        }
        manifest["updated_at"] = health["timestamp"]
        manifest["runtime"] = runtime

        for layer in ("modules", "skills", "mcps"):
            for name, meta in manifest["layers"][layer].items():
                if meta.get("status") == "external":
                    continue
                meta["last_checked"] = health["timestamp"]

        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        self.bus.publish("orchestrator.manifest_updated", runtime, source="orchestrator")
        return manifest

    def run_health_suite(self) -> dict[str, Any]:
        script = ROOT / "scripts" / "health_check.sh"
        if script.is_file():
            proc = subprocess.run([str(script)], cwd=str(ROOT), capture_output=True, text=True)
            return {"returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
        return self.health()

    def run_recon(self, limit: int = 3) -> list[dict[str, Any]]:
        return self.recon.scan_rpc_nodes(limit=limit)

    def run_timing(self) -> dict[str, Any]:
        return self.timing.recommend_endpoint()

    def run_bytecode(self, address: str) -> dict[str, Any]:
        return self.forensics.analyze_contract(address)

    def run_vuln_scan(self) -> dict[str, Any]:
        return self.vuln_scanner.run_full_scan()

    def run_analyze(self, address: str) -> dict[str, Any]:
        """Instruction-driven forensics analysis (hot-wallet protocol)."""
        prompt = self.agent_manager.get_system_prompt("core.forensics")
        entity = self.forensics.resolve_entity(address)
        contract = self.forensics.analyze_contract(address)
        trace = self.chain_tracer.trace(address, depth=2)
        rag_hits = self.rag_mcp.search(f"address {address} rhino bridge hot wallet usdt")
        return {
            "address": address.lower(),
            "instruction_loaded": "forensics.md",
            "instruction_bytes": len(prompt),
            "entity": entity,
            "contract": contract,
            "trace": trace,
            "rag_hits": rag_hits[:3],
        }

    def run_monitor_loop(
        self,
        *,
        duration_seconds: int | None = None,
        delegate_legacy: bool = True,
    ) -> dict[str, Any]:
        if delegate_legacy:
            legacy = ROOT / "scripts" / "autonomous_monitor.py"
            if legacy.is_file():
                cmd = [sys.executable, str(legacy), "--config", str(self.config_path)]
                if duration_seconds:
                    cmd.extend(["--duration", str(duration_seconds)])
                proc = subprocess.run(cmd, cwd=str(ROOT))
                return {"mode": "legacy_monitor", "returncode": proc.returncode}

        alerts = 0
        dedup_skipped = 0
        txs = 0

        for tx in self.monitor.stream(duration_seconds=duration_seconds):
            txs += 1
            frm, to = tx.get("from", ""), tx.get("to", "")
            fp, _ = self.rag_mcp.is_false_positive(tx.get("hash", ""), frm, to)
            if fp:
                continue

            alert = {"hash": tx.get("hash"), "from": frm, "to": to, "severity": "WARN"}
            if self.dedup.filter_alert(alert) is None:
                dedup_skipped += 1
                continue

            entity = self.forensics.resolve_entity(to)
            if entity.get("labels"):
                alert["severity"] = "CRITICAL"

            self.execution_mcp.submit(
                {"hash": tx.get("hash"), "from": frm, "to": to, "value": tx.get("value")},
                reason="mempool_watch_hit",
                severity=alert["severity"],
            )
            alerts += 1

        return {"mode": "orchestrator", "txs": txs, "alerts": alerts, "dedup_skipped": dedup_skipped}

    def status(self) -> dict[str, Any]:
        return {
            "version": "8.0.0",
            "components": {
                "core.monitor": "active",
                "core.stealth": self.stealth.status(),
                "core.forensics": "active",
                "core.execution": "active",
                "core.vault": self.vault.status(),
            },
            "skills": [
                "skill.recon_osint",
                "skill.chain_tracer",
                "skill.timing_analysis",
                "skill.vulnerability_scanner",
                "skill.dedup_engine",
                "skill.bytecode_deobfuscator",
            ],
            "mcps": [
                "mcp_rpc_gateway",
                "mcp_rag_memory",
                "mcp_execution_gate",
                "mcp_github_bridge",
            ],
            "agents": self.agent_manager.status(),
            "pending_action": str(PENDING_ACTION),
            "manifest": str(MANIFEST_PATH),
        }


def main() -> int:
    parser = argparse.ArgumentParser(description="HexStrike-AI orchestrator")
    parser.add_argument("--config", default=str(RPC_CONFIG))
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="Show component status")
    sub.add_parser("health", help="Run health checks and update manifest")
    sub.add_parser("manifest", help="Update project_manifest.json runtime section")

    sub.add_parser("agents", help="Show bound agents and instruction files")

    analyze_p = sub.add_parser("analyze", help="Forensics analysis on address (instruction-driven)")
    analyze_p.add_argument("address", help="Target address (0x...)")

    recon_p = sub.add_parser("recon", help="Passive RPC recon scan")
    recon_p.add_argument("--limit", type=int, default=3)

    sub.add_parser("timing", help="RPC latency profile for gas-war positioning")
    sub.add_parser("vuln-scan", help="Run vulnerability scanner")

    bc_p = sub.add_parser("bytecode", help="Analyze contract bytecode")
    bc_p.add_argument("address", help="Contract address (0x...)")

    mon_p = sub.add_parser("monitor", help="Run mempool monitor loop")
    mon_p.add_argument("--duration", type=int, default=None)
    mon_p.add_argument("--native", action="store_true", help="Use orchestrator native loop")

    stress_p = sub.add_parser("stress-test", help="Run HexStrike Stress Test (KPI evaluation)")
    stress_p.add_argument("--target", default="0xcfc85f21f5f01ab24d6b7a3b93ef097099ebde3a")
    stress_p.add_argument("--ip", default="51.250.97.223")
    stress_p.add_argument("--monitor-duration", type=int, default=45)

    args = parser.parse_args()
    orch = HexStrikeOrchestrator(config_path=Path(args.config))

    if args.command == "status":
        print(json.dumps(orch.status(), indent=2))
        return 0
    if args.command == "health":
        result = orch.run_health_suite()
        orch.update_manifest()
        if isinstance(result, dict) and "stdout" in result:
            print(result.get("stdout", ""))
        else:
            print(json.dumps(result, indent=2))
        return 0
    if args.command == "manifest":
        print(json.dumps(orch.update_manifest(), indent=2))
        return 0
    if args.command == "agents":
        print(json.dumps(orch.agent_manager.status(), indent=2))
        return 0
    if args.command == "analyze":
        print(json.dumps(orch.run_analyze(args.address), indent=2))
        return 0
    if args.command == "recon":
        print(json.dumps(orch.run_recon(limit=args.limit), indent=2))
        return 0
    if args.command == "timing":
        print(json.dumps(orch.run_timing(), indent=2))
        return 0
    if args.command == "bytecode":
        print(json.dumps(orch.run_bytecode(args.address), indent=2))
        return 0
    if args.command == "vuln-scan":
        print(json.dumps(orch.run_vuln_scan(), indent=2))
        return 0
    if args.command == "monitor":
        result = orch.run_monitor_loop(
            duration_seconds=args.duration,
            delegate_legacy=not args.native,
        )
        orch.update_manifest()
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "stress-test":
        cmd = [
            sys.executable,
            str(ROOT / "scripts" / "stress_test.py"),
            "--target", args.target,
            "--ip", args.ip,
            "--monitor-duration", str(args.monitor_duration),
        ]
        return subprocess.call(cmd, cwd=str(ROOT))

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
