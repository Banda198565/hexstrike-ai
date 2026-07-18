#!/usr/bin/env python3
"""Unit tests for gated MCP runners (filesystem gates — offline-safe)."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from hexstrike.mcp.gated_fs_runner import (  # noqa: E402
    fs_create_report_file,
    fs_edit_file,
    fs_list_dir,
    fs_read_file,
    fs_read_report_index,
)


def test_list_and_read_contract() -> None:
    r = fs_list_dir("scripts/sandbox/contracts")
    assert r["success"] is True
    assert "Bank.sol" in r["files"]

    content = fs_read_file("scripts/sandbox/contracts/Bank.sol")
    assert content["success"] is True
    assert "contract Bank" in content["content"]


def test_block_traversal() -> None:
    bad = fs_read_file("../../etc/passwd")
    assert bad["success"] is False


def test_block_immutable_logs() -> None:
    blocked = fs_read_file("artifacts/workflow/traces/dummy.json")
    assert blocked["success"] is False


def test_create_report() -> None:
    with tempfile.TemporaryDirectory(dir=ROOT / "reports") as tmp:
        rel = Path(tmp).relative_to(ROOT)
        name = f"test-gated-{os.getpid()}.md"
        r = fs_create_report_file(str(rel), name, "# test report\n", overwrite=False)
        assert r["success"] is True
        assert r["status"] == "created"
        dup = fs_create_report_file(str(rel), name, "# dup\n", overwrite=False)
        assert dup["status"] == "exists"


def test_edit_dry_run() -> None:
    r = fs_edit_file(
        "scripts/sandbox/contracts/Bank.sol",
        "contract Bank",
        "contract BankPatched",
        dry_run=True,
    )
    assert r["success"] is True
    assert r["applied"] is False
    assert "BankPatched" in r.get("preview_diff", "")


def test_report_index() -> None:
    r = fs_read_report_index("reports")
    assert r["success"] is True
    assert "reports" in r


def main() -> int:
    test_list_and_read_contract()
    test_block_traversal()
    test_block_immutable_logs()
    test_create_report()
    test_edit_dry_run()
    test_report_index()
    print("gated_mcp_runner: 7/7 PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
