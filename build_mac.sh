#!/usr/bin/env bash
# Build AI Image Caption Pro for macOS → dist/AI Image Caption Pro.app → AI-Image-Caption-Pro-mac.dmg
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="AI Image Caption Pro"
DMG_NAME="AI-Image-Caption-Pro-mac.dmg"

# Build entirely in /tmp — external volumes cause codesign/xattr failures on macOS Sequoia+
BUILD_TMP="$(mktemp -d /tmp/aicp_build.XXXXXX)"
WORK_DIR="$BUILD_TMP/work"
DIST_DIR="$BUILD_TMP/dist"
echo "==> Build workspace: $BUILD_TMP"
echo "==> App will be output to: $DIST_DIR/$APP_NAME.app"

echo "==> Installing dependencies"
pip install -r "$PROJECT_DIR/requirements.txt" pyinstaller -q

echo "==> Bundling ExifTool"
if command -v exiftool &>/dev/null; then
    cp "$(which exiftool)" "$PROJECT_DIR/bin/exiftool"
    chmod +x "$PROJECT_DIR/bin/exiftool"
fi

echo "==> Running PyInstaller (building in $BUILD_TMP)"
cd "$PROJECT_DIR"
pyinstaller \
    --workpath "$WORK_DIR" \
    --distpath "$DIST_DIR" \
    AIImageCaptionPro.spec

echo "==> Build complete!"
echo "==> App location: $DIST_DIR/$APP_NAME.app"
echo ""
echo "    To install:  ditto \"$DIST_DIR/$APP_NAME.app\" /Applications/$APP_NAME.app"
echo "    To test now: open \"$DIST_DIR/$APP_NAME.app\""
echo ""
echo "$DIST_DIR/$APP_NAME.app" > /tmp/aicp_last_build.txt

echo "==> Creating DMG (requires create-dmg: brew install create-dmg)"
if command -v create-dmg &>/dev/null; then
    create-dmg \
        --volname "$APP_NAME" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --app-drop-link 450 185 \
        "$PROJECT_DIR/$DMG_NAME" \
        "$DIST_DIR/$APP_NAME.app"
    echo "==> DMG: $PROJECT_DIR/$DMG_NAME"
fi
