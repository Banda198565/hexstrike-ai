"""mcp_storage_gate — access control for sensitive system and credential files."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hexstrike.bus.context_bus import ContextBus
from hexstrike.paths import ARTIFACTS_DIR, CONFIG_DIR, ROOT

# Paths that require operator approval before write/delete
_PROTECTED_GLOBS = (
    "config.xml",
    "credentials.xml",
    "keystore.enc",
    "mcp.json",
    "mcp-hub.json",
)

_STORAGE_PENDING = ARTIFACTS_DIR / "storage_pending.json"


@dataclass
class StorageGateMcp:
    """Gate read/write access to sensitive config and credential artifacts."""

    bus: ContextBus
    pending_path: Path = _STORAGE_PENDING
    protected_roots: list[Path] = field(default_factory=lambda: [CONFIG_DIR, ROOT / ".cursor", ARTIFACTS_DIR / "vault"])

    def _is_protected(self, path: Path) -> bool:
        name = path.name.lower()
        if any(token in name for token in _PROTECTED_GLOBS):
            return True
        for root in self.protected_roots:
            try:
                path.resolve().relative_to(root.resolve())
                if path.suffix in {".xml", ".enc", ".key", ".pem"}:
                    return True
            except ValueError:
                continue
        return False

    def read(self, path: str | Path) -> dict[str, Any]:
        """Read a file — allowed for protected paths (audit logging only)."""
        target = Path(path).expanduser()
        if not target.is_file():
            return {"success": False, "error": "not_found", "path": str(target)}

        protected = self._is_protected(target)
        content = target.read_text(encoding="utf-8", errors="replace")
        self.bus.publish(
            "mcp.storage.read",
            {"path": str(target), "protected": protected, "bytes": len(content)},
            source="mcp_storage_gate",
        )
        return {
            "success": True,
            "path": str(target),
            "protected": protected,
            "content": content[:8000],
            "truncated": len(content) > 8000,
        }

    def request_write(self, path: str | Path, content: str, *, reason: str = "") -> dict[str, Any]:
        """Queue a write to a protected path — requires operator approval."""
        target = Path(path).expanduser()
        if not self._is_protected(target):
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            self.bus.publish("mcp.storage.written", {"path": str(target)}, source="mcp_storage_gate")
            return {"success": True, "path": str(target), "gated": False}

        pending = {
            "status": "awaiting_operator_review",
            "created_at": datetime.now(tz=timezone.utc).isoformat(),
            "action": "write_file",
            "path": str(target),
            "reason": reason,
            "content_preview": content[:500],
            "content_bytes": len(content),
        }
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        self.pending_path.write_text(json.dumps(pending, indent=2) + "\n", encoding="utf-8")
        self.bus.publish("mcp.storage.write_queued", {"path": str(target)}, source="mcp_storage_gate")
        return {"success": True, "gated": True, "pending": pending}

    def approve_write(self, operator_note: str = "") -> dict[str, Any]:
        """Apply queued write after operator approval."""
        if not self.pending_path.is_file():
            return {"success": False, "error": "no_pending_storage_action"}

        pending = json.loads(self.pending_path.read_text(encoding="utf-8"))
        if pending.get("status") != "awaiting_operator_review":
            return {"success": False, "error": "invalid_pending_status", "status": pending.get("status")}

        # Full content stored in pending after approval request in production;
        # operator must paste full payload into storage_pending.json["content"] before approve.
        content = pending.get("content")
        if not content:
            pending["status"] = "approved_pending_content"
            pending["operator_note"] = operator_note
            self.pending_path.write_text(json.dumps(pending, indent=2) + "\n", encoding="utf-8")
            return {
                "success": False,
                "error": "content_missing_in_pending",
                "note": "Add full 'content' field to storage_pending.json before approve",
            }

        target = Path(pending["path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        pending["status"] = "approved"
        pending["approved_at"] = datetime.now(tz=timezone.utc).isoformat()
        pending["operator_note"] = operator_note
        self.pending_path.write_text(json.dumps(pending, indent=2) + "\n", encoding="utf-8")
        self.bus.publish("mcp.storage.write_approved", {"path": str(target)}, source="mcp_storage_gate")
        return {"success": True, "path": str(target)}

    def reject_write(self, operator_note: str = "") -> dict[str, Any]:
        pending = {}
        if self.pending_path.is_file():
            pending = json.loads(self.pending_path.read_text(encoding="utf-8"))
        pending["status"] = "rejected"
        pending["rejected_at"] = datetime.now(tz=timezone.utc).isoformat()
        pending["operator_note"] = operator_note
        self.pending_path.write_text(json.dumps(pending, indent=2) + "\n", encoding="utf-8")
        self.bus.publish("mcp.storage.write_rejected", {}, source="mcp_storage_gate")
        return {"success": True}

    def status(self) -> dict[str, Any]:
        pending = None
        if self.pending_path.is_file():
            try:
                pending = json.loads(self.pending_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pending = {"status": "corrupt"}
        return {
            "has_pending": pending is not None,
            "pending_status": (pending or {}).get("status"),
            "path": str(self.pending_path),
            "protected_patterns": list(_PROTECTED_GLOBS),
        }
