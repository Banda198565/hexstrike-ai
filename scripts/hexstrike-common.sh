#!/usr/bin/env bash
# Shared helpers for HexStrike server management scripts.

set -euo pipefail

HEXSTRIKE_ROOT="${HEXSTRIKE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
HEXSTRIKE_PORT="${HEXSTRIKE_PORT:-8888}"
PID_FILE="${HEXSTRIKE_ROOT}/.hexstrike-server.pid"
LOG_DIR="${HEXSTRIKE_ROOT}/logs"
LOG_FILE="${LOG_DIR}/hexstrike-server.log"
SERVER_SCRIPT="${HEXSTRIKE_ROOT}/hexstrike_server.py"
EVA_MOUNT="/Volumes/EVA"
EVA_WAIT_SECONDS="${EVA_WAIT_SECONDS:-60}"

_find_venv_python() {
  local candidates=(
    "${HEXSTRIKE_ROOT}/hexstrike-env/bin/python"
    "${HEXSTRIKE_ROOT}/.venv/bin/python"
    "${HOME}/.local/hexstrike-venv/bin/python"
  )
  for candidate in "${candidates[@]}"; do
    if [[ -x "${candidate}" ]]; then
      echo "${candidate}"
      return 0
    fi
  done
  return 1
}

_eva_symlink_requires_mount() {
  local link="${HEXSTRIKE_ROOT}/hexstrike-ai"
  if [[ -L "${link}" ]]; then
    local target
    target="$(readlink "${link}")"
    [[ "${target}" == /Volumes/EVA/* ]]
    return $?
  fi
  return 1
}

ensure_eva_available() {
  if ! _eva_symlink_requires_mount; then
    return 0
  fi

  if [[ -d "${EVA_MOUNT}" && -r "${EVA_MOUNT}" ]]; then
    return 0
  fi

  echo "WARNING: ${EVA_MOUNT} is not mounted but ${HEXSTRIKE_ROOT}/hexstrike-ai depends on it." >&2
  echo "Waiting up to ${EVA_WAIT_SECONDS}s for Eva volume..." >&2

  local waited=0
  while (( waited < EVA_WAIT_SECONDS )); do
    if [[ -d "${EVA_MOUNT}" && -r "${EVA_MOUNT}" ]]; then
      echo "Eva volume mounted." >&2
      return 0
    fi
    sleep 2
    waited=$((waited + 2))
  done

  echo "ERROR: Eva volume still unavailable after ${EVA_WAIT_SECONDS}s." >&2
  return 1
}

ensure_log_dir() {
  mkdir -p "${LOG_DIR}"
}

is_pid_running() {
  local pid="$1"
  [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null
}

read_pid_file() {
  if [[ -f "${PID_FILE}" ]]; then
    tr -d '[:space:]' < "${PID_FILE}"
  fi
}

find_server_pid_by_port() {
  lsof -tiTCP:"${HEXSTRIKE_PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true
}

server_health_ok() {
  if curl -fsS --max-time 10 "http://127.0.0.1:${HEXSTRIKE_PORT}/health" >/dev/null 2>&1; then
    return 0
  fi
  local python
  python="$(_find_venv_python 2>/dev/null || true)"
  [[ -n "${python}" ]] || python="$(command -v python3 2>/dev/null || true)"
  [[ -n "${python}" ]] || return 1
  "${python}" -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:${HEXSTRIKE_PORT}/health', timeout=15)" >/dev/null 2>&1
}

is_hexstrike_server_pid() {
  local pid="$1"
  ps -p "${pid}" -o command= 2>/dev/null | grep -q "hexstrike_server.py"
}

resolve_python() {
  local python
  if ! python="$(_find_venv_python)"; then
    echo "ERROR: No HexStrike virtualenv found." >&2
    echo "Expected one of: hexstrike-env, .venv, ~/.local/hexstrike-venv" >&2
    return 1
  fi
  echo "${python}"
}

find_interactsh_client() {
  local candidate
  for candidate in     "${INTERACTSH_CLIENT:-}"     "${HOME}/go/bin/interactsh-client"     "$(command -v interactsh-client 2>/dev/null || true)"     "/opt/homebrew/bin/interactsh-client"     "/usr/local/bin/interactsh-client"; do
    if [[ -n "${candidate}" && -x "${candidate}" ]]; then
      echo "${candidate}"
      return 0
    fi
  done
  return 1
}

remote_interactsh_client_check() {
  local host="${1:?host required}"
  ssh -o BatchMode=yes -o ConnectTimeout=10 "${host}" '
    for c in "${INTERACTSH_CLIENT:-}" "$HOME/go/bin/interactsh-client" "$(command -v interactsh-client 2>/dev/null || true)"; do
      if [[ -n "${c}" && -x "${c}" ]]; then exit 0; fi
    done
    exit 1
  ' >/dev/null 2>&1
}
