#!/usr/bin/env bash
# Stop HexStrike API server.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=hexstrike-common.sh
source "${SCRIPT_DIR}/hexstrike-common.sh"

stopped=0

stop_pid() {
  local pid="$1"
  if ! is_pid_running "${pid}"; then
    return 1
  fi
  echo "Stopping HexStrike server (PID ${pid})..."
  kill "${pid}" 2>/dev/null || true

  for _ in $(seq 1 15); do
    if ! is_pid_running "${pid}"; then
      return 0
    fi
    sleep 1
  done

  echo "Force stopping PID ${pid}..."
  kill -9 "${pid}" 2>/dev/null || true
}

pid="$(read_pid_file)"
if [[ -n "${pid}" ]] && stop_pid "${pid}"; then
  stopped=1
fi

port_pid="$(find_server_pid_by_port)"
if [[ -n "${port_pid}" && "${port_pid}" != "${pid:-}" ]]; then
  stop_pid "${port_pid}"
  stopped=1
fi

rm -f "${PID_FILE}"

if [[ "${stopped}" -eq 1 ]]; then
  echo "HexStrike server stopped."
else
  echo "HexStrike server is not running."
fi
