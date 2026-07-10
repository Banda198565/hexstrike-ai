#!/usr/bin/env bash
# index-rag.sh — index artifacts into Eva HDD RAG store
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export RAG_STORAGE_ROOT="${RAG_STORAGE_ROOT:-/Volumes/Eva/hexstrike-rag-data}"
PY="${ROOT}/rag-env/bin/python"
[[ -x "$PY" ]] || PY="python3"
exec "$PY" "${ROOT}/scripts/rag_core.py" --index-all "${1:-${ROOT}/artifacts/}"
