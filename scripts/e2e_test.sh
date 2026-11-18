#!/bin/sh
# End-to-end smoke test of the full stack inside the container.
# Requires: image pdg2pdf-web:dev, Pdg2Pic mounted at /opt/orig/Pdg2Pic.exe,
# sample archive at $BOOK_ZIP.
set -e
BOOK_ZIP="${BOOK_ZIP:-/opt/orig/fakebook.zip}"

cp /opt/orig/Pdg2Pic.exe /srv/vendor/Pdg2Pic.exe

Xvfb :99 -screen 0 1024x768x16 &
sleep 2
export DISPLAY=:99
export PDG2PDF_CONVERTER=wine_pdg2pic
export PDG2PIC_EXE=/srv/vendor/Pdg2Pic.exe
export WINEDEBUG=-1

uvicorn app.main:app --host 127.0.0.1 --port 8000 &
WEB=$!
trap 'kill $WEB 2>/dev/null; wineserver -k 2>/dev/null || true' EXIT
sleep 4

JOB=$(curl -s -F "file=@${BOOK_ZIP}" http://127.0.0.1:8000/api/jobs | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])')
echo "job: $JOB"

for i in $(seq 1 40); do
    STATUS=$(curl -s "http://127.0.0.1:8000/api/jobs/$JOB")
    echo "$STATUS" | grep -q '"status": "done"' && break
    echo "$STATUS" | grep -q '"status": "error"' && { echo "$STATUS"; exit 1; }
    sleep 5
done

curl -s -o /tmp/result.pdf "http://127.0.0.1:8000/api/jobs/$JOB/download"
head -c 8 /tmp/result.pdf | grep -q "%PDF" && echo "E2E OK: /tmp/result.pdf ($(wc -c < /tmp/result.pdf) bytes)" || { echo "E2E FAIL: not a PDF"; exit 1; }
