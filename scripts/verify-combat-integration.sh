#!/usr/bin/env bash
# Verify combat agents (transaction, rescue, discovery) + CLI wiring.
# Usage: bash scripts/verify-combat-integration.sh [/opt/hexstrike-ai]
set -euo pipefail

ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"

FAIL=0
ok() { echo "  ✔ $*"; }
bad() { echo "  ✘ $*"; FAIL=$((FAIL + 1)); }

echo "════════════════════════════════════════════════════════"
echo " Combat agents integration check"
echo " ROOT: $ROOT"
echo "════════════════════════════════════════════════════════"

for f in \
  agents/combat-agents.json \
  scripts/agents/agent_transaction.py \
  scripts/agents/agent_rescue.py \
  scripts/agents/agent_discovery.py \
  scripts/hexstrike_agent_run.py \
  scripts/hexstrike_logs.py \
  scripts/hexstrike_orchestrator_cmd.py \
  scripts/pipeline_transaction_discovery.sh \
  scripts/fastmcp_live_cycle.sh \
  scripts/fastmcp_verify.sh \
  scripts/vps-almalinux-fastmcp-bootstrap.sh \
  scripts/vps-fastmcp-ops.sh \
  scripts/vps-pull-and-ops.sh \
  scripts/mac-fastmcp-live.sh \
  scripts/tx_control.sh; do
  [[ -f "$ROOT/$f" ]] && ok "$f" || bad "missing $f"
done

for agent in Agent-Transaction-01 Agent-Rescue-01 Agent-Discovery-01; do
  grep -q "$agent" "$ROOT/agents/registry.json" 2>/dev/null && ok "registry: $agent" || bad "registry missing $agent"
done

grep -q '"transaction-discovery"' "$ROOT/agents/workflows.json" 2>/dev/null && ok "workflows: transaction-discovery" || bad "workflows missing transaction-discovery"

for agent in Agent-Transaction-01 Agent-Rescue-01 Agent-Discovery-01; do
  grep -q "$agent" "$ROOT/mcp/agent-bindings.json" 2>/dev/null && ok "mcp: $agent" || bad "mcp missing $agent"
done

if grep -q 'agent run' "$ROOT/hexstrike" 2>/dev/null; then
  ok "hexstrike CLI routes agent/logs/orchestrator"
else
  bad "hexstrike wrapper missing combat routes"
fi

if grep -q 'fastmcp' "$ROOT/hexstrike" 2>/dev/null && grep -q 'ops' "$ROOT/hexstrike" 2>/dev/null; then
  ok "hexstrike CLI routes ops/fastmcp"
else
  bad "hexstrike wrapper missing ops/fastmcp routes"
fi

[[ -f "$ROOT/mcp/tx-skills.json" ]] && ok "mcp/tx-skills.json" || bad "missing mcp/tx-skills.json"
[[ -f "$ROOT/scripts/mcp_tx.py" ]] && ok "scripts/mcp_tx.py" || bad "missing scripts/mcp_tx.py"

if grep -q 'mcp tx' "$ROOT/hexstrike" 2>/dev/null; then
  ok "hexstrike CLI routes mcp tx"
else
  bad "hexstrike wrapper missing mcp tx route"
fi

for skill in tx_build tx_sign tx_broadcast tx_status tx_rescue tx_log tx_discovery; do
  grep -q "\"$skill\"" "$ROOT/mcp/agent-bindings.json" 2>/dev/null && ok "mcp binding: $skill" || bad "mcp binding missing $skill"
done

echo ""
echo "── MCP tx skill smoke tests ──"
if out="$(./hexstrike tx build --target=0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA --value=0.001bnb --gas=21000 2>&1)"; then
  echo "$out" | grep -q '"command": "build"' && ok "hexstrike tx build" || bad "hexstrike tx build incomplete"
else
  bad "hexstrike tx build failed"
fi

if out="$(./hexstrike tx nonce 2>&1)"; then
  echo "$out" | grep -q '"command": "nonce"' && ok "hexstrike tx nonce" || bad "hexstrike tx nonce incomplete"
else
  bad "hexstrike tx nonce failed"
fi

if out="$(./hexstrike vault status 2>&1)"; then
  echo "$out" | grep -q '"command": "vault_status"' && ok "hexstrike vault status" || bad "hexstrike vault status incomplete"
else
  bad "hexstrike vault status failed"
fi

if out="$(python3 "$ROOT/scripts/mcp_tx.py" build --target=0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA --value=0.001bnb --dry-run 2>&1)"; then
  echo "$out" | grep -q '"skill_id": "tx_build"' && ok "mcp tx build" || bad "mcp tx build incomplete"
else
  bad "mcp tx build failed"
fi

if out="$(python3 "$ROOT/scripts/mcp_tx.py" discovery --trace 2>&1)"; then
  echo "$out" | grep -q '"skill_id": "tx_discovery"' && ok "mcp tx discovery" || bad "mcp tx discovery incomplete"
else
  bad "mcp tx discovery failed"
fi

echo ""
echo "── Runtime smoke tests ──"
if python3 -m py_compile \
  "$ROOT/scripts/agents/agent_transaction.py" \
  "$ROOT/scripts/agents/agent_rescue.py" \
  "$ROOT/scripts/agents/agent_discovery.py" \
  "$ROOT/scripts/hexstrike_agent_run.py" \
  "$ROOT/scripts/hexstrike_logs.py" \
  "$ROOT/scripts/hexstrike_orchestrator_cmd.py" 2>/dev/null; then
  ok "Python syntax compile"
else
  bad "SyntaxError in combat agent modules"
fi

if out="$(python3 "$ROOT/scripts/agents/agent_discovery.py" scan 2>&1)"; then
  echo "$out" | grep -q '"success": true' && ok "discovery scan" || bad "discovery scan no success"
else
  bad "discovery scan failed"
fi

if out="$(TARGET_ADDRESS=0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA python3 "$ROOT/scripts/agents/agent_transaction.py" dry-run 2>&1)"; then
  echo "$out" | grep -q '"success": true' && ok "transaction dry-run" || bad "transaction dry-run no success"
else
  bad "transaction dry-run failed"
fi

if out="$(python3 "$ROOT/scripts/hexstrike_agent_run.py" run pipeline --pipeline transaction-discovery 2>&1)"; then
  echo "$out" | grep -q '"pipeline": "transaction-discovery"' && ok "pipeline transaction-discovery" || bad "pipeline JSON incomplete"
else
  bad "pipeline transaction-discovery failed"
fi

echo ""
if [[ "$FAIL" -eq 0 ]]; then
  echo "RESULT: PASS — Combat agents integrated in $ROOT"
  exit 0
fi
echo "RESULT: FAIL — $FAIL check(s) failed"
exit 1
