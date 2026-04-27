#!/usr/bin/env bash
# Build AI Image Caption Pro for Linux → dist/AIImageCaptionPro/ → AIImageCaptionPro-linux.tar.gz
set -euo pipefail

echo "==> Installing Python dependencies"
pip install -r requirements.txt pyinstaller

echo "==> Locating ExifTool"
if command -v exiftool &>/dev/null; then
    cp "$(which exiftool)" bin/exiftool
    chmod +x bin/exiftool
    echo "    Bundled system exiftool → bin/exiftool"
else
    echo "    WARNING: exiftool not found. Install: apt install libimage-exiftool-perl"
fi

echo "==> Running PyInstaller"
pyinstaller \
    --name "AIImageCaptionPro" \
    --windowed \
    --onedir \
    --add-data "assets:assets" \
    --add-binary "bin/exiftool:bin" \
    --hidden-import "app.core.agent" \
    --hidden-import "app.core.captioner" \
    --hidden-import "app.core.exiftool" \
    --hidden-import "app.core.job_db" \
    --hidden-import "app.models" \
    --hidden-import "app.ui.main_window" \
    --hidden-import "app.ui.drop_panel" \
    --hidden-import "app.ui.queue_panel" \
    --hidden-import "app.ui.quick_settings_panel" \
    --hidden-import "app.ui.status_bar" \
    --hidden-import "app.ui.progress_panel" \
    --hidden-import "app.ui.settings_dialog" \
    --hidden-import "app.ui.style" \
    --hidden-import "app.ui.floating_window" \
    --hidden-import "app.ui.tray" \
    --exclude-module "PIL" \
    --exclude-module "Pillow" \
    --exclude-module "numpy" \
    main.py

echo "==> Packaging tarball"
tar -czf AIImageCaptionPro-linux.tar.gz -C dist AIImageCaptionPro
echo "==> Done: AIImageCaptionPro-linux.tar.gz"
echo "    Run with: ./dist/AIImageCaptionPro/AIImageCaptionPro"
