#!/usr/bin/env bash
# Orchestrator smoke tests — infrastructure only (not agent behavior).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

pass=0
fail=0

run() {
  local name="$1"
  shift
  if "$@"; then
    echo "PASS $name"
    pass=$((pass + 1))
  else
    echo "FAIL $name"
    fail=$((fail + 1))
  fi
}

run "api_health" curl -fsS http://127.0.0.1:8888/health >/dev/null
run "r1_deepseek" python3 scripts/verify-r1-deepseek.py
run "web3_audit_tests" python3 scripts/test_web3_audit_runner.py
run "solidity_audit_tests" python3 scripts/test_solidity_audit_runner.py
run "web3_rpc_tests" python3 scripts/test_web3_rpc_runner.py
run "orchestrator_status" python3 hexstrike_orchestrator.py status >/dev/null

echo "---"
echo "Smoke: $pass passed, $fail failed"
test "$fail" -eq 0
