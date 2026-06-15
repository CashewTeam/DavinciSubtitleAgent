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

APP_VERSION="$("$PYTHON_BIN" - <<'PY'
from subtitle_agent_app.main import APP_VERSION
print(APP_VERSION)
PY
)"

"$PYTHON_BIN" -m PyInstaller --clean --noconfirm "SubtitleAgent.spec"

if [[ -n "${MACOS_CODESIGN_IDENTITY:-}" ]]; then
  echo "Signing and notarization enabled."
  ./sign_macos_app.sh "dist/Subtitle Agent.app"
else
  echo "Skipping signing: set MACOS_CODESIGN_IDENTITY to enable Developer ID signing."
fi

chmod +x "fix_quarantine.command"

DIST_PACKAGE_DIR="dist/Subtitle Agent Package"
rm -rf "$DIST_PACKAGE_DIR"
mkdir -p "$DIST_PACKAGE_DIR"
cp -R "dist/Subtitle Agent.app" "$DIST_PACKAGE_DIR/"
cp "fix_quarantine.command" "$DIST_PACKAGE_DIR/"

ZIP_PATH="dist/SubtitleAgent_macOS_ARM64_${APP_VERSION}.zip"
rm -f "$ZIP_PATH"
/usr/bin/ditto -c -k --keepParent "$DIST_PACKAGE_DIR" "$ZIP_PATH"
echo "Adhoc distribution zip ready: $ZIP_PATH"
