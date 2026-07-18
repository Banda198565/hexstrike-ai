"""Real Nuclei binary runner — no simulated findings."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARTIFACTS = _REPO_ROOT / "artifacts" / "nuclei"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def resolve_nuclei_bin() -> str:
    for key in ("NUCLEI_BIN_PATH", "NUCLEI_PATH"):
        val = os.environ.get(key, "").strip()
        if val:
            return val
    found = shutil.which("nuclei")
    return found or "nuclei"


def normalize_finding(row: dict[str, Any]) -> dict[str, Any]:
    info = row.get("info") or {}
    return {
        "template_id": row.get("template-id") or row.get("templateID") or info.get("name", ""),
        "name": info.get("name") or row.get("matcher-name", ""),
        "severity": (info.get("severity") or row.get("severity") or "unknown").lower(),
        "host": row.get("host") or row.get("matched-at") or "",
        "matched_at": row.get("matched-at") or row.get("matched") or "",
        "description": info.get("description") or "",
        "tags": info.get("tags") or [],
        "curl_command": row.get("curl-command"),
    }


def parse_nuclei_jsonl(text: str) -> list[dict[str, Any]]:
    """Parse nuclei -jsonl output — returns empty list if no findings (never fabricated)."""
    findings: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("template-id") or row.get("templateID") or (row.get("info")):
            findings.append(normalize_finding(row))
    return findings


class NucleiRunner:
    """Execute real nuclei scans and normalize JSONL output."""

    def __init__(self, *, bin_path: str | None = None, artifacts_dir: Path | None = None) -> None:
        self.bin_path = bin_path or resolve_nuclei_bin()
        self.artifacts_dir = artifacts_dir or DEFAULT_ARTIFACTS
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    def _verify_binary(self) -> str | None:
        if not shutil.which(self.bin_path) and not Path(self.bin_path).is_file():
            return f"Nuclei binary not found: {self.bin_path} (set NUCLEI_BIN_PATH)"
        return None

    def _run(
        self,
        args: list[str],
        *,
        timeout_sec: int = 600,
    ) -> dict[str, Any]:
        err = self._verify_binary()
        if err:
            return {"success": False, "error": err, "findings": [], "command": " ".join([self.bin_path] + args)}

        cmd = [self.bin_path] + args
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_sec,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"nuclei timeout after {timeout_sec}s",
                "findings": [],
                "command": " ".join(cmd),
            }
        except OSError as exc:
            return {"success": False, "error": str(exc), "findings": [], "command": " ".join(cmd)}

        combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
        findings = parse_nuclei_jsonl(proc.stdout or "")
        # Some nuclei versions write JSONL to file only; stderr may contain progress only
        if not findings and proc.returncode == 0:
            findings = []

        return {
            "success": proc.returncode in (0, 1),  # 1 = findings present in some versions
            "exit_code": proc.returncode,
            "findings": findings,
            "command": " ".join(cmd),
            "stderr_tail": (proc.stderr or "")[-500:] if proc.stderr else "",
            "raw_stdout_lines": len((proc.stdout or "").splitlines()),
        }

    def scan(
        self,
        target: str,
        *,
        tags: str | None = None,
        severity: str | None = None,
        rate_limit: int = 50,
        templates: str | None = None,
        json_output_path: str | None = None,
        timeout_sec: int = 600,
        scan_id: str | None = None,
    ) -> dict[str, Any]:
        sid = scan_id or f"nuclei-{_utc_stamp()}-{uuid.uuid4().hex[:8]}"
        out_path = Path(json_output_path) if json_output_path else self.artifacts_dir / f"{sid}.jsonl"
        out_path.parent.mkdir(parents=True, exist_ok=True)

        args = ["-u", target, "-jsonl", "-o", str(out_path), "-rate-limit", str(rate_limit), "-silent"]
        if tags:
            args.extend(["-tags", tags])
        if severity:
            args.extend(["-severity", severity])
        if templates:
            args.extend(["-t", templates])

        result = self._run(args, timeout_sec=timeout_sec)
        result["scan_id"] = sid
        result["target"] = target
        result["raw_report_path"] = str(out_path)

        # Re-parse from file if stdout empty but file exists
        if not result["findings"] and out_path.is_file() and out_path.stat().st_size > 0:
            result["findings"] = parse_nuclei_jsonl(out_path.read_text(encoding="utf-8", errors="replace"))

        result["finding_count"] = len(result["findings"])
        return result

    def basic_scan(
        self,
        target: str,
        *,
        rate_limit: int = 30,
        timeout_sec: int = 300,
    ) -> dict[str, Any]:
        return self.scan(
            target,
            tags="cve,misconfig,exposure",
            severity="medium,high,critical",
            rate_limit=rate_limit,
            timeout_sec=timeout_sec,
        )

    def list_tags(self, *, timeout_sec: int = 120) -> dict[str, Any]:
        """List template tags via nuclei -tl -json (real template index)."""
        err = self._verify_binary()
        if err:
            return {"success": False, "error": err, "tags": []}

        cmd = [self.bin_path, "-tl", "-json", "-silent"]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, check=False)
        except (subprocess.TimeoutExpired, OSError) as exc:
            return {"success": False, "error": str(exc), "tags": []}

        tags: set[str] = set()
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            info = row.get("info") or {}
            for tag in info.get("tags") or []:
                if isinstance(tag, str):
                    tags.add(tag)

        return {
            "success": proc.returncode == 0,
            "tags": sorted(tags),
            "tag_count": len(tags),
            "command": " ".join(cmd),
        }
