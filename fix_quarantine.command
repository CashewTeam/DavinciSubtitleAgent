#!/bin/zsh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_PATH="$SCRIPT_DIR/Subtitle Agent.app"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Subtitle Agent.app not found next to this script."
  echo "Expected: $APP_PATH"
  read -r "?Press Enter to close..."
  exit 1
fi

echo "Removing quarantine attribute from:"
echo "$APP_PATH"
/usr/bin/xattr -dr com.apple.quarantine "$APP_PATH"

echo
echo "Done. You can now open Subtitle Agent.app."
read -r "?Press Enter to close..."
