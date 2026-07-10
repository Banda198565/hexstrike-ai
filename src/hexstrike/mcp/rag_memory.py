"""mcp_rag_memory — LanceDB interface for historical pattern retrieval."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hexstrike.bus.context_bus import ContextBus
from hexstrike.paths import ROOT, RAG_ROOT

RAG_PYTHON = Path(os.environ.get("RAG_PYTHON", str(ROOT / "rag-env" / "bin" / "python")))
RAG_SCRIPT = ROOT / "scripts" / "rag_core.py"


def _rag_subprocess(action: str, **kwargs: Any) -> Any:
    """Run rag_core via dedicated rag-env Python (3.12) when main interpreter lacks deps."""
    py = RAG_PYTHON if RAG_PYTHON.is_file() else Path(sys.executable)
    env = {**os.environ, "RAG_STORAGE_ROOT": os.environ.get("RAG_STORAGE_ROOT", str(RAG_ROOT))}
    payload = json.dumps({"action": action, **kwargs})

    proc = subprocess.run(
        [str(py), str(RAG_SCRIPT), "--rpc", payload],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "rag subprocess failed")
    return json.loads(proc.stdout)


def _try_direct_import():
    sys.path.insert(0, str(ROOT / "scripts"))
    from rag_core import (  # noqa: E402
        RagStorageError,
        index_false_positive,
        is_false_positive_pattern,
        search_history,
    )
    return RagStorageError, index_false_positive, is_false_positive_pattern, search_history


@dataclass
class RagMemoryMcp:
    """LanceDB-backed forensic memory for agents."""

    bus: ContextBus
    _use_subprocess: bool = False

    def __post_init__(self) -> None:
        self._use_subprocess = RAG_PYTHON.is_file()
        if not self._use_subprocess:
            try:
                _try_direct_import()
            except ImportError:
                self._use_subprocess = False

    def search(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        try:
            if self._use_subprocess and RAG_PYTHON.is_file():
                data = _rag_subprocess("search", query=query, top_k=top_k)
                hits = data.get("results", [])
            else:
                _, _, _, search_history = _try_direct_import()
                hits = search_history(query, top_k=top_k)
            self.bus.publish(
                "mcp.rag.search",
                {"query": query[:120], "hits": len(hits)},
                source="mcp_rag_memory",
            )
            return hits
        except (OSError, ImportError, RuntimeError, json.JSONDecodeError) as exc:
            self.bus.publish("mcp.rag.error", {"error": str(exc)}, source="mcp_rag_memory")
            return []

    def is_false_positive(self, tx_hash: str, frm: str, to: str) -> tuple[bool, list]:
        try:
            if self._use_subprocess and RAG_PYTHON.is_file():
                data = _rag_subprocess("is_false_positive", tx_hash=tx_hash, frm=frm, to=to)
                return bool(data.get("match")), data.get("hits", [])
            _, _, is_false_positive_pattern, _ = _try_direct_import()
            return is_false_positive_pattern(tx_hash, frm, to)
        except (OSError, ImportError, RuntimeError, json.JSONDecodeError):
            return False, []

    def index_feedback(self, tx_hash: str, frm: str, to: str, note: str = "") -> dict[str, Any]:
        try:
            if self._use_subprocess and RAG_PYTHON.is_file():
                return _rag_subprocess("index_feedback", tx_hash=tx_hash, frm=frm, to=to, note=note)
            _, index_false_positive, _, _ = _try_direct_import()
            index_false_positive(tx_hash, frm, to, note)
            self.bus.publish("mcp.rag.feedback_indexed", {"tx_hash": tx_hash}, source="mcp_rag_memory")
            return {"success": True}
        except (OSError, ImportError, RuntimeError, json.JSONDecodeError) as exc:
            return {"success": False, "error": str(exc)}
