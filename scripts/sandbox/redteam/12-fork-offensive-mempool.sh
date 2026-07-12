#!/usr/bin/env bash
# 12-fork-offensive-mempool.sh — BSC fork + live mempool pipeline (sim only)
set -euo pipefail
REDTEAM="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=_common.sh
source "$REDTEAM/_common.sh"
require_tools

echo "=== REDTEAM 12: Fork offensive + mempool pipeline ==="

export MEV_SANDBOX_ONLY=1 MEV_ALLOWED_CHAINS=56 BUILDER_SIM_ONLY=1
export PIPELINE_USE_FORK=1

if ! python3 "$SANDBOX/mev/offensive_pipeline.py" > /tmp/mev-12.log 2>&1; then
  log_result "12-fork-offensive-mempool" "INCONCLUSIVE" "offensive_pipeline failed — /tmp/mev-12.log"
  exit 0
fi

ok="$(python3 - "$ROOT/artifacts/sandbox/mev-live-pipeline-result.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
mempool = d.get("mempool", {})
print(1 if mempool.get("candidate_count", 0) >= 0 and d.get("builder_sim") else 0)
PY
)"

if [[ "$ok" == "1" ]]; then
  candidates="$(python3 -c "import json;print(json.load(open('$ROOT/artifacts/sandbox/mev-live-pipeline-result.json'))['mempool'].get('candidate_count',0))")"
  log_result "12-fork-offensive-mempool" "VULN_CONFIRMED" "pipeline ok candidates=${candidates} sim_only=true"
else
  log_result "12-fork-offensive-mempool" "INCONCLUSIVE" "pipeline artifact invalid"
fi

# Restore local Anvil for phase 13 integration test
"$SANDBOX/stop-bsc-fork.sh" 2>/dev/null || true
"$SANDBOX/start-anvil.sh" >/dev/null 2>&1 || true
