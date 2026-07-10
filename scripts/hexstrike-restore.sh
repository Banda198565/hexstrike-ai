#!/usr/bin/env bash
# One-command recovery: fix MCP ports, ensure dirs, start server, health check.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=hexstrike-common.sh
source "${SCRIPT_DIR}/hexstrike-common.sh"

MCP_JSON="${HOME}/.cursor/mcp.json"
MCP_HUB_JSON="${HOME}/.cursor/mcp-hub.json"
MCP_FIX_DIR="/tmp/mcp-fix"

fix_mcp_configs() {
  echo "=== Fixing MCP configs (port ${HEXSTRIKE_PORT}) ==="

  if [[ -f "${MCP_FIX_DIR}/mcp.json" ]]; then
    cp "${MCP_FIX_DIR}/mcp.json" "${MCP_JSON}"
    echo "Applied ${MCP_FIX_DIR}/mcp.json -> ${MCP_JSON}"
  elif [[ -f "${MCP_JSON}" ]]; then
    sed -i '' 's|http://127.0.0.1:8890|http://127.0.0.1:8888|g; s|http://localhost:8890|http://127.0.0.1:8888|g' "${MCP_JSON}"
    echo "Patched port in ${MCP_JSON}"
  else
    echo "WARNING: ${MCP_JSON} not found" >&2
  fi

  if [[ -f "${MCP_FIX_DIR}/mcp-hub.json" ]]; then
    cp "${MCP_FIX_DIR}/mcp-hub.json" "${MCP_HUB_JSON}"
    # Fix non-existent .venv path from prepared fix
    sed -i '' 's|/hexstrike-ai/.venv/bin/python|/hexstrike-ai/hexstrike-env/bin/python|g' "${MCP_HUB_JSON}"
    sed -i '' 's|http://localhost:8888|http://127.0.0.1:8888|g' "${MCP_HUB_JSON}"
    echo "Applied ${MCP_FIX_DIR}/mcp-hub.json -> ${MCP_HUB_JSON} (venv path corrected)"
  elif [[ -f "${MCP_HUB_JSON}" ]]; then
    sed -i '' 's|http://127.0.0.1:8890|http://127.0.0.1:8888|g; s|http://localhost:8890|http://127.0.0.1:8888|g; s|/hexstrike-ai/.venv/bin/python|/hexstrike-ai/hexstrike-env/bin/python|g' "${MCP_HUB_JSON}"
    echo "Patched port and venv path in ${MCP_HUB_JSON}"
  else
    echo "WARNING: ${MCP_HUB_JSON} not found" >&2
  fi
}

ensure_log_dir
fix_mcp_configs

echo
echo "=== Starting HexStrike server ==="
"${SCRIPT_DIR}/hexstrike-start.sh"

echo
echo "=== Health check ==="
if server_health_ok; then
  echo "Health: OK"
  curl -fsS --max-time 5 "http://127.0.0.1:${HEXSTRIKE_PORT}/health"
  echo
else
  echo "Health: FAILED — see ${LOG_FILE}" >&2
  exit 1
fi

echo
"${SCRIPT_DIR}/hexstrike-status.sh"

echo
echo "Recovery complete. Reload MCP in Cursor: Cmd+Shift+P -> 'MCP: Reload Servers'"
