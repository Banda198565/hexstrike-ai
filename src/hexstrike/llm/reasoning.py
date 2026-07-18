"""HexStrike Reasoning Agent — cloud R1 planner (plan only, no execution)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hexstrike.llm.cloud_r1 import CloudR1Provider, extract_json_object, resolve_cloud_r1_config

_REPO_ROOT = Path(__file__).resolve().parents[3]
REASONING_PROMPT_PATH = _REPO_ROOT / "config" / "reasoning-system-prompt.md"
PROTOCOL_EXAMPLE_PATH = _REPO_ROOT / "config" / "reasoning-protocol.example.json"


@dataclass
class ReasoningTask:
    task_id: str
    goal: str
    mode: str = "defense"
    context: dict[str, Any] = field(default_factory=dict)
    tools: list[dict[str, Any]] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    prior_steps: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ReasoningTask:
        return cls(
            task_id=data.get("task_id") or uuid.uuid4().hex[:12],
            goal=data["goal"],
            mode=data.get("mode", "defense"),
            context=data.get("context") or {},
            tools=data.get("tools") or [],
            constraints=data.get("constraints") or {},
            prior_steps=data.get("prior_steps") or [],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "goal": self.goal,
            "mode": self.mode,
            "context": self.context,
            "tools": self.tools,
            "constraints": self.constraints,
            "prior_steps": self.prior_steps,
        }


def load_reasoning_system_prompt(path: Path | None = None) -> str:
    p = path or REASONING_PROMPT_PATH
    if p.is_file():
        return p.read_text(encoding="utf-8").strip()
    return (
        "HexStrike Reasoning Agent. Plan defense-only workflows. "
        "Output JSON plan only. Do not execute tools."
    )


def build_planning_messages(task: ReasoningTask, system_prompt: str | None = None) -> list[dict[str, str]]:
    """Build chat messages for R1 planning call."""
    defense = load_reasoning_system_prompt() if system_prompt is None else system_prompt
    user_payload = json.dumps(task.to_dict(), ensure_ascii=False, indent=2)
    return [
        {"role": "system", "content": defense},
        {
            "role": "user",
            "content": (
                "Plan the following HexStrike task. Return ONLY valid JSON matching the response schema.\n\n"
                f"{user_payload}"
            ),
        },
    ]


def validate_plan(plan: dict[str, Any], task: ReasoningTask) -> list[str]:
    """Validate R1 plan against task constraints. Returns list of warnings/errors."""
    issues: list[str] = []
    if plan.get("task_id") and plan["task_id"] != task.task_id:
        issues.append(f"task_id mismatch: expected {task.task_id}, got {plan['task_id']}")

    steps = plan.get("steps") or []
    if not isinstance(steps, list):
        issues.append("steps must be a list")
        return issues

    max_steps = int(task.constraints.get("max_steps", 20))
    if len(steps) > max_steps:
        issues.append(f"plan exceeds max_steps ({len(steps)} > {max_steps})")

    allowed = {(t.get("agent"), t.get("task")) for t in task.tools}

    for step in steps:
        agent = step.get("agent")
        task_name = step.get("task")
        if (agent, task_name) not in allowed:
            issues.append(f"unknown step agent/task: {agent}/{task_name}")

    if task.constraints.get("read_only") and task.mode not in ("offense", "validation"):
        for step in steps:
            args = step.get("args") or {}
            if args.get("intrusive") or args.get("exploit"):
                issues.append(f"read_only violation in step {step.get('step_id')}")

    return issues


class ReasoningAgent:
    """Cloud R1 reasoning backend — plans only, delegates execution to worker agents."""

    def __init__(self, provider: CloudR1Provider | None = None) -> None:
        self.provider = provider or CloudR1Provider(resolve_cloud_r1_config())

    def plan(
        self,
        task: ReasoningTask | dict[str, Any],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = 4096,
    ) -> dict[str, Any]:
        """Call cloud R1 and return parsed + validated plan."""
        rt = task if isinstance(task, ReasoningTask) else ReasoningTask.from_dict(task)
        messages = build_planning_messages(rt)
        response = self.provider.chat(messages, temperature=temperature, max_tokens=max_tokens)

        result: dict[str, Any] = {
            "task": rt.to_dict(),
            "provider": self.provider.config.provider,
            "model": self.provider.config.model,
            "llm": response,
        }

        if not response.get("ok"):
            result["ok"] = False
            result["error"] = response.get("error", "LLM call failed")
            return result

        raw_text = response.get("content") or ""
        if not raw_text.strip() and response.get("reasoning_content"):
            raw_text = response["reasoning_content"]

        try:
            plan = extract_json_object(raw_text)
        except (json.JSONDecodeError, ValueError) as exc:
            result["ok"] = False
            result["error"] = f"Failed to parse plan JSON: {exc}"
            result["raw_content"] = raw_text[:2000]
            return result

        validation = validate_plan(plan, rt)
        result["ok"] = len(validation) == 0 or all("mismatch" not in v for v in validation)
        result["plan"] = plan
        result["validation"] = validation
        result["step_count"] = len(plan.get("steps") or [])
        return result

    def plan_from_file(self, path: Path | str) -> dict[str, Any]:
        """Load task JSON from file and plan."""
        p = Path(path)
        data = json.loads(p.read_text(encoding="utf-8"))
        return self.plan(data)

    def status(self) -> dict[str, Any]:
        return {
            "role": "reasoning-agent",
            "executes_tools": False,
            "provider": self.provider.status(),
            "protocol_example": str(PROTOCOL_EXAMPLE_PATH),
            "system_prompt": str(REASONING_PROMPT_PATH),
        }
