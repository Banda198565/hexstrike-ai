#!/usr/bin/env bash
# Start HexStrike API server on port 8888 (idempotent).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=hexstrike-common.sh
source "${SCRIPT_DIR}/hexstrike-common.sh"

ensure_log_dir
ensure_eva_available

python="$(resolve_python)"

existing_pid="$(read_pid_file)"
if is_pid_running "${existing_pid}"; then
  if server_health_ok; then
    echo "HexStrike server already running (PID ${existing_pid}, port ${HEXSTRIKE_PORT})."
    exit 0
  fi
  echo "Stale PID file detected (PID ${existing_pid}); cleaning up." >&2
  rm -f "${PID_FILE}"
fi

port_pid="$(find_server_pid_by_port)"
if [[ -n "${port_pid}" ]]; then
  if server_health_ok; then
    echo "${port_pid}" > "${PID_FILE}"
    echo "HexStrike server already listening on port ${HEXSTRIKE_PORT} (PID ${port_pid})."
    exit 0
  fi
  if is_hexstrike_server_pid "${port_pid}"; then
    echo "${port_pid}" > "${PID_FILE}"
    echo "HexStrike server already listening on port ${HEXSTRIKE_PORT} (PID ${port_pid}); health check slow, assuming OK."
    exit 0
  fi
  echo "ERROR: Port ${HEXSTRIKE_PORT} is in use by PID ${port_pid}, but it is not HexStrike." >&2
  exit 1
fi

if [[ ! -f "${SERVER_SCRIPT}" ]]; then
  echo "ERROR: Server script not found: ${SERVER_SCRIPT}" >&2
  exit 1
fi

echo "Starting HexStrike server on port ${HEXSTRIKE_PORT}..."
nohup "${python}" "${SERVER_SCRIPT}" --port "${HEXSTRIKE_PORT}" >> "${LOG_FILE}" 2>&1 &
new_pid=$!
echo "${new_pid}" > "${PID_FILE}"

for _ in $(seq 1 30); do
  if server_health_ok; then
    echo "HexStrike server started (PID ${new_pid}, port ${HEXSTRIKE_PORT})."
    echo "Log: ${LOG_FILE}"
    exit 0
  fi
  if ! is_pid_running "${new_pid}"; then
    echo "ERROR: Server process exited during startup. Check ${LOG_FILE}" >&2
    rm -f "${PID_FILE}"
    exit 1
  fi
  sleep 1
done

echo "ERROR: Server started (PID ${new_pid}) but health check did not pass in time." >&2
echo "Check ${LOG_FILE} for details." >&2
exit 1
