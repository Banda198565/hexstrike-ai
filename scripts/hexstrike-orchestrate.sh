#!/usr/bin/env bash
# HexStrike orchestration helper for Cursor Agent (trial period).
# Usage:
#   hexstrike-orchestrate.sh health
#   hexstrike-orchestrate.sh status
#   hexstrike-orchestrate.sh select-tools <target> [objective]
#   hexstrike-orchestrate.sh smart-scan <target> [objective] [max_tools]
#   hexstrike-orchestrate.sh report

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=hexstrike-common.sh
source "${SCRIPT_DIR}/hexstrike-common.sh"

ORCH_LOG="${LOG_DIR}/orchestration.log"
METRICS_FILE="${HEXSTRIKE_ROOT}/orchestration/metrics.json"
BASE_URL="http://127.0.0.1:${HEXSTRIKE_PORT}"
CONFIG_FILE="${HEXSTRIKE_ROOT}/orchestration/trial-config.yaml"

ensure_log_dir
mkdir -p "$(dirname "${METRICS_FILE}")"
touch "${ORCH_LOG}"

_log() {
  local action="$1"
  local target="${2:-}"
  local decision="$3"
  local result="$4"
  local ts
  ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  echo "[${ts}] ACTION=${action} TARGET=${target} DECISION=${decision} RESULT=${result}" >> "${ORCH_LOG}"
}

_init_metrics() {
  if [[ ! -f "${METRICS_FILE}" ]]; then
    cat > "${METRICS_FILE}" <<'EOF'
{
  "health_checks_total": 0,
  "health_checks_failed": 0,
  "workflows_run": 0,
  "tools_selected": 0,
  "smart_scans_executed": 0,
  "fallback_chains_used": 0,
  "recovery_actions": 0,
  "success_rate": 1.0,
  "last_updated": null
}
EOF
  fi
}

_bump_metric() {
  local key="$1"
  local delta="${2:-1}"
  _init_metrics
  local python
  python="$(resolve_python)"
  "${python}" - <<PY
import json
from datetime import datetime, timezone
from pathlib import Path

path = Path("${METRICS_FILE}")
data = json.loads(path.read_text())
data["${key}"] = data.get("${key}", 0) + ${delta}
total = data.get("workflows_run", 0) + data.get("smart_scans_executed", 0)
failed = data.get("health_checks_failed", 0) + data.get("fallback_chains_used", 0)
checks = max(data.get("health_checks_total", 0), 1)
if total > 0:
    data["success_rate"] = round(max(0.0, 1.0 - (failed / max(total, 1))), 3)
else:
    data["success_rate"] = round(max(0.0, 1.0 - (failed / checks)), 3)
data["last_updated"] = datetime.now(timezone.utc).isoformat()
path.write_text(json.dumps(data, indent=2) + "\n")
PY
}

_api_post() {
  local endpoint="$1"
  local json_payload="$2"
  curl -fsS --max-time 120 \
    -H "Content-Type: application/json" \
    -X POST \
    -d "${json_payload}" \
    "${BASE_URL}${endpoint}"
}

cmd_health() {
  _bump_metric health_checks_total
  echo "=== HexStrike Orchestration Health ==="
  if server_health_ok; then
    local body
    body="$(_api_post "/health" '{}' 2>/dev/null || curl -fsS --max-time 10 "${BASE_URL}/health")"
    echo "Health: OK"
    echo "${body}"
    _log health "" "server_health_ok" "OK"
    return 0
  fi

  echo "Health: FAILED — attempting restore..."
  _bump_metric health_checks_failed
  _log health "" "server_health_failed" "FAILED"

  if [[ -x "${SCRIPT_DIR}/hexstrike-restore.sh" ]]; then
    _bump_metric recovery_actions
    "${SCRIPT_DIR}/hexstrike-restore.sh" || true
    sleep 3
    if server_health_ok; then
      echo "Health: RECOVERED after restore"
      _log health "" "hexstrike_restore" "RECOVERED"
      return 0
    fi
  fi

  echo "Health: STILL FAILED — manual intervention required"
  _log health "" "restore_exhausted" "STILL_FAILED"
  return 1
}

cmd_status() {
  echo "=== HexStrike Orchestration Status ==="
  echo "Config:   ${CONFIG_FILE}"
  echo "Log:      ${ORCH_LOG}"
  echo "Metrics:  ${METRICS_FILE}"
  echo "API:      ${BASE_URL}"
  echo
  "${SCRIPT_DIR}/hexstrike-status.sh"
  echo
  if [[ -f "${METRICS_FILE}" ]]; then
    echo "=== Orchestration Metrics ==="
    cat "${METRICS_FILE}"
  fi
}

cmd_select_tools() {
  local target="${1:?Usage: select-tools <target> [objective]}"
  local objective="${2:-comprehensive}"
  local payload
  payload="$(printf '{"target":"%s","objective":"%s"}' "${target}" "${objective}")"

  cmd_health || return 1

  echo "=== Select Tools: ${target} (${objective}) ==="
  local result
  if result="$(_api_post "/api/intelligence/select-tools" "${payload}")"; then
    echo "${result}" | python3 -m json.tool 2>/dev/null || echo "${result}"
    _bump_metric tools_selected
    _bump_metric workflows_run
    _log select-tools "${target}" "objective=${objective}" "OK"
  else
    _log select-tools "${target}" "objective=${objective}" "FAILED"
    return 1
  fi
}

cmd_smart_scan() {
  local target="${1:?Usage: smart-scan <target> [objective] [max_tools]}"
  local objective="${2:-comprehensive}"
  local max_tools="${3:-5}"
  local payload
  payload="$(printf '{"target":"%s","objective":"%s","max_tools":%s}' "${target}" "${objective}" "${max_tools}")"

  cmd_health || return 1

  echo "=== Smart Scan: ${target} (${objective}, max_tools=${max_tools}) ==="
  echo "Calling ${BASE_URL}/api/intelligence/smart-scan ..."
  local result
  if result="$(_api_post "/api/intelligence/smart-scan" "${payload}")"; then
    echo "${result}" | python3 -m json.tool 2>/dev/null || echo "${result}"
    _bump_metric smart_scans_executed
    _bump_metric workflows_run
    _log smart-scan "${target}" "objective=${objective},max_tools=${max_tools}" "OK"
  else
    _bump_metric fallback_chains_used
    _log smart-scan "${target}" "objective=${objective}" "FAILED"
    echo "Smart scan failed — agent should apply GracefulDegradation fallback chains"
    return 1
  fi
}

cmd_report() {
  cmd_status
  echo
  echo "=== Recent Orchestration Log (last 20 lines) ==="
  tail -20 "${ORCH_LOG}" 2>/dev/null || echo "(empty)"
  echo
  if [[ -f "${CONFIG_FILE}" ]]; then
    echo "=== Trial Config Summary ==="
    grep -E '^(  )?(start_date|end_date|duration_days|status):' "${CONFIG_FILE}" || true
  fi
}

usage() {
  cat <<EOF
HexStrike Orchestration Helper (trial)

Usage:
  $(basename "$0") health
  $(basename "$0") status
  $(basename "$0") select-tools <target> [objective]
  $(basename "$0") smart-scan <target> [objective] [max_tools]
  $(basename "$0") report
EOF
}

main() {
  local cmd="${1:-report}"
  shift || true

  case "${cmd}" in
    health) cmd_health ;;
    status) cmd_status ;;
    select-tools) cmd_select_tools "$@" ;;
    smart-scan) cmd_smart_scan "$@" ;;
    report) cmd_report ;;
    -h|--help|help) usage ;;
    *)
      echo "Unknown command: ${cmd}" >&2
      usage
      exit 1
      ;;
  esac
}

main "$@"
