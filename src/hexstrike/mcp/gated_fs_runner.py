"""Gated filesystem runner — read-only listing/reading + controlled report writes."""

from __future__ import annotations

import difflib
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_CONFIG = _REPO_ROOT / "config" / "gated-mcp.json"

_IMMUTABLE_PREFIXES = (
    "artifacts/workflow/traces",
    "attack_logs",
    "nuclei_steps",
    "artifacts/nuclei",
    "logs",
)


def _load_config() -> dict[str, Any]:
    if _DEFAULT_CONFIG.is_file():
        return json.loads(_DEFAULT_CONFIG.read_text(encoding="utf-8"))
    return {"filesystem": {}}


def _resolve_safe(rel_path: str) -> Path:
    raw = rel_path.strip().replace("\\", "/").lstrip("/")
    if not raw or raw.startswith("..") or "/../" in f"/{raw}/":
        raise ValueError("path traversal forbidden")
    resolved = (_REPO_ROOT / raw).resolve()
    if not str(resolved).startswith(str(_REPO_ROOT.resolve())):
        raise ValueError("path outside repository root")
    rel = str(resolved.relative_to(_REPO_ROOT.resolve())).replace("\\", "/")
    for blocked in _IMMUTABLE_PREFIXES:
        if rel == blocked or rel.startswith(blocked + "/"):
            raise ValueError(f"immutable path: {rel}")
    return resolved


def _under_root(path: Path, roots: list[str]) -> bool:
    rel = str(path.relative_to(_REPO_ROOT.resolve())).replace("\\", "/")
    for root in roots:
        r = root.strip("/")
        if rel == r or rel.startswith(r + "/"):
            return True
    return False


def fs_list_dir(path: str) -> dict[str, Any]:
    """List directories and files under an allowed read root."""
    cfg = _load_config().get("filesystem", {})
    read_roots = cfg.get("read_roots") or []
    try:
        target = _resolve_safe(path)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    if not _under_root(target, read_roots):
        return {"success": False, "error": f"path not in read_roots: {path}"}
    if not target.is_dir():
        return {"success": False, "error": "not a directory", "path": path}

    directories = sorted(p.name for p in target.iterdir() if p.is_dir())
    files = sorted(p.name for p in target.iterdir() if p.is_file())
    return {
        "success": True,
        "path": path.strip().lstrip("/"),
        "directories": directories,
        "files": files,
        "read_only": True,
    }


def fs_read_file(path: str) -> dict[str, Any]:
    """Read file content from allowlisted paths."""
    cfg = _load_config().get("filesystem", {})
    read_roots = cfg.get("read_roots") or []
    max_bytes = int(cfg.get("max_read_bytes") or 524288)
    try:
        target = _resolve_safe(path)
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    if not _under_root(target, read_roots):
        return {"success": False, "error": f"path not in read_roots: {path}"}
    if not target.is_file():
        return {"success": False, "error": "not a file", "path": path}

    data = target.read_bytes()
    if len(data) > max_bytes:
        return {
            "success": False,
            "error": f"file exceeds max_read_bytes ({max_bytes})",
            "path": path,
        }
    try:
        content = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"success": False, "error": "binary file — read not supported", "path": path}

    return {
        "success": True,
        "path": path.strip().lstrip("/"),
        "content": content,
        "bytes": len(data),
        "read_only": True,
    }


def fs_create_report_file(
    directory: str,
    filename: str,
    content: str,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create audit report in allowlisted write directory only."""
    cfg = _load_config().get("filesystem", {})
    write_roots = cfg.get("write_roots") or []
    max_bytes = int(cfg.get("max_report_bytes") or 2097152)

    safe_name = Path(filename).name
    if safe_name != filename or ".." in filename:
        return {"success": False, "error": "invalid filename", "status": "error"}

    try:
        dir_path = _resolve_safe(directory.rstrip("/"))
    except ValueError as exc:
        return {"success": False, "error": str(exc), "status": "error"}

    if not _under_root(dir_path, write_roots):
        return {"success": False, "error": f"directory not in write_roots: {directory}", "status": "error"}

    if len(content.encode("utf-8")) > max_bytes:
        return {"success": False, "error": "content exceeds max_report_bytes", "status": "error"}

    dir_path.mkdir(parents=True, exist_ok=True)
    out = dir_path / safe_name
    rel_out = str(out.relative_to(_REPO_ROOT)).replace("\\", "/")
    existed = out.exists()

    if existed and not overwrite:
        return {
            "success": False,
            "path": rel_out,
            "status": "exists",
            "error": "file exists — set overwrite=true with user confirmation",
        }

    out.write_text(content, encoding="utf-8")
    return {
        "success": True,
        "path": rel_out,
        "status": "overwritten" if existed else "created",
        "bytes": len(content.encode("utf-8")),
    }


def fs_read_report_index(directory: str = "reports") -> dict[str, Any]:
    """List report files in an allowlisted directory."""
    cfg = _load_config().get("filesystem", {})
    read_roots = cfg.get("read_roots") or []
    try:
        dir_path = _resolve_safe(directory.rstrip("/"))
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    if not _under_root(dir_path, read_roots):
        return {"success": False, "error": f"directory not in read_roots: {directory}"}
    if not dir_path.is_dir():
        return {"success": False, "error": "not a directory"}

    reports: list[dict[str, str]] = []
    for p in sorted(dir_path.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if p.is_file() and p.suffix in (".md", ".json", ".txt"):
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
            reports.append(
                {
                    "filename": p.name,
                    "path": str(p.relative_to(_REPO_ROOT)).replace("\\", "/"),
                    "created_at": mtime,
                }
            )
    return {"success": True, "directory": directory.strip("/"), "reports": reports, "read_only": True}


def fs_edit_file(
    path: str,
    original_snippet: str,
    new_snippet: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Preview or apply a snippet replacement — dry_run default true; apply needs env gate."""
    cfg = _load_config().get("filesystem", {})
    edit_roots = cfg.get("edit_roots") or []
    read_roots = cfg.get("read_roots") or []

    try:
        target = _resolve_safe(path)
    except ValueError as exc:
        return {"success": False, "error": str(exc), "applied": False}

    if not target.is_file():
        return {"success": False, "error": "not a file", "applied": False}

    allowed = _under_root(target, edit_roots) if edit_roots else False
    can_read = _under_root(target, read_roots)
    if not can_read:
        return {"success": False, "error": f"path not readable: {path}", "applied": False}

    current = target.read_text(encoding="utf-8")
    if original_snippet not in current:
        return {
            "success": False,
            "error": "original_snippet not found in file",
            "applied": False,
            "path": path,
        }

    new_content = current.replace(original_snippet, new_snippet, 1)
    diff = "\n".join(
        difflib.unified_diff(
            current.splitlines(),
            new_content.splitlines(),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            lineterm="",
        )
    )

    apply_ok = os.environ.get("HEXSTRIKE_FS_APPLY", "").lower() in ("1", "true", "yes")
    if dry_run or not allowed or not apply_ok:
        return {
            "success": True,
            "path": path,
            "preview_diff": diff,
            "applied": False,
            "dry_run": True,
            "note": "apply requires edit_roots + HEXSTRIKE_FS_APPLY=1 + dry_run=false",
        }

    target.write_text(new_content, encoding="utf-8")
    return {
        "success": True,
        "path": path,
        "preview_diff": diff,
        "applied": True,
        "dry_run": False,
    }
