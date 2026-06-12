#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$PWD/.pyinstaller-cache}"

"$PYTHON_BIN" -m PyInstaller --clean --noconfirm "SubtitleAgent.spec"
