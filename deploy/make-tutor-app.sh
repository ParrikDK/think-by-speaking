#!/usr/bin/env bash
# Builds "Tutor Server.app" into ~/Applications — a double-clickable
# control app for the backend (start/stop/restart/status/logs/dashboard).
# Re-run after changing deploy/tutor-app.applescript or the icon.
#
#   ./deploy/make-tutor-app.sh        # build (or rebuild) the app
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_NAME="Tutor Server"
APP_DIR="$HOME/Applications/$APP_NAME.app"
SRC_ICON="$PROJECT_DIR/frontend/public/icons/icon-512.png"

if [ ! -f "$SRC_ICON" ]; then
  echo "Icon not found at $SRC_ICON — build with a placeholder instead."
  SRC_ICON=""
fi

# 1. Compile the AppleScript with the real project path embedded.
mkdir -p "$HOME/Applications"
sed "s|PROJECT_DIR_PLACEHOLDER|$PROJECT_DIR|" "$PROJECT_DIR/deploy/tutor-app.applescript" >/tmp/tutor-app.applescript
osacompile -o "$APP_DIR" /tmp/tutor-app.applescript

# 2. Custom icon (512px PNG → .icns).
if [ -n "$SRC_ICON" ]; then
  ICONSET="/tmp/tutor-icon.iconset"
  rm -rf "$ICONSET" && mkdir -p "$ICONSET"
  for s in 16 32 128 256 512; do
    sips -z "$s" "$s" "$SRC_ICON" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
    sips -z "$((s * 2))" "$((s * 2))" "$SRC_ICON" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o /tmp/tutor.icns
  cp /tmp/tutor.icns "$APP_DIR/Contents/Resources/applet.icns"
fi

chmod -R u+w "$APP_DIR"
echo "Built $APP_DIR"
echo "Double-click it (or drag to the Dock) to control the tutor server."
