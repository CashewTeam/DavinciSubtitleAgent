#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"

"$PYTHON_BIN" -m PyInstaller --clean --noconfirm "SubtitleAgent.spec"
