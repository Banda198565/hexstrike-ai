#!/usr/bin/env bash
# Restart HexStrike API server.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"${SCRIPT_DIR}/hexstrike-stop.sh"
sleep 1
exec "${SCRIPT_DIR}/hexstrike-start.sh"
