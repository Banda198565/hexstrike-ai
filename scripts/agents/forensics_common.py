#!/usr/bin/env python3
"""Shared helpers for read-only malware/contract forensics agents."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts"
ETH_ADDR = re.compile(r"0x[a-fA-F0-9]{40}")
SOL_ADDR = re.compile(r"[1-9A-HJ-NP-Za-km-z]{32,44}")
HOST = re.compile(r"(?:https?://)?([a-zA-Z0-9.-]+\.[a-zA-Z]{2,})")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def output_path(name: str) -> Path:
    env = os.environ.get("OUTPUT")
    if env:
        p = Path(env)
        return p if p.is_absolute() else ROOT / p
    return ARTIFACTS / name


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def scan_tree(root: Path, *, max_files: int = 400) -> dict[str, Any]:
    if not root.is_dir():
        return {"root": str(root), "exists": False, "files_analyzed": 0, "addresses": [], "hosts": []}

    addresses: set[str] = set()
    hosts: set[str] = set()
    files_analyzed = 0
    exts = {".js", ".ts", ".tsx", ".jsx", ".py", ".go", ".sol", ".json", ".env", ".md", ".html", ".sh"}

    for path in root.rglob("*"):
        if files_analyzed >= max_files:
            break
        if not path.is_file() or path.suffix.lower() not in exts:
            continue
        if any(part in {".git", "node_modules", "dist", "build", ".next"} for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        files_analyzed += 1
        for m in ETH_ADDR.findall(text):
            addresses.add(m.lower())
        for m in SOL_ADDR.findall(text):
            if len(m) >= 32:
                addresses.add(m)
        for m in HOST.findall(text):
            if "." in m and not m.endswith(".local"):
                hosts.add(m.lower())

    return {
        "root": str(root),
        "exists": True,
        "files_analyzed": files_analyzed,
        "addresses": sorted(addresses),
        "hosts": sorted(hosts),
    }


def load_intel(name: str) -> dict[str, Any]:
    path = ARTIFACTS / "recon" / name
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def emit(payload: dict[str, Any]) -> int:
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("success", True) else 1
