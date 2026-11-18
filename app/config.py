"""Runtime configuration, overridable via environment variables."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("PDG2PDF_DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
JOB_DIR = DATA_DIR / "jobs"
RESULT_DIR = DATA_DIR / "results"
WORK_DIR = DATA_DIR / "work"

# Optional word list for encrypted archives (one password per line).
# Defaults to the bundled community-collected list; point this variable at
# your own file to override it.
DEFAULT_WORDLIST = BASE_DIR / "wordlists" / "archive-passwords.txt"
PASSWORD_LIST_FILE = (
    Path(os.environ["PDG2PDF_PASSWORD_LIST"])
    if os.environ.get("PDG2PDF_PASSWORD_LIST")
    else DEFAULT_WORDLIST
)

MAX_UPLOAD_BYTES = int(os.environ.get("PDG2PDF_MAX_UPLOAD_MB", "2048")) * 1024 * 1024

# "auto" (native engine, Wine fallback), "native", "wine_pdg2pic",
# or "echo" (self-test backend, no Wine).
CONVERTER_BACKEND = os.environ.get("PDG2PDF_CONVERTER", "auto")

# Path to the deployer-provided Pdg2Pic executable (BYOB, not shipped here).
PDG2PIC_EXE = Path(os.environ.get("PDG2PIC_EXE", "/srv/vendor/Pdg2Pic.exe"))


def ensure_dirs() -> None:
    for d in (DATA_DIR, UPLOAD_DIR, JOB_DIR, RESULT_DIR, WORK_DIR):
        d.mkdir(parents=True, exist_ok=True)
