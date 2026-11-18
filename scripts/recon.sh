#!/bin/sh
# Reconnaissance runbook: inspect the Pdg2Pic main dialog under Wine/Xvfb.
#
# Usage (image built as pdg2pdf-web:dev, Pdg2Pic mounted at /srv/vendor):
#   sh scripts/recon.sh
#
# Steps:
#   1. start Xvfb
#   2. launch Pdg2Pic.exe via Wine (background)
#   3. dump all top-level windows, then child controls of the Pdg2Pic window
#   4. leave the container shell available for interactive probing
set -e

export WINEDEBUG=-1
Xvfb :99 -screen 0 1024x768x16 &
XVFB_PID=$!
sleep 1
export DISPLAY=:99

wine "$PDG2PIC_EXE" &
APP_PID=$!
sleep 8

echo "=== top-level windows ==="
wine /srv/driver/windowdump.exe || true
echo "=== Pdg2Pic window + child controls ==="
wine /srv/driver/windowdump.exe -c Pdg2Pic || true
echo "=== windows again (after any lazy dialogs) ==="
wine /srv/driver/windowdump.exe || true

echo "recon done; killing app ($APP_PID) and Xvfb ($XVFB_PID)"
kill "$APP_PID" "$XVFB_PID" 2>/dev/null || true
wineserver -k 2>/dev/null || true
exit 0
