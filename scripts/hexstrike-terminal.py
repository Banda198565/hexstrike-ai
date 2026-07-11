#!/usr/bin/env python3
"""HexStrike local terminal — chat + real agent dispatch (no Cursor)."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REGISTRY = ROOT / "agents/registry.json"
WORKFLOWS = ROOT / "agents/workflows.json"
ORCHESTRATOR = ROOT / "scripts/hexstrike-orchestrator.py"
MODELFILE = ROOT / "config/hexstrike-orchestrator.modelfile"
OLLAMA_MODEL = os.environ.get("HEXSTRIKE_OLLAMA_MODEL", "hexstrike-orchestrator")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_system_prompt() -> str:
    reg = load_json(REGISTRY)
    wf = load_json(WORKFLOWS)
    lines = [
        "Ты HexStrike Orchestrator в терминале Mac.",
        "Агенты и задачи:",
    ]
    for name, cfg in reg.get("agents", {}).items():
        tasks = cfg.get("tasks", {})
        if isinstance(tasks, dict) and tasks:
            task_list = ", ".join(tasks.keys())
            lines.append(f"- {name}: {task_list}")
    lines.append("Workflows:")
    for wname, wcfg in wf.get("workflows", {}).items():
        lines.append(f"- {wname}: {wcfg.get('description', '')}")
    lines.extend(
        [
            "",
            "Служебные команды (выполняются локально):",
            "/help /agents /workflows /run <workflow> /dispatch <Agent> <task> /status /exit",
            "Отвечай по-русски, кратко. Не выдумывай артефакты.",
        ]
    )
    return "\n".join(lines)


def ollama_chat(messages: list[dict], model: str = OLLAMA_MODEL) -> str:
    url = f"{OLLAMA_HOST}/v1/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "num_thread": int(os.environ.get("OLLAMA_NUM_THREAD", "16")),
                "num_predict": int(os.environ.get("OLLAMA_NUM_PREDICT", "512")),
            },
        }
    ).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"].strip()


def run_orchestrator(args: list[str]) -> tuple[int, str]:
    cmd = [sys.executable, str(ORCHESTRATOR), *args]
    proc = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, text=True)
    out = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, out[-4000:]


def cmd_help() -> str:
    return """
Команды HexStrike Terminal:
  /help                         — эта справка
  /agents                       — список агентов
  /workflows                    — список workflow
  /run <workflow>               — запустить pipeline (реально)
  /dispatch <Agent-ID> <task>   — один агент (реально)
  /status                       — статус оркестратора
  /exit                         — выход

Примеры:
  /run defensive-disclosure
  /dispatch Agent-Vuln-05 passive-cve-check
  /run vps-full-readonly

Обычный текст — чат с локальной моделью (знает агентов).
""".strip()


def cmd_agents() -> str:
    reg = load_json(REGISTRY)
    lines = ["Зарегистрированные агенты:"]
    for name, cfg in reg.get("agents", {}).items():
        tasks = cfg.get("tasks", {})
        if isinstance(tasks, dict):
            lines.append(f"  {name}: {', '.join(tasks.keys()) or '(orchestrator)'}")
    return "\n".join(lines)


def cmd_workflows() -> str:
    code, out = run_orchestrator(["workflows"])
    return out if code == 0 else f"Ошибка workflows: {out}"


def handle_slash(line: str) -> tuple[bool, str]:
    parts = line.strip().split()
    if not parts:
        return True, ""
    cmd = parts[0].lower()

    if cmd in ("/exit", "/quit", "/bye"):
        raise SystemExit(0)
    if cmd == "/help":
        return True, cmd_help()
    if cmd == "/agents":
        return True, cmd_agents()
    if cmd == "/workflows":
        return True, cmd_workflows()
    if cmd == "/status":
        code, out = run_orchestrator(["status"])
        if code != 0:
            proc = subprocess.run(
                [sys.executable, str(ROOT / "hexstrike_orchestrator.py"), "status"],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
            )
            out = proc.stdout or proc.stderr
        return True, out
    if cmd == "/run" and len(parts) >= 2:
        wf = parts[1]
        print(f"\n[hexstrike] запуск workflow: {wf} ...\n")
        code, out = run_orchestrator(["run", wf])
        return True, f"exit={code}\n{out}"
    if cmd == "/dispatch" and len(parts) >= 3:
        agent, task = parts[1], parts[2]
        print(f"\n[hexstrike] dispatch {agent} / {task} ...\n")
        code, out = run_orchestrator(["dispatch", agent, task])
        return True, f"exit={code}\n{out}"

    return False, ""


def ensure_ollama_model() -> None:
    tags_url = f"{OLLAMA_HOST}/api/tags"
    try:
        with urllib.request.urlopen(tags_url, timeout=5) as resp:
            tags = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        print(f"[FAIL] Ollama недоступен на {OLLAMA_HOST}: {exc}")
        print("Запусти: ollama serve  или открой Ollama.app")
        raise SystemExit(1)

    names = [m.get("name", "") for m in tags.get("models", [])]
    has_custom = any(n.startswith(OLLAMA_MODEL) for n in names)
    if has_custom:
        return

    if not MODELFILE.is_file():
        print(f"[WARN] Modelfile не найден: {MODELFILE}")
        print(f"Буду использовать deepseek-r1:1.5b")
        return

    print(f"[setup] Создаю модель {OLLAMA_MODEL} ...")
    proc = subprocess.run(
        ["ollama", "create", OLLAMA_MODEL, "-f", str(MODELFILE)],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(proc.stderr or proc.stdout)
        print(f"[WARN] Не удалось создать {OLLAMA_MODEL}, fallback deepseek-r1:1.5b")


def main() -> int:
    ensure_ollama_model()
    model = OLLAMA_MODEL
    tags = json.loads(urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=5).read().decode())
    names = [m.get("name", "") for m in tags.get("models", [])]
    if not any(n.startswith(model) for n in names):
        model = "deepseek-r1:1.5b"

    messages: list[dict] = [{"role": "system", "content": build_system_prompt()}]

    print("╔══════════════════════════════════════════════════╗")
    print("║  HexStrike Terminal — локальный оркестратор      ║")
    print("╚══════════════════════════════════════════════════╝")
    print(f"Ollama: {OLLAMA_HOST} | model: {model}")
    print("Введи /help для команд. /run и /dispatch запускают агентов по-настоящему.\n")

    while True:
        try:
            user = input("hexstrike> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nbye")
            return 0

        if not user:
            continue

        if user.startswith("/"):
            try:
                handled, reply = handle_slash(user)
            except SystemExit:
                print("bye")
                return 0
            if handled:
                if reply:
                    print(reply)
                continue

        # Natural language → suggest slash if obvious
        low = user.lower()
        m_run = re.search(r"(?:запусти|run)\s+(?:workflow\s+)?([\w-]+)", low)
        m_disp = re.search(r"(?:dispatch|агент)\s+(agent[\w-]+)\s+([\w-]+)", low, re.I)

        messages.append({"role": "user", "content": user})
        try:
            reply = ollama_chat(messages, model=model)
        except Exception as exc:
            print(f"[FAIL] Ollama: {exc}")
            messages.pop()
            continue

        messages.append({"role": "assistant", "content": reply})
        print(f"\n{reply}\n")

        if m_run:
            wf = m_run.group(1)
            print(f"[подсказка] Реальный запуск: /run {wf}\n")
        if m_disp:
            print(f"[подсказка] Реальный запуск: /dispatch {m_disp.group(1)} {m_disp.group(2)}\n")


if __name__ == "__main__":
    raise SystemExit(main())
