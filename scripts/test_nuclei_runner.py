#!/usr/bin/env python3
"""Unit tests for Nuclei JSONL parser — no binary required."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.mcp.nuclei_runner import parse_nuclei_jsonl, normalize_finding


SAMPLE_JSONL = """
{"template-id":"tech-detect","info":{"name":"Tech Detect","severity":"info","description":"detect tech","tags":["tech"]},"host":"https://example.com","matched-at":"https://example.com"}
not-json
{"template-id":"cve-test","info":{"name":"CVE Test","severity":"high","description":"test vuln","tags":["cve"]},"host":"https://example.com","matched-at":"https://example.com/api"}
"""


def test_parse_findings():
    findings = parse_nuclei_jsonl(SAMPLE_JSONL)
    assert len(findings) == 2
    assert findings[0]["severity"] == "info"
    assert findings[1]["template_id"] == "cve-test"
    assert "cve" in findings[1]["tags"]


def test_empty_means_empty():
    assert parse_nuclei_jsonl("") == []
    assert parse_nuclei_jsonl("progress line only\n") == []


if __name__ == "__main__":
    test_parse_findings()
    test_empty_means_empty()
    print("OK")
