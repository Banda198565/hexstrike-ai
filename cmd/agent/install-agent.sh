#!/usr/bin/env bash
set -euo pipefail
MODE="${1:-local}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
bash "$(dirname "$0")/build.sh"
BIN="$ROOT/bin/hexstrike-agent"
if [[ "$MODE" == "global" ]]; then
  install -m 755 "$BIN" /usr/local/bin/hexstrike-agent
  echo "installed to /usr/local/bin/hexstrike-agent"
else
  echo "local build: $BIN"
  echo 'add to PATH: export PATH="$PATH:'"$ROOT/bin"'"
fi
