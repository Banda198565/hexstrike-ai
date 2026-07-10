#!/usr/bin/env bash
# vps-status.sh — quick VPS + Mac integration status
set -euo pipefail

HOST="${VPS_HOST:-hexstrike-vps}"
INSTALL_DIR="${HEXSTRIKE_DIR:-/opt/hexstrike-ai}"

echo "=== HexStrike VPS Status (${HOST}) ==="
ssh -o BatchMode=yes -o ConnectTimeout=10 "${HOST}" "bash -s" <<REMOTE
echo "Host: \$(hostname)"
echo "IP: \$(curl -sf --max-time 3 ifconfig.me 2>/dev/null || echo '?')"
echo "Uptime: \$(uptime -p 2>/dev/null || uptime)"
if [[ -d ${INSTALL_DIR} ]]; then
  cd ${INSTALL_DIR}
  echo "Repo: \$(git log -1 --oneline 2>/dev/null || echo 'not cloned')"
  echo "Orchestrator: \$(systemctl is-active hexstrike-orchestrator 2>/dev/null || echo 'no service')"
  [[ -f artifacts/vps-master-report.json ]] && echo "Master report: present" || echo "Master report: missing"
else
  echo "Repo: NOT INSTALLED at ${INSTALL_DIR}"
fi
REMOTE

echo ""
echo "=== Mac local ==="
curl -sf --max-time 2 http://127.0.0.1:11434/api/tags >/dev/null && echo "Ollama: OK" || echo "Ollama: DOWN"
curl -sf --max-time 2 http://127.0.0.1:8888/health >/dev/null && echo "HexStrike API: OK" || echo "HexStrike API: DOWN"
python3 hexstrike_orchestrator.py status 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print('Agents:', d['agents']['agents_bound']); print('MCPs:', len(d['mcps']))" 2>/dev/null || echo "Orchestrator: check manually"
