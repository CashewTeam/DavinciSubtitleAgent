#!/bin/zsh
set -euo pipefail

cd "$(dirname "$0")"

APP_PATH="${1:-dist/Subtitle Agent.app}"
if [[ ! -d "$APP_PATH" ]]; then
  echo "App bundle not found: $APP_PATH" >&2
  exit 1
fi

if [[ -z "${MACOS_CODESIGN_IDENTITY:-}" ]]; then
  echo "MACOS_CODESIGN_IDENTITY is required for signing." >&2
  exit 1
fi

if ! command -v codesign >/dev/null 2>&1; then
  echo "codesign not found." >&2
  exit 1
fi

if ! command -v xcrun >/dev/null 2>&1; then
  echo "xcrun not found." >&2
  exit 1
fi

ZIP_PATH="${APP_PATH%.app}.zip"

sign_one() {
  local target="$1"
  echo "Signing: $target"
  codesign --force --options runtime --timestamp --sign "$MACOS_CODESIGN_IDENTITY" "$target"
}

echo "Signing embedded Mach-O files..."
while IFS= read -r target; do
  sign_one "$target"
done < <(
  find "$APP_PATH/Contents/Frameworks" "$APP_PATH/Contents/MacOS" -type f 2>/dev/null | while IFS= read -r file; do
    if file "$file" | rg -q 'Mach-O'; then
      printf '%s\n' "$file"
    fi
  done
)

echo "Signing app bundle..."
codesign --force --deep --options runtime --timestamp --sign "$MACOS_CODESIGN_IDENTITY" "$APP_PATH"

echo "Verifying codesign..."
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

echo "Creating notarization archive: $ZIP_PATH"
/usr/bin/ditto -c -k --keepParent "$APP_PATH" "$ZIP_PATH"

submit_notarization() {
  local archive="$1"
  if [[ -n "${MACOS_NOTARYTOOL_PROFILE:-}" ]]; then
    xcrun notarytool submit "$archive" --keychain-profile "$MACOS_NOTARYTOOL_PROFILE" --wait
    return
  fi
  if [[ -n "${MACOS_NOTARY_APPLE_ID:-}" && -n "${MACOS_NOTARY_TEAM_ID:-}" && -n "${MACOS_NOTARY_PASSWORD:-}" ]]; then
    xcrun notarytool submit "$archive" \
      --apple-id "$MACOS_NOTARY_APPLE_ID" \
      --team-id "$MACOS_NOTARY_TEAM_ID" \
      --password "$MACOS_NOTARY_PASSWORD" \
      --wait
    return
  fi
  echo "Skipping notarization: no notarytool credentials configured."
  return 0
}

if submit_notarization "$ZIP_PATH"; then
  if [[ -n "${MACOS_NOTARYTOOL_PROFILE:-}" || ( -n "${MACOS_NOTARY_APPLE_ID:-}" && -n "${MACOS_NOTARY_TEAM_ID:-}" && -n "${MACOS_NOTARY_PASSWORD:-}" ) ]]; then
    echo "Stapling notarization ticket..."
    xcrun stapler staple "$APP_PATH"
    echo "Assessing Gatekeeper..."
    spctl -a -vv "$APP_PATH"
  fi
fi

echo "Signed app ready: $APP_PATH"
