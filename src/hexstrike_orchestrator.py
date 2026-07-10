#!/usr/bin/env python3
"""CLI entrypoint shim — delegates to repo-root hexstrike_orchestrator.py."""

from __future__ import annotations

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

if __name__ == "__main__":
    runpy.run_path(str(ROOT / "hexstrike_orchestrator.py"), run_name="__main__")
