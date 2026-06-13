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

if ! "$PYTHON_BIN" -c "import customtkinter" >/dev/null 2>&1; then
  echo "customtkinter is not available in: $PYTHON_BIN" >&2
  echo "Install dependencies in the project venv or set PYTHON_BIN explicitly." >&2
  exit 1
fi

export PYTHONUNBUFFERED=1
exec "$PYTHON_BIN" "$PWD/subtitle_agent_app.py" "$@"
