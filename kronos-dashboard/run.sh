#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
export KRONOS_DIR="${KRONOS_DIR:-$HERE/../../Kronos}"
export HF_HUB_DISABLE_XET=1
PY="$HERE/.venv/bin/python"; [ -x "$PY" ] || PY=python3
cd "$HERE" && exec "$PY" app.py
