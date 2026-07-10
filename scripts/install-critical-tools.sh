#!/usr/bin/env bash
# install-critical-tools.sh — install Nmap + Nuclei for hexstrike-env (VPS/Linux)
set -euo pipefail

log() { echo "[tools] $*"; }

[[ $(id -u) -eq 0 ]] || { echo "[tools] Run as root (apt-get)"; exit 1; }

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nmap curl

if ! command -v nuclei >/dev/null 2>&1; then
  log "Installing nuclei binary..."
  ARCH=$(uname -m)
  case "$ARCH" in
    x86_64) NARCH=amd64 ;;
    aarch64|arm64) NARCH=arm64 ;;
    *) log "Unsupported arch: $ARCH — install nuclei manually"; exit 1 ;;
  esac
  VER=$(curl -sS https://api.github.com/repos/projectdiscovery/nuclei/releases/latest | python3 -c "import json,sys; print(json.load(sys.stdin)['tag_name'].lstrip('v'))")
  TMP=$(mktemp -d)
  curl -sSL "https://github.com/projectdiscovery/nuclei/releases/download/v${VER}/nuclei_${VER}_linux_${NARCH}.zip" -o "$TMP/nuclei.zip"
  unzip -q "$TMP/nuclei.zip" -d "$TMP"
  install -m 755 "$TMP/nuclei" /usr/local/bin/nuclei
  rm -rf "$TMP"
  nuclei -update-templates 2>/dev/null || true
fi

log "Installed:"
command -v nmap && nmap --version | head -1
command -v nuclei && nuclei -version 2>/dev/null | head -1

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if curl -sf --max-time 3 http://127.0.0.1:8888/health >/dev/null 2>&1; then
  log "Re-check hexstrike tools count:"
  curl -sf http://127.0.0.1:8888/health | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(f\"  {d.get('total_tools_available')}/{d.get('total_tools_count')} tools available\")
print(f\"  nmap={d.get('tools_status',{}).get('nmap')} nuclei={d.get('tools_status',{}).get('nuclei')}\")
"
fi
