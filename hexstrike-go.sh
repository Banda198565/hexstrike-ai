#!/usr/bin/env bash
# hexstrike-go.sh — ОДНА команда: setup + меню (протестировано)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

MODEL="${HEXSTRIKE_OLLAMA_MODEL:-hexstrike-orchestrator}"
HOST="${OLLAMA_HOST:-http://127.0.0.1:11434}"
FASTFILE="/tmp/hexstrike-fast.modelfile"

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
ylw()  { printf '\033[33m%s\033[0m\n' "$*"; }

die() { red "[FAIL] $*"; exit 1; }

check_ollama() {
  command -v ollama >/dev/null || die "Установи: brew install ollama"
  if ! curl -sf --max-time 5 "${HOST}/api/tags" >/dev/null; then
    ylw "Запускаю Ollama.app..."
    open -a Ollama 2>/dev/null || true
    for i in 1 2 3 4 5 6; do
      sleep 3
      curl -sf --max-time 3 "${HOST}/api/tags" >/dev/null && return 0
    done
    die "Ollama не отвечает. Открой Ollama.app вручную."
  fi
}

ensure_models() {
  ollama list 2>/dev/null | grep -q 'deepseek-r1:1.5b' || ollama pull deepseek-r1:1.5b
  cat > "$FASTFILE" << 'EOF'
FROM deepseek-r1:1.5b
PARAMETER num_predict 64
PARAMETER num_thread 8
PARAMETER temperature 0.2
SYSTEM "Ты HexStrike Orchestrator. Кратко по-русски. Агенты: OSINT-03, Web-04, Vuln-05, Report-06. Команды: /run defensive-disclosure, /run vps-full-readonly, /dispatch Agent-Vuln-05 passive-cve-check. Read-only, без эксплойтов."
EOF
  ollama create "${MODEL}" -f "$FASTFILE" >/dev/null 2>&1 || ollama create "${MODEL}" -f "$FASTFILE"
}

preflight_agents() {
  grn "[test] orchestrator dispatch..."
  if ./hexstrike-orchestrator dispatch Agent-Vuln-05 passive-cve-check >/tmp/hexstrike-preflight.log 2>&1; then
    grn "[OK]   агенты работают → artifacts/jenkins-cve-report.json"
  else
    red "[WARN] агент упал — см. /tmp/hexstrike-preflight.log"
  fi
}

menu() {
  echo ""
  echo "╔════════════════════════════════════════╗"
  echo "║         HexStrike — готово к работе    ║"
  echo "╚════════════════════════════════════════╝"
  echo ""
  echo "  1) Чат DeepSeek + HexStrike (терминал)"
  echo "  2) Запустить defensive-disclosure (CVE+checklist)"
  echo "  3) Запустить vps-full-readonly (полный recon)"
  echo "  4) Только ollama run (простой чат)"
  echo "  5) Выход"
  echo ""
  read -r -p "Выбор [1]: " choice
  choice="${choice:-1}"
  case "$choice" in
    1) export OLLAMA_NUM_PREDICT=64 OLLAMA_NUM_THREAD=8; exec python3 "$ROOT/scripts/hexstrike-terminal.py" ;;
    2) ./hexstrike-orchestrator run defensive-disclosure ;;
    3) ./hexstrike-orchestrator run vps-full-readonly ;;
    4) exec ollama run "${MODEL}" ;;
    5) exit 0 ;;
    *) menu ;;
  esac
}

check_ollama
ensure_models
chmod +x "$ROOT/scripts/hexstrike-terminal.py" "$ROOT/hexstrike-orchestrator" 2>/dev/null || true
preflight_agents
menu
