#!/usr/bin/env bash
# Connect DeepSeek R1 (OpenRouter / DeepSeek API) — standalone, no IDE coupling.
#
# Usage:
#   export R1_API_KEY=sk-...
#   bash scripts/connect-r1.sh
#   bash scripts/connect-r1.sh --status
#   bash scripts/connect-r1.sh --handshake
#   bash scripts/connect-r1.sh --plan config/reasoning-protocol.example.json
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="${ROOT}/src${PYTHONPATH:+:$PYTHONPATH}"

MODE="connect"
PLAN_FILE=""
for arg in "$@"; do
  case "$arg" in
    --status) MODE="status" ;;
    --handshake) MODE="handshake" ;;
    --plan=*) PLAN_FILE="${arg#--plan=}" ;;
    --plan) ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
  esac
done

prev=""
for arg in "$@"; do
  if [[ "$prev" == "--plan" ]]; then
    PLAN_FILE="$arg"
  fi
  prev="$arg"
done

python3 - <<PY
import json
import sys
from pathlib import Path

sys.path.insert(0, "${ROOT}/src")
from hexstrike.llm.cloud_r1 import CloudR1Provider, resolve_cloud_r1_config
from hexstrike.llm.reasoning import ReasoningAgent

root = Path("${ROOT}")
env_path = root / ".env"
mode = "${MODE}"
plan_file = "${PLAN_FILE}"

cfg = resolve_cloud_r1_config()
print(f"[r1] provider={cfg.provider} base={cfg.base_url} model={cfg.model}")
print(f"[r1] authenticated={bool(cfg.api_key)}")

if mode == "status":
    st = CloudR1Provider(cfg).status()
    print(json.dumps(st, indent=2))
    sys.exit(0 if st.get("authenticated") else 1)

if mode == "handshake":
    report = CloudR1Provider(cfg).handshake()
    print(json.dumps(report, indent=2))
    ok = report.get("r1", {}).get("authenticated") and report.get("ping", {}).get("ok")
    sys.exit(0 if ok else 1)

if mode == "connect" and plan_file:
    agent = ReasoningAgent(CloudR1Provider(cfg))
    result = agent.plan_from_file(plan_file)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result.get("ok") else 1)

if not env_path.is_file() and (root / ".env.example").is_file():
    env_path.write_text((root / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
    print(f"[r1] seeded {env_path} from .env.example")

updates = {
    "R1_PROVIDER": cfg.provider,
    "R1_BASE_URL": cfg.base_url,
    "R1_MODEL": cfg.model,
    "R1_TIMEOUT_SEC": str(int(cfg.timeout_sec)),
}
if cfg.api_key:
    updates["R1_API_KEY"] = cfg.api_key

lines: list[str] = []
if env_path.is_file():
    lines = env_path.read_text(encoding="utf-8").splitlines()

keys_seen: set[str] = set()
out: list[str] = []
for line in lines:
    if "=" in line and not line.strip().startswith("#"):
        k = line.split("=", 1)[0].strip()
        if k in updates:
            out.append(f"{k}={updates[k]}")
            keys_seen.add(k)
            continue
    out.append(line)
for k, v in updates.items():
    if k not in keys_seen:
        out.append(f"{k}={v}")
env_path.write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"[r1] wrote R1_* block -> {env_path}")

report = CloudR1Provider(resolve_cloud_r1_config()).handshake()
print(json.dumps(report, indent=2))
ok = report.get("r1", {}).get("authenticated")
sys.exit(0 if ok else 1)
PY
