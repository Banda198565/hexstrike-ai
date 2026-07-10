#!/usr/bin/env bash
# Show HexStrike server and MCP-related status.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=hexstrike-common.sh
source "${SCRIPT_DIR}/hexstrike-common.sh"

echo "=== HexStrike Status ==="
echo "Project:  ${HEXSTRIKE_ROOT}"
echo "Port:     ${HEXSTRIKE_PORT}"
echo "Log:      ${LOG_FILE}"
echo "PID file: ${PID_FILE}"

if _eva_symlink_requires_mount; then
  if [[ -d "${EVA_MOUNT}" && -r "${EVA_MOUNT}" ]]; then
    echo "Eva:      mounted (${EVA_MOUNT})"
  else
    echo "Eva:      NOT MOUNTED (required by ${HEXSTRIKE_ROOT}/hexstrike-ai symlink)"
  fi
else
  echo "Eva:      not required"
fi

pid="$(read_pid_file)"
port_pid="$(find_server_pid_by_port)"

if [[ -n "${pid}" ]]; then
  if [[ -n "${port_pid}" && "${pid}" == "${port_pid}" ]]; then
    echo "PID file: ${pid} (running)"
  elif is_pid_running "${pid}"; then
    echo "PID file: ${pid} (running)"
  else
    echo "PID file: ${pid} (stale)"
  fi
else
  echo "PID file: absent"
fi

if [[ -n "${port_pid}" ]]; then
  echo "Port ${HEXSTRIKE_PORT}: listener PID ${port_pid}"
else
  echo "Port ${HEXSTRIKE_PORT}: not listening"
fi

if server_health_ok; then
  echo "Health:   OK (http://127.0.0.1:${HEXSTRIKE_PORT}/health)"
  if curl -fsS --max-time 5 "http://127.0.0.1:${HEXSTRIKE_PORT}/health" 2>/dev/null; then
    echo
  else
    "$(resolve_python)" -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:${HEXSTRIKE_PORT}/health', timeout=5).read().decode()[:200])" 2>/dev/null || true
    echo
  fi
else
  echo "Health:   FAILED"
fi

if [[ -n "${port_pid}" && ! -f "${PID_FILE}" ]]; then
  echo "${port_pid}" > "${PID_FILE}"
fi

if [[ -f "${HOME}/.cursor/mcp.json" ]]; then
  echo
  echo "MCP (~/.cursor/mcp.json) server URL:"
  grep -E '127\.0\.0\.1:8888|localhost:8888' "${HOME}/.cursor/mcp.json" || echo "  (port 8888 not found — run hexstrike-restore.sh)"
fi

if [[ -f "${HOME}/.cursor/mcp-hub.json" ]]; then
  echo "MCP (~/.cursor/mcp-hub.json) server URL:"
  grep -E '127\.0\.0\.1:8888|localhost:8888' "${HOME}/.cursor/mcp-hub.json" || echo "  (port 8888 not found — run hexstrike-restore.sh)"
fi
