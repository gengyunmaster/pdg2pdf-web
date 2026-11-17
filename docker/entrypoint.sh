#!/bin/sh
# Start Xvfb (headless display for Wine), then the web service.
set -e

if ! pgrep -x Xvfb >/dev/null 2>&1; then
    Xvfb :99 -screen 0 1024x768x16 &
    sleep 1
fi
export DISPLAY=:99

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
