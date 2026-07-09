#!/usr/bin/env python3
"""
HexStrike Orchestrator — dispatches tasks to registered agents.

Run on Mac/VPS separately from Cursor chat. Chat plans; orchestrator executes.

Examples:
  ./hexstrike-orchestrator run entity-id-pipeline
  ./hexstrike-orchestrator dispatch Agent-OSINT-03 entity-resolution
  ./hexstrike-orchestrator enqueue agents/queue/job.json
  ./hexstrike-orchestrator watch
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "agents/registry.json"
WORKFLOWS = ROOT / "agents/workflows.json"
AGENT_RUNNER = ROOT / "scripts/hexstrike-agent.py"
QUEUE_DIR = ROOT / "agents/queue"
LOG_DIR = ROOT / "artifacts/orchestrator"


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path) -> dict:
    with open(path) as f:
        return json.load(f)


def log_run(record: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    run_id = record.get("run_id", uuid.uuid4().hex[:12])
    path = LOG_DIR / f"{run_id}.json"
    with open(path, "w") as f:
        json.dump(record, f, indent=2)
    latest = LOG_DIR / "latest.json"
    with open(latest, "w") as f:
        json.dump(record, f, indent=2)
    return path


def run_agent(agent: str, task: str, env: dict | None = None) -> dict:
    cmd = [sys.executable, str(AGENT_RUNNER), "--agent", agent, "--task", task]
    proc_env = os.environ.copy()
    if env:
        proc_env.update({k.upper() if k.islower() else k: str(v) for k, v in env.items()})
    started = utc_now()
    proc = subprocess.run(cmd, cwd=str(ROOT), env=proc_env, capture_output=True, text=True)
    return {
        "agent": agent,
        "task": task,
        "started_at": started,
        "finished_at": utc_now(),
        "exit_code": proc.returncode,
        "stdout": proc.stdout.strip()[-2000:],
        "stderr": proc.stderr.strip()[-2000:],
        "success": proc.returncode == 0,
    }


def run_workflow(name: str, env: dict | None = None) -> int:
    wf_data = load_json(WORKFLOWS)
    workflows = wf_data.get("workflows", {})
    if name not in workflows:
        print(json.dumps({"success": False, "error": f"Unknown workflow: {name}", "known": list(workflows)}))
        return 1

    wf = workflows[name]
    run_id = uuid.uuid4().hex[:12]
    steps_out: list[dict] = []
    completed: set[str] = set()

    print(f"▶ workflow={name} run_id={run_id} steps={len(wf.get('steps', []))}")

    for i, step in enumerate(wf.get("steps", []), 1):
        agent = step["agent"]
        task = step["task"]
        dep = step.get("depends_on")
        optional = step.get("optional", False)

        if dep and dep not in completed:
            # depends_on matches prior task name
            pass  # sequential order already enforces deps

        print(f"  [{i}/{len(wf['steps'])}] {agent} / {task}")
        result = run_agent(agent, task, env)
        steps_out.append(result)
        completed.add(task)

        if not result["success"] and not optional:
            record = {
                "run_id": run_id,
                "type": "workflow",
                "workflow": name,
                "started_at": steps_out[0]["started_at"] if steps_out else utc_now(),
                "finished_at": utc_now(),
                "success": False,
                "failed_step": result,
                "steps": steps_out,
            }
            log_path = log_run(record)
            print(json.dumps({"success": False, "run_id": run_id, "log": str(log_path)}, indent=2))
            return 1

    record = {
        "run_id": run_id,
        "type": "workflow",
        "workflow": name,
        "description": wf.get("description"),
        "started_at": steps_out[0]["started_at"] if steps_out else utc_now(),
        "finished_at": utc_now(),
        "success": True,
        "steps": steps_out,
    }
    log_path = log_run(record)
    print(json.dumps({"success": True, "run_id": run_id, "log": str(log_path), "steps": len(steps_out)}, indent=2))
    return 0


def run_job(job: dict) -> int:
    """Single job file: { "workflow": "..." } or { "agent": "...", "task": "..." }"""
    env = job.get("env", {})
    if "workflow" in job:
        return run_workflow(job["workflow"], env)
    if "agent" in job and "task" in job:
        result = run_agent(job["agent"], job["task"], env)
        record = {"run_id": uuid.uuid4().hex[:12], "type": "single", "success": result["success"], "step": result}
        log_run(record)
        print(json.dumps(record, indent=2))
        return 0 if result["success"] else 1
    print(json.dumps({"success": False, "error": "Job needs workflow or agent+task"}))
    return 1


def watch_queue(poll_sec: float = 2.0) -> int:
    QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    (QUEUE_DIR / "done").mkdir(exist_ok=True)
    (QUEUE_DIR / "failed").mkdir(exist_ok=True)
    print(f"Watching {QUEUE_DIR} (Ctrl+C to stop)")
    while True:
        for path in sorted(QUEUE_DIR.glob("*.json")):
            if path.parent.name != "queue":
                continue
            try:
                job = load_json(path)
                print(f"▶ job {path.name}")
                code = run_job(job)
                dest = QUEUE_DIR / ("done" if code == 0 else "failed") / path.name
                path.rename(dest)
            except Exception as e:
                print(f"✗ {path.name}: {e}")
                path.rename(QUEUE_DIR / "failed" / path.name)
        time.sleep(poll_sec)


def list_workflows() -> None:
    wf = load_json(WORKFLOWS).get("workflows", {})
    for name, spec in wf.items():
        n = len(spec.get("steps", []))
        print(f"{name:24} ({n} steps) — {spec.get('description', '')}")


def main() -> int:
    p = argparse.ArgumentParser(description="HexStrike Orchestrator — agent dispatcher")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("workflows", help="List workflows")

    run_p = sub.add_parser("run", help="Run a workflow")
    run_p.add_argument("workflow")
    run_p.add_argument("--target", help="Set TARGET env for agents")

    disp = sub.add_parser("dispatch", help="Run single agent task")
    disp.add_argument("agent")
    disp.add_argument("task")
    disp.add_argument("--target")

    enq = sub.add_parser("enqueue", help="Copy job JSON into agents/queue/")
    enq.add_argument("job_file")

    sub.add_parser("watch", help="Process agents/queue/*.json")

    st = sub.add_parser("status", help="Show last orchestrator run")
    st.add_argument("--run-id")

    args = p.parse_args()
    env = {}
    if getattr(args, "target", None):
        env["TARGET"] = args.target

    if args.cmd == "workflows":
        list_workflows()
        return 0
    if args.cmd == "run":
        return run_workflow(args.workflow, env or None)
    if args.cmd == "dispatch":
        r = run_agent(args.agent, args.task, env or None)
        log_run({"type": "dispatch", "success": r["success"], "step": r})
        print(json.dumps(r, indent=2))
        return 0 if r["success"] else 1
    if args.cmd == "enqueue":
        src = Path(args.job_file)
        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        dest = QUEUE_DIR / src.name
        dest.write_bytes(src.read_bytes())
        print(json.dumps({"queued": str(dest)}))
        return 0
    if args.cmd == "watch":
        try:
            watch_queue()
        except KeyboardInterrupt:
            return 0
    if args.cmd == "status":
        path = LOG_DIR / (f"{args.run_id}.json" if args.run_id else "latest.json")
        if not path.exists():
            print(json.dumps({"error": "no runs yet"}))
            return 1
        print(path.read_text())
        return 0

    p.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
