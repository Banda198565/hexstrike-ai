#!/usr/bin/env bash
# Install `hx` CLI on VPS — one entry point, no directory confusion
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[[ $(id -u) -eq 0 ]] || { echo "Run as root on VPS"; exit 1; }

install -m 755 "$ROOT/scripts/hx" /usr/local/bin/hx
grep -q 'HEXSTRIKE_ROOT=/opt/hexstrike-ai' /root/.bashrc 2>/dev/null || \
  echo 'export HEXSTRIKE_ROOT=/opt/hexstrike-ai' >> /root/.bashrc

echo "Installed: /usr/local/bin/hx"
echo "Try: hx status"
echo "Try: hx manifest"
echo "Try: hx exploit-test"
