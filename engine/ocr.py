"""OCR hidden-text layer via the Tesseract CLI (optional feature).

Enabled per conversion (web UI checkbox) or globally (PDG2PDF_OCR=1).
Requires tesseract (+ chi_sim/eng packs) and poppler-utils at runtime;
pages are rendered to bitmap with pdftoppm so every payload type (JPEG,
PNG, G4) works without an in-process JPEG decoder. When the tools are
missing the page is emitted without a text layer rather than failing.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .pdfdoc import Page, write_pdf


@dataclass
class Word:
    x: float          # pt
    y: float
    size: float
    text: str


def _render_gray(page: Page, tmpdir: str) -> Path | None:
    """Rasterize the page via poppler; returns the PGM path."""
    if not shutil.which("pdftoppm"):
        return None
    pdf_path = Path(tmpdir) / "page.pdf"
    pdf_path.write_bytes(write_pdf([page]))
    prefix = Path(tmpdir) / "render"
    proc = subprocess.run(
        ["pdftoppm", "-r", str(max(72, page.dpi)), "-gray", "-png",
         str(pdf_path), str(prefix)],
        capture_output=True, timeout=180,
    )
    if proc.returncode != 0:
        return None
    outs = sorted(glob.glob(str(prefix) + "*.png"))
    return Path(outs[0]) if outs else None


def _tsv_words(tsv: str, w_px: int, h_px: int, w_pt: float,
               h_pt: float) -> list[Word]:
    sx, sy = w_pt / w_px, h_pt / h_px
    out: list[Word] = []
    for line in tsv.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        try:
            # TSV columns: 0 level,1 page,2 block,3 par,4 line,5 word,
            # 6 left, 7 top, 8 width, 9 height, 10 conf, 11 text
            left, top, width, height = (int(f[6]), int(f[7]),
                                        int(f[8]), int(f[9]))
        except ValueError:
            continue
        out.append(Word(left * sx,
                        h_pt - (top + height) * sy,
                        max(4.0, height * sy),
                        f[11].strip()))
    return out


def _escape_gbk(text: str) -> bytes:
    raw = text.encode("gbk", "replace")
    raw = raw.replace(b"\\", b"\\\\")
    raw = raw.replace(b"(", b"\\(")
    raw = raw.replace(b")", b"\\)")
    return raw


def ocr_page(page: Page, langs: str = "chi_sim+eng") -> bytes | None:
    """Return PDF content-stream bytes for the hidden text layer, or
    None when the tools are unavailable or produced nothing."""
    if not shutil.which("tesseract"):
        return None
    w_pt = page.width_px * 72.0 / page.dpi
    h_pt = page.height_px * 72.0 / page.dpi
    try:
        with tempfile.TemporaryDirectory() as tmp:
            img = _render_gray(page, tmp)
            if img is None:
                return None
            proc = subprocess.run(
                ["tesseract", str(img), "stdout", "-l", langs, "tsv"],
                capture_output=True, text=True, timeout=300,
            )
            if proc.returncode != 0:
                return None
            words = _tsv_words(proc.stdout, page.width_px,
                               page.height_px, w_pt, h_pt)
    except Exception:
        return None
    if not words:
        return None
    parts = ["BT", "/F1 10 Tf", "3 Tr"]
    for wd in words:
        parts.append(f"1 0 0 1 {wd.x:.1f} {wd.y:.1f} Tm {wd.size:.1f} Tf "
                     f"({_escape_gbk(wd.text)}) Tj")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")
