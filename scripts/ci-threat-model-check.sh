#!/usr/bin/env bash
# ci-threat-model-check.sh — read-only GitHub Actions threat model checklist
# Mac/VPS: bash scripts/ci-threat-model-check.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass=0
fail=0
warn=0

ok()   { echo -e "${GREEN}PASS${NC}: $*"; pass=$((pass + 1)); }
bad()  { echo -e "${RED}FAIL${NC}: $*"; fail=$((fail + 1)); }
note() { echo -e "${YELLOW}WARN${NC}: $*"; warn=$((warn + 1)); }

echo "=== GitHub Actions Threat Model Check (read-only) ==="
echo ""

shopt -s nullglob
workflows=(.github/workflows/*.{yml,yaml})
if [[ ${#workflows[@]} -eq 0 ]]; then
  note "No workflows in .github/workflows/"
else
  for wf in "${workflows[@]}"; do
    echo "--- $wf ---"
    if grep -q 'pull_request_target' "$wf"; then
      bad "$wf uses pull_request_target (fork-to-base risk)"
    else
      ok "$wf — no pull_request_target"
    fi
    if grep -qE 'id-token:\s*write' "$wf"; then
      note "$wf requests OIDC id-token — verify cloud trust policy"
    else
      ok "$wf — no OIDC id-token"
    fi
    if grep -q 'actions/cache' "$wf"; then
      note "$wf uses cache — verify key includes github.ref"
    fi
    if grep -qE 'run:.*\$\{\{\s*github\.event\.(pull_request|issue|comment)' "$wf"; then
      bad "$wf — possible expression injection in run:"
    else
      ok "$wf — no obvious event injection in run:"
    fi
    if grep -qE 'secrets\.' "$wf"; then
      note "$wf references secrets — ensure not on fork PR jobs"
    fi
  done
fi

echo ""
echo "--- Reference examples (not active CI) ---"
for ex in docs/examples/gh-actions-*.example.yml; do
  [[ -f "$ex" ]] && echo "  $ex"
done
echo ""
echo "Full doc: docs/CI-SECURITY-THREAT-MODEL.md"
echo ""
echo "Summary: PASS=$pass FAIL=$fail WARN=$warn"
[[ "$fail" -eq 0 ]]
