"""External Solidity toolchain wrappers — Slither, Mythril, Echidna, Foundry."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hexstrike.paths import ROOT

CONFIG_PATH = ROOT / "config" / "dual-mode.json"


def _load_config() -> dict[str, Any]:
    if CONFIG_PATH.is_file():
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    return {}


def _which(name: str) -> str | None:
    path = shutil.which(name)
    if path:
        return path
    foundry = Path.home() / ".foundry" / "bin" / name
    return str(foundry) if foundry.is_file() else None


@dataclass
class ToolResult:
    tool: str
    ok: bool
    findings: list[dict[str, Any]] = field(default_factory=list)
    stdout: str = ""
    stderr: str = ""
    error: str | None = None
    skipped: bool = False
    skip_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "ok": self.ok,
            "findings": self.findings,
            "stdout": self.stdout[:8000],
            "stderr": self.stderr[:4000],
            "error": self.error,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
        }


@dataclass
class ContractToolchain:
    """Detect and invoke local audit / fuzz / forge tools."""

    timeout_sec: int = 300
    config: dict[str, Any] = field(default_factory=_load_config)

    def detect_tools(self) -> dict[str, bool]:
        tools = self.config.get("tools", {})
        out: dict[str, bool] = {}
        for name, meta in tools.items():
            binary = meta.get("binary", name)
            out[name] = _which(binary) is not None
        return out

    def _run(self, tool: str, cmd: list[str], *, cwd: Path | None = None) -> ToolResult:
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd or ROOT),
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )
            ok = proc.returncode == 0
            return ToolResult(
                tool=tool,
                ok=ok,
                stdout=proc.stdout,
                stderr=proc.stderr,
                error=None if ok else f"exit {proc.returncode}",
            )
        except FileNotFoundError:
            return ToolResult(tool=tool, ok=False, skipped=True, skip_reason="binary not found")
        except subprocess.TimeoutExpired:
            return ToolResult(tool=tool, ok=False, error=f"timeout after {self.timeout_sec}s")
        except OSError as exc:
            return ToolResult(tool=tool, ok=False, error=str(exc))

    def slither_scan(self, contract_path: Path) -> ToolResult:
        binary = _which("slither")
        if not binary:
            return ToolResult("slither", ok=False, skipped=True, skip_reason="slither not installed")
        result = self._run(
            "slither",
            [binary, str(contract_path), "--json", "-"],
            cwd=contract_path.parent,
        )
        if result.ok and result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
                detectors = payload.get("results", {}).get("detectors", [])
                result.findings = [
                    {
                        "check": d.get("check"),
                        "impact": d.get("impact"),
                        "confidence": d.get("confidence"),
                        "description": d.get("description"),
                    }
                    for d in detectors
                ]
            except json.JSONDecodeError:
                result.findings = [{"raw": result.stdout[:2000]}]
        return result

    def mythril_analyze(self, contract_path: Path) -> ToolResult:
        binary = _which("myth")
        if not binary:
            return ToolResult("mythril", ok=False, skipped=True, skip_reason="mythril not installed")
        result = self._run(
            "mythril",
            [binary, "analyze", str(contract_path), "-o", "json"],
            cwd=contract_path.parent,
        )
        if result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
                issues = payload if isinstance(payload, list) else payload.get("issues", [])
                result.findings = [
                    {
                        "title": i.get("title"),
                        "severity": i.get("severity"),
                        "description": i.get("description"),
                        "swc_id": i.get("swc-id") or i.get("swc_id"),
                    }
                    for i in issues
                ]
                result.ok = True
            except json.JSONDecodeError:
                result.findings = [{"raw": result.stdout[:2000]}]
        return result

    def aderyn_scan(self, project_dir: Path) -> ToolResult:
        binary = _which("aderyn")
        if not binary:
            return ToolResult("aderyn", ok=False, skipped=True, skip_reason="aderyn not installed")
        out_md = project_dir / "aderyn-report.md"
        result = self._run(
            "aderyn",
            [binary, str(project_dir), "--output", str(out_md)],
            cwd=project_dir if project_dir.is_dir() else project_dir.parent,
        )
        if out_md.is_file():
            text = out_md.read_text(encoding="utf-8", errors="replace")
            result.stdout = text
            # Parse markdown issue headers — real output only
            findings: list[dict[str, Any]] = []
            for line in text.splitlines():
                line = line.strip()
                if line.startswith("## ") or line.startswith("### "):
                    title = line.lstrip("#").strip()
                    if title and title.lower() not in ("summary", "report"):
                        findings.append({"title": title, "source": "aderyn_markdown"})
            result.findings = findings
            result.ok = True
        return result

    def slither_raw_json(self, contract_path: Path) -> tuple[dict[str, Any] | None, ToolResult]:
        """Run slither --json and return parsed payload + ToolResult."""
        binary = _which("slither")
        if not binary:
            tr = ToolResult("slither", ok=False, skipped=True, skip_reason="slither not installed")
            return None, tr
        result = self._run(
            "slither",
            [binary, str(contract_path), "--json", "-"],
            cwd=contract_path.parent,
        )
        payload: dict[str, Any] | None = None
        if result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
                detectors = (payload.get("results") or {}).get("detectors", [])
                result.findings = [
                    {
                        "check": d.get("check"),
                        "impact": d.get("impact"),
                        "confidence": d.get("confidence"),
                        "description": d.get("description"),
                        "elements": d.get("elements") or [],
                    }
                    for d in detectors
                ]
                result.ok = bool(payload.get("success", result.ok))
            except json.JSONDecodeError:
                result.findings = [{"raw": result.stdout[:2000]}]
        return payload, result

    def echidna_fuzz(self, project_dir: Path) -> ToolResult:
        binary = _which("echidna-test")
        if not binary:
            return ToolResult("echidna", ok=False, skipped=True, skip_reason="echidna not installed")
        return self._run("echidna", [binary, "."], cwd=project_dir)

    def forge_compile_abi(
        self, project_dir: Path, *, contract_name: str | None = None
    ) -> ToolResult:
        """Compile Foundry project and extract ABI/bytecode from out/ artifacts."""
        binary = _which("forge")
        if not binary:
            return ToolResult("forge", ok=False, skipped=True, skip_reason="forge not installed")
        if not (project_dir / "foundry.toml").is_file():
            return ToolResult(
                "forge",
                ok=False,
                skipped=True,
                skip_reason="foundry.toml not found — not a Foundry project",
            )
        result = self._run("forge", [binary, "build"], cwd=project_dir)
        if not result.ok:
            return result
        out_dir = project_dir / "out"
        if not out_dir.is_dir():
            result.ok = False
            result.error = "forge build succeeded but out/ missing"
            return result
        artifacts: list[dict[str, Any]] = []
        for json_path in out_dir.rglob("*.json"):
            if json_path.name.endswith(".metadata.json"):
                continue
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict) or "abi" not in data:
                continue
            name = data.get("contractName") or json_path.stem
            if contract_name and name != contract_name:
                continue
            artifacts.append(
                {
                    "contract_name": name,
                    "abi": data.get("abi"),
                    "bytecode": (data.get("bytecode") or {}).get("object"),
                    "deployed_bytecode": (data.get("deployedBytecode") or {}).get("object"),
                    "artifact_path": str(json_path),
                }
            )
        result.findings = artifacts
        result.ok = bool(artifacts)
        if not artifacts:
            result.error = "no ABI artifacts found in out/"
        return result

    def mythril_analyze_bytecode(self, bytecode: str) -> ToolResult:
        """Run Mythril on raw bytecode hex string."""
        binary = _which("myth")
        if not binary:
            return ToolResult("mythril", ok=False, skipped=True, skip_reason="mythril not installed")
        hex_body = bytecode[2:] if bytecode.startswith("0x") else bytecode
        if not hex_body:
            return ToolResult("mythril", ok=False, error="empty bytecode")
        result = self._run("mythril", [binary, "analyze", "-c", f"0x{hex_body}", "-o", "json"])
        if result.stdout.strip():
            try:
                payload = json.loads(result.stdout)
                issues = payload if isinstance(payload, list) else payload.get("issues", [])
                result.findings = [
                    {
                        "title": i.get("title"),
                        "severity": i.get("severity"),
                        "description": i.get("description"),
                        "swc_id": i.get("swc-id") or i.get("swc_id"),
                    }
                    for i in issues
                ]
                result.ok = True
            except json.JSONDecodeError:
                result.findings = [{"raw": result.stdout[:2000]}]
        return result

    def foundry_test(self, project_dir: Path, *, match: str | None = None) -> ToolResult:
        binary = _which("forge")
        if not binary:
            return ToolResult("foundry", ok=False, skipped=True, skip_reason="forge not installed")
        cmd = [binary, "test", "-vv"]
        if match:
            cmd.extend(["--match-path", match])
        return self._run("foundry", cmd, cwd=project_dir)

    def foundry_exploit_poc(self, project_dir: Path, test_path: str) -> ToolResult:
        """Sandbox-only PoC runner — forge test for a specific exploit test file."""
        limits_off = os.environ.get("HEXSTRIKE_LIMITS_DISABLED", "").lower() in ("1", "true", "yes")
        if limits_off:
            os.environ.setdefault("HEXSTRIKE_SANDBOX", "1")
        if not limits_off and os.environ.get("HEXSTRIKE_SANDBOX", "").lower() not in ("1", "true", "yes"):
            return ToolResult(
                "foundry_poc",
                ok=False,
                skipped=True,
                skip_reason="offense PoC requires HEXSTRIKE_SANDBOX=1",
            )
        return self.foundry_test(project_dir, match=test_path)

    def scan_allowances_hint(self, address: str) -> ToolResult:
        """Defensive hint — recommends Revoke.cash / manual allowance review."""
        return ToolResult(
            "allowance_monitor",
            ok=True,
            findings=[
                {
                    "type": "manual_review",
                    "address": address.lower(),
                    "action": "Review token approvals via Revoke.cash or block explorer",
                    "url": f"https://revoke.cash/address/{address}",
                    "risk": "ice-phishing via unlimited approvals / permits",
                }
            ],
        )
