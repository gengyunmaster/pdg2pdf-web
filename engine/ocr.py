"""OCR hidden-text layer via the Tesseract CLI (optional feature).

Enabled with PDG2PDF_OCR=1. Requires tesseract and the language packs
(chi_sim+eng) at runtime; when unavailable the page is emitted without a
text layer rather than failing the conversion.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .pdfdoc import Page


@dataclass
class Word:
    x: float          # pt
    y: float
    size: float
    text: str


def _pgm_bytes(page: Page) -> bytes:
    """Render decoded samples back to a PGM/PPM for tesseract."""
    import zlib
    raw = zlib.decompress(page.stream) if page.filter == "/FlateDecode" \
        else page.stream
    w, h = page.width_px, page.height_px
    if page.bits == 1 and page.colorspace == "/DeviceGray":
        # unpack to 8-bit
        stride = (w + 7) // 8
        out = bytearray(w * h)
        i = 0
        for y in range(h):
            row = raw[y * stride:(y + 1) * stride]
            for x in range(w):
                out[i] = 255 if (row[x // 8] >> (7 - x % 8)) & 1 else 0
                i += 1
        return (b"P5\n%d %d\n255\n" % (w, h)) + bytes(out)
    if page.bits == 8 and page.colorspace == "/DeviceGray":
        return (b"P5\n%d %d\n255\n" % (w, h)) + raw
    if page.bits == 8 and page.colorspace == "/DeviceRGB":
        return (b"P6\n%d %d\n255\n" % (w, h)) + raw
    raise ValueError(f"ocr: unsupported page {page.colorspace}/{page.bits}")


def _tsv_words(tsv: str, w_px: int, h_px: int, w_pt: float,
               h_pt: float) -> list[Word]:
    sx, sy = w_pt / w_px, h_pt / h_px
    out: list[Word] = []
    for line in tsv.splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip():
            continue
        try:
            left, top, width, height = (int(f[7]), int(f[8]),
                                        int(f[9]), int(f[10]))
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
    None when tesseract is unavailable or produced nothing."""
    if not shutil.which("tesseract"):
        return None
    w_pt = page.width_px * 72.0 / page.dpi
    h_pt = page.height_px * 72.0 / page.dpi
    with tempfile.NamedTemporaryFile(suffix=".pgm", delete=False) as tf:
        tf.write(_pgm_bytes(page))
        tmp = tf.name
    try:
        proc = subprocess.run(
            ["tesseract", tmp, "stdout", "-l", langs, "tsv"],
            capture_output=True, text=True, timeout=300,
        )
        if proc.returncode != 0:
            return None
        words = _tsv_words(proc.stdout, page.width_px, page.height_px,
                           w_pt, h_pt)
    except Exception:
        return None
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    if not words:
        return None
    parts = ["BT", "/F1 10 Tf", "3 Tr"]
    for wd in words:
        parts.append(f"1 0 0 1 {wd.x:.1f} {wd.y:.1f} Tm {wd.size:.1f} Tf "
                     f"({_escape_gbk(wd.text)}) Tj")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")
