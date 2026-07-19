#!/usr/bin/env bash
# ============================================
# HexStrike Forensics Command Kit v1.0
# Defense-only: recon, static analysis, IOC,
# monitoring, disclosure reports.
# NO exploit / drain / frontrun / phishing.
# ============================================
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

TARGET_ENV="${TARGET_ENV:-mainnet}"
RPC_URL="${ETH_RPC_URL:-${ETH_HTTP_URL:-${RPC_URL:-}}}"
OUT_DIR="${FORENSICS_KIT_OUT:-$ROOT/artifacts/forensics-kit}"
LOG_FILE=""
NONINTERACTIVE=0

usage() {
  cat <<EOF
Usage: $0 [options]

Defense-only forensics menu (or one-shot flags).

Options:
  --help, -h           Show help
  --deps               Check dependencies and exit
  --env NAME           mainnet|testnet|local (default: mainnet)
  --rpc URL            Override ETH_RPC_URL
  --recon ADDR         Fetch ABI + bytecode (read-only)
  --permit ADDR        Check EIP-2612 DOMAIN_SEPARATOR (read-only)
  --create2            Run create2-forensics workflow
  --permit-farming     Run permit-farming-forensics workflow
  --dust-once          Run dust→drain detector once
  --slack-once         Forward unread alerts to Slack once
  --three-progons      Run scripts/run-three-progons.sh
  --report             Generate markdown summary from kit log
  --noninteractive     Skip "press Enter" prompts

Env:
  ETH_RPC_URL / ETH_HTTP_URL   JSON-RPC HTTPS
  ETHERSCAN_API_KEY            optional for ABI fetch
  SLACK_WEBHOOK_URL            optional for slack-once
EOF
}

load_env() {
  if [[ -f "$ROOT/scripts/forensics-env-vps.sh" ]] && { [[ -d /opt/drainer-intel ]] || [[ "${HEXSTRIKE_VPS:-}" == "1" ]]; }; then
    # shellcheck source=/dev/null
    source "$ROOT/scripts/forensics-env-vps.sh"
  elif [[ -f "$ROOT/scripts/forensics-env-mac.sh" ]]; then
    # shellcheck source=/dev/null
    source "$ROOT/scripts/forensics-env-mac.sh"
  fi
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck source=/dev/null
    source "$ROOT/.env"
    set +a
  fi
  RPC_URL="${ETH_RPC_URL:-${ETH_HTTP_URL:-${RPC_URL:-}}}"
}

init_out() {
  mkdir -p "$OUT_DIR"
  LOG_FILE="${LOG_FILE:-$OUT_DIR/kit_$(date +%Y%m%d_%H%M%S).log}"
  touch "$LOG_FILE"
}

log_message() {
  echo -e "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

pause() {
  [[ "$NONINTERACTIVE" -eq 1 ]] && return 0
  read -r -p "Нажмите Enter для продолжения..."
}

check_dependencies() {
  log_message "${BLUE}Проверка зависимостей...${NC}"
  local deps=(curl jq python3 git)
  local missing=()
  local opt_ok=()
  for dep in "${deps[@]}"; do
    if ! command -v "$dep" &>/dev/null; then
      missing+=("$dep")
    fi
  done
  for opt in cast forge slither node; do
    if command -v "$opt" &>/dev/null; then
      opt_ok+=("$opt")
    fi
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    log_message "${RED}Отсутствуют обязательные: ${missing[*]}${NC}"
    return 1
  fi
  log_message "${GREEN}OK: ${deps[*]}${NC}"
  log_message "${CYAN}Опционально доступно: ${opt_ok[*]:-none}${NC}"
  if [[ -z "$RPC_URL" ]]; then
    log_message "${YELLOW}ETH_RPC_URL не задан — cast/bytecode шаги будут пропущены${NC}"
  else
    log_message "${GREEN}RPC: ${RPC_URL:0:48}...${NC}"
  fi
  return 0
}

is_address() {
  [[ "${1:-}" =~ ^0x[0-9a-fA-F]{40}$ ]]
}

recon_scan_contracts() {
  local target_address="${1:-}"
  if ! is_address "$target_address"; then
    log_message "${RED}Нужен адрес 0x…40 hex${NC}"
    return 1
  fi
  log_message "${CYAN}[RECON] Контракт $target_address (read-only)${NC}"
  local abi_file="$OUT_DIR/abi_${target_address}.json"
  local code_file="$OUT_DIR/code_${target_address}.hex"

  if [[ -n "${ETHERSCAN_API_KEY:-}" ]]; then
    curl -fsS "https://api.etherscan.io/api?module=contract&action=getabi&address=${target_address}&apikey=${ETHERSCAN_API_KEY}" \
      | jq -r '.result' >"$abi_file" || true
    if [[ -s "$abi_file" ]] && [[ "$(head -c 1 "$abi_file")" == "[" ]]; then
      log_message "${GREEN}ABI → $abi_file${NC}"
    else
      log_message "${YELLOW}ABI не получен / unverified${NC}"
    fi
  else
    log_message "${YELLOW}ETHERSCAN_API_KEY пуст — пропускаем ABI API${NC}"
  fi

  if [[ -n "$RPC_URL" ]] && command -v cast &>/dev/null; then
    cast code "$target_address" --rpc-url "$RPC_URL" >"$code_file" || true
    local size
    size=$(wc -c <"$code_file" | tr -d ' ')
    log_message "${GREEN}bytecode bytes≈$size → $code_file${NC}"
    # EIP-7702 delegation marker 0xef0100
    if grep -qi '^0xef0100' "$code_file" 2>/dev/null; then
      log_message "${YELLOW}Возможная EIP-7702 delegation (0xef0100)${NC}"
    fi
  else
    log_message "${YELLOW}cast/RPC недоступны — bytecode пропущен${NC}"
  fi
}

check_permit_support() {
  local token_address="${1:-}"
  if ! is_address "$token_address"; then
    log_message "${RED}Нужен адрес токена 0x…${NC}"
    return 1
  fi
  log_message "${CYAN}[ANALYZE] EIP-2612 support check (read-only) $token_address${NC}"
  if [[ -z "$RPC_URL" ]] || ! command -v cast &>/dev/null; then
    log_message "${RED}Нужны cast + ETH_RPC_URL${NC}"
    return 1
  fi
  # DOMAIN_SEPARATOR() selector 0x3644e515
  local out
  if out=$(cast call "$token_address" "DOMAIN_SEPARATOR()(bytes32)" --rpc-url "$RPC_URL" 2>/dev/null); then
    log_message "${GREEN}Поддерживает DOMAIN_SEPARATOR → вероятно EIP-2612${NC}"
    log_message "DOMAIN_SEPARATOR=$out"
    echo "{\"address\":\"$token_address\",\"eip2612_likely\":true,\"domain_separator\":\"$out\"}" \
      >"$OUT_DIR/permit_check_${token_address}.json"
  else
    log_message "${YELLOW}DOMAIN_SEPARATOR() недоступен — permit, скорее всего, нет${NC}"
    echo "{\"address\":\"$token_address\",\"eip2612_likely\":false}" \
      >"$OUT_DIR/permit_check_${token_address}.json"
  fi
}

run_slither_if_path() {
  local path="${1:-}"
  if [[ -z "$path" ]]; then
    log_message "${YELLOW}Укажите путь к .sol / найденному репо${NC}"
    return 1
  fi
  if ! command -v slither &>/dev/null; then
    log_message "${YELLOW}slither не установлен — skip${NC}"
    return 0
  fi
  log_message "${CYAN}[ANALYZE] Slither $path${NC}"
  slither "$path" --exclude-informational 2>&1 | tee -a "$LOG_FILE" | tee "$OUT_DIR/slither_$(date +%H%M%S).txt" || true
}

run_workflow() {
  local wf="$1"
  log_message "${CYAN}[FORENSICS] workflow $wf${NC}"
  python3 "$ROOT/scripts/hexstrike-orchestrator.py" run "$wf" --quiet 2>&1 | tee -a "$LOG_FILE"
}

run_dust_once() {
  log_message "${CYAN}[MONITOR] dust→drain detector --once${NC}"
  if [[ -z "$RPC_URL" ]]; then
    log_message "${RED}ETH_RPC_URL required${NC}"
    return 1
  fi
  python3 "$ROOT/scripts/detect_eip7702_dust_drain.py" --once 2>&1 | tee -a "$LOG_FILE"
}

run_slack_once() {
  log_message "${CYAN}[MONITOR] slack_forwarder --once${NC}"
  python3 "$ROOT/scripts/slack_forwarder.py" --once 2>&1 | tee -a "$LOG_FILE"
}

run_three() {
  log_message "${CYAN}[FORENSICS] three progons${NC}"
  bash "$ROOT/scripts/run-three-progons.sh" 2>&1 | tee -a "$LOG_FILE"
}

generate_report() {
  local report_file="$OUT_DIR/report_$(date +%Y%m%d_%H%M%S).md"
  cat >"$report_file" <<EOF
# HexStrike Forensics Kit Report
**Date:** $(date -u +%Y-%m-%dT%H:%M:%SZ)
**Env:** $TARGET_ENV
**Mode:** defense-only (recon / detect / disclose)

## Summary lines
\`\`\`
$(grep -iE 'OK|FAIL|EIP|DOMAIN|delegation|sent|victim|ERROR|WARN' "$LOG_FILE" 2>/dev/null | tail -40 || echo "(no log hits)")
\`\`\`

## Kit artifacts
\`\`\`
$(ls -la "$OUT_DIR" 2>/dev/null | tail -30)
\`\`\`

## Remediation checklist
1. Revoke unexpected ERC-20 allowances / EIP-2612 permits
2. Check EIP-7702 code (\`0xef0100\`) on EOAs; revoke with zero delegation if compromised
3. Enable dust→drain monitor + Slack/Telegram alerts
4. Disclose IOCs via \`artifacts/forensics/\` packs — no mixer / cash-out guidance

## Log
\`$LOG_FILE\`
EOF
  log_message "${GREEN}Отчёт → $report_file${NC}"
}

show_menu() {
  clear 2>/dev/null || true
  echo -e "${CYAN}╔════════════════════════════════════════════╗${NC}"
  echo -e "${CYAN}║   HexStrike Forensics Command Kit v1.0     ║${NC}"
  echo -e "${CYAN}║   Defense / IR / Disclosure only           ║${NC}"
  echo -e "${CYAN}╚════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "${GREEN}[1]${NC} Проверка зависимостей"
  echo -e "${GREEN}[2]${NC} Разведка (ABI + bytecode + 7702 marker)"
  echo -e "${GREEN}[3]${NC} Анализ (permit support / Slither / workflows)"
  echo -e "${GREEN}[4]${NC} Три прогона + модули forensics"
  echo -e "${GREEN}[5]${NC} Мониторинг (dust→drain / Slack)"
  echo -e "${GREEN}[6]${NC} Генерация отчёта"
  echo -e "${GREEN}[7]${NC} Выход"
  echo ""
  echo -e "RPC: ${RPC_URL:-unset} | out: $OUT_DIR"
  echo -e "${YELLOW}Выберите опцию: ${NC}"
}

analysis_menu() {
  echo -e "${YELLOW}Анализ:${NC}"
  echo "1) EIP-2612 DOMAIN_SEPARATOR (read-only)"
  echo "2) Slither по локальному пути"
  echo "3) Workflow permit-farming-forensics"
  echo "4) Workflow create2-forensics"
  echo "5) Назад"
  read -r analysis_choice
  case $analysis_choice in
    1)
      read -r -p "Адрес токена: " token_address
      check_permit_support "$token_address"
      ;;
    2)
      read -r -p "Путь к .sol / проекту: " sol_path
      run_slither_if_path "$sol_path"
      ;;
    3) run_workflow permit-farming-forensics ;;
    4) run_workflow create2-forensics ;;
    *) ;;
  esac
}

monitor_menu() {
  echo -e "${YELLOW}Мониторинг:${NC}"
  echo "1) dust→drain detector --once"
  echo "2) slack_forwarder --once"
  echo "3) tail dust-drain-alerts.jsonl"
  echo "4) Назад"
  read -r m
  case $m in
    1) run_dust_once ;;
    2) run_slack_once ;;
    3)
      local alerts="$ROOT/artifacts/monitor/dust-drain-alerts.jsonl"
      if [[ -f "$alerts" ]]; then
        tail -n 20 "$alerts" | tee -a "$LOG_FILE"
      else
        log_message "${YELLOW}Нет $alerts${NC}"
      fi
      ;;
    *) ;;
  esac
}

progons_menu() {
  echo -e "${YELLOW}Forensics runs:${NC}"
  echo "1) run-three-progons.sh"
  echo "2) operator-lab"
  echo "3) field-targets-5"
  echo "4) run-all-forensics.sh"
  echo "5) Назад"
  read -r p
  case $p in
    1) run_three ;;
    2) run_workflow operator-lab ;;
    3) run_workflow field-targets-5 ;;
    4) bash "$ROOT/scripts/run-all-forensics.sh" 2>&1 | tee -a "$LOG_FILE" ;;
    *) ;;
  esac
}

main_menu() {
  while true; do
    show_menu
    read -r choice
    case $choice in
      1) check_dependencies; pause ;;
      2)
        read -r -p "Адрес контракта/EOA: " contract_address
        recon_scan_contracts "$contract_address"
        pause
        ;;
      3) analysis_menu; pause ;;
      4) progons_menu; pause ;;
      5) monitor_menu; pause ;;
      6) generate_report; pause ;;
      7)
        log_message "${BLUE}Выход. Лог: $LOG_FILE${NC}"
        exit 0
        ;;
      *)
        echo -e "${RED}Неверный выбор${NC}"
        sleep 1
        ;;
    esac
  done
}

# ---- entry ----
load_env
init_out

if [[ $# -eq 0 ]]; then
  echo "=== HexStrike Forensics Command Kit ===" >"$LOG_FILE"
  echo "start: $(date -u -Iseconds) user=$(whoami) host=$(hostname)" >>"$LOG_FILE"
  main_menu
  exit 0
fi

while [[ $# -gt 0 ]]; do
  case $1 in
    --help|-h) usage; exit 0 ;;
    --noninteractive) NONINTERACTIVE=1; shift ;;
    --env) TARGET_ENV="$2"; shift 2 ;;
    --rpc) RPC_URL="$2"; export ETH_RPC_URL="$2"; shift 2 ;;
    --deps) check_dependencies; exit $? ;;
    --recon)
      recon_scan_contracts "$2"
      exit $?
      ;;
    --permit)
      check_permit_support "$2"
      exit $?
      ;;
    --create2)
      run_workflow create2-forensics
      exit $?
      ;;
    --permit-farming)
      run_workflow permit-farming-forensics
      exit $?
      ;;
    --dust-once)
      run_dust_once
      exit $?
      ;;
    --slack-once)
      run_slack_once
      exit $?
      ;;
    --three-progons)
      run_three
      exit $?
      ;;
    --report)
      generate_report
      exit 0
      ;;
    *)
      echo "Unknown: $1"
      usage
      exit 1
      ;;
  esac
done
