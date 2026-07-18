"""Campaign trace logger — hook-style capture of tool/skill calls."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
TRACE_DIR = _REPO_ROOT / "artifacts" / "workflow" / "traces"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class CampaignTrace:
    """In-memory campaign trace matching campaign-trace.schema.json."""

    campaign_id: str
    task_id: str = ""
    trace_id: str = field(default_factory=lambda: f"trace-{uuid.uuid4().hex[:12]}")
    outcome: str = "failed"
    started_at: str = field(default_factory=_utc_now)
    finished_at: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    success_criteria_met: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    _seq: int = field(default=0, repr=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "campaign_id": self.campaign_id,
            "task_id": self.task_id,
            "outcome": self.outcome,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "context": self.context,
            "success_criteria_met": self.success_criteria_met,
            "steps": self.steps,
            "artifacts": self.artifacts,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CampaignTrace:
        return cls(
            trace_id=data.get("trace_id", f"trace-{uuid.uuid4().hex[:12]}"),
            campaign_id=data["campaign_id"],
            task_id=data.get("task_id", ""),
            outcome=data.get("outcome", "failed"),
            started_at=data.get("started_at", _utc_now()),
            finished_at=data.get("finished_at"),
            context=data.get("context") or {},
            success_criteria_met=data.get("success_criteria_met") or [],
            steps=data.get("steps") or [],
            artifacts=data.get("artifacts") or [],
            metadata=data.get("metadata") or {},
            _seq=len(data.get("steps") or []),
        )


class CampaignTraceLogger:
    """Hook-style logger: session_start → tool_call → session_end."""

    def __init__(
        self,
        campaign_id: str,
        *,
        task_id: str = "",
        trace_dir: Path | None = None,
        auto_save: bool = True,
    ) -> None:
        self.trace = CampaignTrace(campaign_id=campaign_id, task_id=task_id)
        self.trace_dir = trace_dir or TRACE_DIR
        self.auto_save = auto_save
        self._open_step_start: float | None = None
        self._open_step: dict[str, Any] | None = None

    def session_start(self, context: dict[str, Any] | None = None) -> None:
        if context:
            self.trace.context.update(context)
        self.trace.started_at = _utc_now()
        self._persist()

    def tool_call_start(
        self,
        tool: str,
        *,
        tool_kind: str = "skill",
        input_data: dict[str, Any] | None = None,
        agent: str | None = None,
        task: str | None = None,
        depends_on_seq: list[int] | None = None,
    ) -> int:
        """Begin a step; returns seq for pairing with tool_call_end."""
        self.trace._seq += 1
        seq = self.trace._seq
        self._open_step = {
            "seq": seq,
            "tool": tool,
            "tool_kind": tool_kind,
            "input": input_data or {},
            "status": "running",
            "timestamp": _utc_now(),
        }
        if agent:
            self._open_step["agent"] = agent
        if task:
            self._open_step["task"] = task
        if depends_on_seq:
            self._open_step["depends_on_seq"] = depends_on_seq
        self._open_step_start = time.perf_counter()
        return seq

    def tool_call_end(
        self,
        seq: int,
        *,
        output: dict[str, Any] | None = None,
        status: str = "success",
        error: str | None = None,
    ) -> None:
        if not self._open_step or self._open_step.get("seq") != seq:
            raise ValueError(f"No open step for seq={seq}")
        step = self._open_step
        step["output"] = output or {}
        step["status"] = status
        if error:
            step["error"] = error
        if self._open_step_start is not None:
            step["latency_ms"] = round((time.perf_counter() - self._open_step_start) * 1000, 2)
        self.trace.steps.append(step)
        self._open_step = None
        self._open_step_start = None
        self._persist()

    def add_artifact(self, path: str, kind: str = "output", sha256: str | None = None) -> None:
        entry: dict[str, Any] = {"path": path, "kind": kind}
        if sha256:
            entry["sha256"] = sha256
        self.trace.artifacts.append(entry)
        self._persist()

    def session_end(
        self,
        outcome: str,
        *,
        success_criteria_met: list[str] | None = None,
    ) -> Path:
        self.trace.outcome = outcome
        self.trace.finished_at = _utc_now()
        if success_criteria_met:
            self.trace.success_criteria_met = success_criteria_met
        return self._persist()

    def _persist(self) -> Path:
        self.trace_dir.mkdir(parents=True, exist_ok=True)
        path = self.trace_dir / f"{self.trace.trace_id}.json"
        path.write_text(json.dumps(self.trace.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        latest = self.trace_dir / "latest.json"
        latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        if self.auto_save and self.trace.outcome == "success":
            pending = self.trace_dir / "pending_skillify.json"
            pending.write_text(json.dumps({"trace_id": self.trace.trace_id, "path": str(path)}, indent=2) + "\n")
        return path

    @staticmethod
    def load(path: Path | str) -> CampaignTrace:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return CampaignTrace.from_dict(data)

    @staticmethod
    def list_successful(trace_dir: Path | None = None) -> list[Path]:
        d = trace_dir or TRACE_DIR
        if not d.is_dir():
            return []
        out: list[Path] = []
        for p in sorted(d.glob("trace-*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if data.get("outcome") == "success":
                    out.append(p)
            except (json.JSONDecodeError, OSError):
                continue
        return out
