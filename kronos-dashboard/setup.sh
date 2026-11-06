#!/usr/bin/env bash
# One-time setup: clones Kronos next to this repo, creates a virtualenv, installs dependencies.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
KRONOS_DIR="${KRONOS_DIR:-$HERE/../../Kronos}"
if [ ! -d "$KRONOS_DIR/model" ]; then
  git clone --depth 1 https://github.com/shiyu-coder/Kronos.git "$KRONOS_DIR"
fi
python3 -m venv "$HERE/.venv"
"$HERE/.venv/bin/pip" install -q --upgrade pip
"$HERE/.venv/bin/pip" install -q torch --index-url https://download.pytorch.org/whl/cpu
"$HERE/.venv/bin/pip" install -q -r "$HERE/requirements.txt"
echo "Done. Start with: ./run.sh"
