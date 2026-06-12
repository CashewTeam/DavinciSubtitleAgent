#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

DEFAULT_VENV_PYTHON="$PWD/venv/bin/python"
if [[ -z "${PYTHON_BIN:-}" ]]; then
  if [[ -x "$DEFAULT_VENV_PYTHON" ]]; then
    PYTHON_BIN="$DEFAULT_VENV_PYTHON"
  else
    PYTHON_BIN="python3"
  fi
else
  PYTHON_BIN="$PYTHON_BIN"
fi

export PYINSTALLER_CONFIG_DIR="${PYINSTALLER_CONFIG_DIR:-$PWD/.pyinstaller-cache}"

if ! "$PYTHON_BIN" -c "import PyInstaller" >/dev/null 2>&1; then
  echo "PyInstaller is not available in: $PYTHON_BIN" >&2
  echo "Install dependencies in the project venv or set PYTHON_BIN explicitly." >&2
  exit 1
fi

"$PYTHON_BIN" -m PyInstaller --clean --noconfirm "SubtitleAgent.spec"
