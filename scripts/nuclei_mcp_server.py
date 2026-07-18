#!/usr/bin/env python3
"""HexStrike Nuclei MCP Server — real scans only, no simulated findings.

Tools:
  - nuclei_scan      — full scan with tags/severity/rate-limit
  - basic_scan       — fast cve/misconfig/exposure scan
  - get_nuclei_tags  — list available template tags

Env:
  NUCLEI_BIN_PATH / NUCLEI_PATH — path to nuclei binary
  NUCLEI_ARTIFACTS_DIR          — default artifacts/nuclei

Usage (stdio MCP):
  python3 scripts/nuclei_mcp_server.py

Cursor mcp.json:
  see config/mcp/nuclei-mcp.json
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from mcp.server.fastmcp import FastMCP

from hexstrike.mcp.nuclei_runner import NucleiRunner

mcp = FastMCP("nuclei_mcp")
_runner = NucleiRunner()


def _maybe_trace(tool: str, input_data: dict, output: dict) -> None:
    """Optional hook: append to campaign trace when HEXSTRIKE_TRACE_ID is set."""
    trace_id = os.environ.get("HEXSTRIKE_TRACE_ID", "").strip()
    if not trace_id:
        return
    try:
        from hexstrike.workflow.trace_logger import CampaignTraceLogger

        # Minimal append — full session managed by orchestrator
        log_path = ROOT / "artifacts" / "workflow" / "traces" / f"{trace_id}.json"
        if not log_path.is_file():
            return
        data = json.loads(log_path.read_text(encoding="utf-8"))
        seq = len(data.get("steps", [])) + 1
        data.setdefault("steps", []).append(
            {
                "seq": seq,
                "tool": tool,
                "tool_kind": "mcp",
                "input": input_data,
                "output": {
                    "success": output.get("success"),
                    "finding_count": output.get("finding_count", len(output.get("findings", []))),
                    "raw_report_path": output.get("raw_report_path"),
                },
                "status": "success" if output.get("success") else "failed",
            }
        )
        log_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    except Exception:
        pass


@mcp.tool()
def nuclei_scan(
    target: str,
    tags: Optional[str] = None,
    severity: Optional[str] = None,
    rate_limit: int = 50,
    json_output_path: Optional[str] = None,
    timeout_sec: int = 600,
) -> str:
    """Run a real Nuclei scan against target with optional tags/severity filters.

    Returns normalized JSON with findings from actual nuclei -jsonl output.
    Never fabricates findings — empty array means nuclei found nothing.
    """
    inp = {
        "target": target,
        "tags": tags,
        "severity": severity,
        "rate_limit": rate_limit,
        "json_output_path": json_output_path,
    }
    result = _runner.scan(
        target,
        tags=tags,
        severity=severity,
        rate_limit=rate_limit,
        json_output_path=json_output_path,
        timeout_sec=timeout_sec,
    )
    _maybe_trace("nuclei_scan", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def basic_scan(
    target: str,
    rate_limit: int = 30,
    timeout_sec: int = 300,
) -> str:
    """Quick Nuclei scan (tags: cve,misconfig,exposure; severity: medium+). Real binary only."""
    inp = {"target": target, "rate_limit": rate_limit}
    result = _runner.basic_scan(target, rate_limit=rate_limit, timeout_sec=timeout_sec)
    _maybe_trace("basic_scan", inp, result)
    return json.dumps(result, ensure_ascii=False)


@mcp.tool()
def get_nuclei_tags() -> str:
    """List available Nuclei template tags from real template index (-tl -json)."""
    result = _runner.list_tags()
    return json.dumps(result, ensure_ascii=False)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
