#!/bin/bash
# Deploy read-only blockchain MCP layer on HexStrike VPS
set -euo pipefail

HEX_ROOT="${HEX_ROOT:-/opt/hexstrike-ai}"
MCP_SRC="${MCP_SRC:-/root/blockchain-mcp}"
VENV="${VENV:-$HEX_ROOT/hexstrike-env}"

echo "=== Blockchain MCP deploy ==="
mkdir -p "$MCP_SRC/lib" "$HEX_ROOT/mcp"

# copy from repo if present
if [[ -d /workspace/mcp ]]; then
  rsync -a /workspace/mcp/ "$MCP_SRC/"
  rsync -a /workspace/mcp-config.json "$HEX_ROOT/mcp-config.json"
fi

chmod +x "$MCP_SRC"/*.py 2>/dev/null || true

# env
mkdir -p /etc/hexstrike
cat >/etc/hexstrike/blockchain-mcp.env <<ENV
EVM_RPC_URL=http://51.222.42.220:8545
EVM_CHAIN_ID=56
ENV

echo "=== Smoke test (Python) ==="
"$VENV/bin/python3" - <<'PY'
import sys
sys.path.insert(0, "/root/blockchain-mcp")
from lib.evm_client import EvmClient
c = EvmClient()
print("chainId", int(c.rpc("eth_chainId", []), 16))
meta = c.token_meta("0x55d398326f99059fF775485246999027B3197955")
print("USDT symbol", meta.get("symbol"))
PY

cat <<'README'

=== Cursor on Mac ===
1) SSH tunnel (HexStrike + optional):
   ssh -L 8888:127.0.0.1:8888 root@78.27.235.70

2) Copy mcp-config.json paths to Mac Eva/hexstrike and set:
   EVM_RPC_URL=http://51.222.42.220:8545

3) Cursor → Settings → MCP → merge servers:
   - evm-rpc-mcp
   - block-explorer-mcp
   - defi-dex-mcp

READ-ONLY: no signing tools exposed.

README

echo "Done."
