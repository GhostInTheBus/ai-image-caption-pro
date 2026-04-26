#!/usr/bin/env bash
# dev.sh — auto-restart the app whenever a .py file changes.
# Requires: brew install fswatch
#
# Usage:
#   bash dev.sh
#
# The app relaunches within ~1 second of saving any .py file.

set -euo pipefail
cd "$(dirname "$0")"

APP_PID=""

start_app() {
    python main.py &
    APP_PID=$!
}

stop_app() {
    if [[ -n "$APP_PID" ]] && kill -0 "$APP_PID" 2>/dev/null; then
        kill "$APP_PID"
        wait "$APP_PID" 2>/dev/null || true
    fi
    APP_PID=""
}

cleanup() {
    stop_app
    exit 0
}
trap cleanup INT TERM

if ! command -v fswatch &>/dev/null; then
    echo "Error: fswatch not found. Install it with:"
    echo "  brew install fswatch"
    exit 1
fi

echo "Starting app..."
start_app

echo "Watching app/ and main.py for changes. Ctrl+C to quit."
fswatch \
    --monitor=poll_monitor \
    --recursive \
    --event=Updated \
    --latency=2 \
    --include='.*\.py$' \
    --exclude='.*' \
    app/ main.py \
| while read -r _changed; do
    echo "  → Change detected, restarting..."
    stop_app
    sleep 0.3
    start_app
done
