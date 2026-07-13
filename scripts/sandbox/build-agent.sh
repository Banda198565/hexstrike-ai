#!/usr/bin/env bash
# build-agent.sh — compile hexstrike-agent (Go rescue orchestrator)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT="${1:-$ROOT/bin/hexstrike-agent}"
mkdir -p "$(dirname "$OUT")"
cd "$ROOT/cmd/agent"
go build -o "$OUT" .
echo "[OK] $OUT"
