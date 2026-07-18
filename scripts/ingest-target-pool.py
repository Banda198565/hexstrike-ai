#!/usr/bin/env python3
"""Ingest target pool from Desktop тест ЦЕЛИ or SAMSON_TARGETS_DIR."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_EVM = re.compile(r"0x[a-fA-F0-9]{40}")
_URL = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_IPV4 = re.compile(
    r"(?<![\w.])(?:(?:25[0-5]|2[0-4]\d|[01]?\d?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|[01]?\d?\d)(?![\w.])"
)
_TEXT_SUFFIXES = {".txt", ".md", ".json", ".yaml", ".yml", ".csv", ".log", ".html", ".htm"}


def _lite_scan(root: Path) -> dict:
    """Scan without Samson deps — extract indicators, no live HTTP probe."""
    found: dict[str, set[str]] = {"web3": set(), "url": set(), "ip": set()}
    files = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES and path.suffix:
            continue
        files.append(str(path.relative_to(root)))
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _EVM.finditer(text):
            found["web3"].add(m.group(0).lower())
        for m in _URL.finditer(text):
            found["url"].add(m.group(0).rstrip(".,;"))
        for m in _IPV4.finditer(text):
            found["ip"].add(m.group(0))

    return {
        "success": True,
        "mode": "lite",
        "source_root": str(root.resolve()),
        "file_count": len(files),
        "files": files,
        "indicators": {k: sorted(v) for k, v in found.items()},
        "note": "Lite scan — no live probe. Full ingest: pip install -r requirements-samson.txt",
    }


def _full_ingest(root: Path | None, output: Path) -> dict:
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "src"))
    from samson.core.target_loader import TargetLoader

    loader = TargetLoader(explicit_root=root) if root else TargetLoader()
    pool = loader.load()
    out = output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pool.model_dump(mode="json"), indent=2, default=str) + "\n", encoding="utf-8")
    return {
        "success": True,
        "mode": "full",
        "source_root": pool.source_root,
        "unique_count": pool.unique_count,
        "scanned_files": pool.scanned_files,
        "dropped_junk": pool.dropped_junk,
        "dropped_offline": pool.dropped_offline,
        "output": str(out),
        "targets": [{"kind": t.kind.value, "value": t.normalized_value} for t in pool.targets],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest ~/Desktop/тест ЦЕЛИ target pool")
    parser.add_argument("--root", help="Target pool root directory")
    parser.add_argument(
        "--output",
        default=str(ROOT / "artifacts" / "target-pool" / "ingested-pool.json"),
        help="Write full ingest JSON here",
    )
    parser.add_argument("--dry-run", action="store_true", help="Lite scan only — no live probe")
    parser.add_argument("--lite", action="store_true", help="Alias for --dry-run")
    args = parser.parse_args()

    root_path = Path(args.root) if args.root else None
    if root_path is None:
        desktop = Path.home() / "Desktop" / "тест ЦЕЛИ"
        env = __import__("os").environ.get("SAMSON_TARGETS_DIR")
        if env and Path(env).is_dir():
            root_path = Path(env)
        elif desktop.is_dir():
            root_path = desktop
        else:
            root_path = ROOT / "data" / "pentest" / "targets"

    if not root_path.is_dir():
        print(json.dumps({"success": False, "error": f"not a directory: {root_path}"}), file=sys.stderr)
        return 1

    if args.dry_run or args.lite:
        print(json.dumps(_lite_scan(root_path), indent=2, ensure_ascii=False))
        return 0

    try:
        result = _full_ingest(root_path, Path(args.output))
    except ModuleNotFoundError as exc:
        print(json.dumps({
            "success": False,
            "error": str(exc),
            "hint": "pip install -r requirements-samson.txt for full ingest with live probe",
            "fallback": "python3 scripts/ingest-target-pool.py --dry-run",
        }, indent=2), file=sys.stderr)
        return 1
    except Exception as exc:
        print(json.dumps({"success": False, "error": str(exc)}, indent=2), file=sys.stderr)
        return 1

    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
