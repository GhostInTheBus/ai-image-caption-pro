#!/usr/bin/env bash
# Build AI Photo Caption Pro for Linux → dist/AIPhotoCaptionPro (single directory)
set -euo pipefail

echo "==> Installing system deps (Debian/Ubuntu)"
# sudo apt-get install -y libimage-exiftool-perl python3-dev python3-pip

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
    --name "AIPhotoCaptionPro" \
    --windowed \
    --onedir \
    --add-data "assets:assets" \
    --add-binary "bin/exiftool:bin" \
    --hidden-import "app.ui.floating_window" \
    --hidden-import "app.ui.progress_panel" \
    --hidden-import "app.ui.settings_dialog" \
    --hidden-import "app.ui.tray" \
    --hidden-import "app.core.agent" \
    --hidden-import "app.core.captioner" \
    --hidden-import "app.core.exiftool" \
    --hidden-import "app.core.job_db" \
    --hidden-import "app.models" \
    --exclude-module "PIL" \
    --exclude-module "Pillow" \
    --exclude-module "numpy" \
    main.py

echo "==> Built: dist/AIPhotoCaptionPro/"
echo "    Run with: ./dist/AIPhotoCaptionPro/AIPhotoCaptionPro"
