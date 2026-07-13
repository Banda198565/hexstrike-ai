#!/usr/bin/env bash
# fastmcp_status.sh — compact FastMCP contour status (VPS or Mac)
#
# Usage:
#   bash scripts/fastmcp_status.sh
#   ./hexstrike fastmcp status
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ -f .env ]]; then
  set -a
  # shellcheck source=/dev/null
  source .env
  set +a
fi

HEXSTRIKE="${ROOT}/hexstrike"
[[ -x "$HEXSTRIKE" ]] || HEXSTRIKE="hexstrike"

HOST_ROLE="${HEXSTRIKE_HOST_ROLE:-}"
if [[ -z "$HOST_ROLE" ]]; then
  if [[ "$ROOT" == "/opt/hexstrike-ai" ]] || [[ "$(uname -s)" == "Linux" ]]; then
    HOST_ROLE="vps"
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    HOST_ROLE="mac"
  else
    HOST_ROLE="unknown"
  fi
fi

python3 - <<PY
import json, os, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path("${ROOT}")
HOST_ROLE = "${HOST_ROLE}"
LIVE = os.environ.get("HEXSTRIKE_TX_LIVE", "")
TARGET = os.environ.get("TARGET_ADDRESS") or os.environ.get("TARGET_WALLET") or "0x4943F5E7F4e450d48Ae82026163ecDe8A52C53dA"
BOT = os.environ.get("BOT_ADDRESS") or os.environ.get("PUBLIC_ADDRESS") or ""

report = {
    "command": "fastmcp_status",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "host_role": HOST_ROLE,
    "root": str(ROOT),
    "live_flag": LIVE or "unset",
    "live_allowed": HOST_ROLE == "mac" and LIVE == "1",
    "env": {
        "vault_passphrase": "SET" if os.environ.get("VAULT_PASSPHRASE") else "unset",
        "bot_private_key": "SET" if os.environ.get("BOT_PRIVATE_KEY") else "unset",
        "rpc_url": os.environ.get("RPC_URL", "unset"),
        "bot_address": BOT or "unset",
        "target": TARGET,
    },
    "scripts": {},
    "artifacts": {},
    "vault": {},
    "allowlist": {},
    "nonce": {},
    "verdict": "",
}

for name in (
    "scripts/fastmcp_verify.sh",
    "scripts/fastmcp_live_cycle.sh",
    "scripts/vps-fastmcp-ops.sh",
    "scripts/mac-fastmcp-live.sh",
    "scripts/run_fastmcp_combat_live.py",
    "src/hexstrike/mcp/fastmcp/tx_package.py",
):
    report["scripts"][name] = (ROOT / name).is_file()

# artifacts
latest = ROOT / "tx_logs" / "latest" / "fastmcp_cycle.json"
ops = ROOT / "tx_logs" / "ops" / "latest_ops_summary.json"
dry = ROOT / "tx_logs" / "latest_dry_run.json"
for label, path in (("latest_cycle", latest), ("ops_summary", ops), ("latest_dry_run", dry)):
    if path.is_file():
        try:
            data = json.loads(path.read_text())
            report["artifacts"][label] = {
                "path": str(path),
                "success": data.get("success", data.get("dry_run_success")),
                "gate_allowed": data.get("gate_allowed") or (data.get("gate") or {}).get("allowed"),
                "sign_hash": data.get("sign_hash") or (data.get("sign") or {}).get("hash"),
                "sign_from": data.get("sign_from") or (data.get("sign") or {}).get("from"),
                "mode": data.get("mode"),
            }
        except Exception as exc:
            report["artifacts"][label] = {"path": str(path), "error": str(exc)}
    else:
        report["artifacts"][label] = {"path": str(path), "exists": False}

# vault status (no unlock)
try:
    out = subprocess.check_output([str(ROOT / "hexstrike"), "vault", "status"], text=True, cwd=str(ROOT), timeout=30)
    report["vault"] = json.loads(out)
except Exception as exc:
    report["vault"] = {"error": str(exc)}

# allowlist
try:
    sys.path.insert(0, str(ROOT / "src"))
    from hexstrike.mcp.fastmcp import AllowlistManager
    al = AllowlistManager().load()
    recipients = [a.lower() for a in al.get("authorized_recipients", [])]
    report["allowlist"] = {
        "path": "config/hot-wallet-allowlist.json",
        "hot_wallet": al.get("hot_wallet"),
        "recipient_count": len(recipients),
        "target_authorized": TARGET.lower() in recipients,
    }
except Exception as exc:
    report["allowlist"] = {"error": str(exc)}

# nonce (best-effort)
try:
    cmd = [str(ROOT / "hexstrike"), "tx", "nonce"]
    if BOT:
        cmd += [f"--address={BOT}"]
    out = subprocess.check_output(cmd, text=True, cwd=str(ROOT), timeout=45)
    n = json.loads(out)
    report["nonce"] = {
        "pending_gap": n.get("pending_gap"),
        "recommended_nonce": n.get("recommended_nonce"),
        "stuck": n.get("stuck"),
        "address": n.get("address"),
    }
except Exception as exc:
    report["nonce"] = {"error": str(exc)}

# verdict
missing = [k for k, v in report["scripts"].items() if not v]
if HOST_ROLE == "vps" and LIVE == "1":
    report["verdict"] = "❌ VPS_LIVE_FORBIDDEN"
elif missing:
    report["verdict"] = "⚠️ MISSING_SCRIPTS"
elif report["allowlist"].get("target_authorized") is False:
    report["verdict"] = "🔒 ALLOWLIST_BLOCK"
elif report["nonce"].get("pending_gap", 0) not in (0, None) and report["nonce"].get("pending_gap", 0) > 0:
    report["verdict"] = "⚠️ NONCE_GAP"
elif HOST_ROLE == "vps":
    report["verdict"] = "✅ VPS_WATCH_OK"
elif HOST_ROLE == "mac" and LIVE == "1":
    report["verdict"] = "✅ MAC_LIVE_ARMED"
else:
    report["verdict"] = "✅ MAC_DRYRUN_READY"

print(json.dumps(report, indent=2))
sys.exit(0 if report["verdict"].startswith("✅") else 1)
PY
