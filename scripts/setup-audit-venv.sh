#!/usr/bin/env bash
# Изолированное окружение для Slither + Mythril (не трогает base conda).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="${ROOT}/.venv-audit"

echo "[+] Creating audit venv: $VENV"
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"

pip install --upgrade pip wheel
pip install 'slither-analyzer>=0.10,<0.12'
pip install 'mythril==0.23.25'

echo ""
echo "[+] Installed:"
slither --version || true
myth version 2>/dev/null || mythril version 2>/dev/null || true

cat <<EOF

[+] Готово. Активация перед аудитом:
  source ${VENV}/bin/activate

[+] Запуск:
  export BSCSCAN_API_KEY=your_key
  export BSC_RPC=http://51.222.42.220:8545
  ./scripts/run-slither-mythril-audit.sh

[+] Деактивация:
  deactivate
EOF
