"""Engine orchestration: a folder of PDG pages -> one PDF.

Milestone 1 supports payloads that are complete image formats (JPEG, PNG).
CCITT/JPEG2000/DjVu/TIFF payloads and text-type (ZIP) books raise
UnsupportedPayload so the caller can fall back to the wrapper backend.
"""
from __future__ import annotations

import struct
import sys
import zlib
from pathlib import Path

from .imgdec import UnsupportedImage, jpeg_info, png_decode
from .pdfdoc import Page, write_pdf
from .pdgspec import list_pages, sniff_file


class UnsupportedPayload(Exception):
    def __init__(self, path: Path, kind: str | None):
        self.path = path
        self.kind = kind
        super().__init__(f"unsupported payload {kind or 'unknown'}: {path.name}")


def _strip_app14(data: bytes) -> bytes:
    """Remove APP14 (Adobe) segments, as the reference tool does when
    embedding JPEGs into PDF."""
    out = bytearray(data[:2])
    pos = 2
    while pos + 4 <= len(data) and data[pos] == 0xFF:
        marker = data[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            out += data[pos:pos + 2]
            pos += 2
            continue
        (length,) = struct.unpack_from(">H", data, pos + 2)
        seg = data[pos:pos + 2 + length]
        if marker != 0xEE:
            out += seg
        pos += 2 + length
        if marker == 0xDA:
            out += data[pos:]
            break
    return bytes(out)


def _load_page(path: Path) -> Page:
    kind = sniff_file(path)
    data = path.read_bytes()
    if kind == "jpeg":
        w, h, dpi = jpeg_info(data)
        return Page(w, h, dpi, "/DeviceRGB", 8,
                    _strip_app14(data), "/DCTDecode")
    if kind == "png":
        w, h, dpi, cs, bits, raw = png_decode(data)
        return Page(w, h, dpi, cs, bits, zlib.compress(raw), "/FlateDecode")
    raise UnsupportedPayload(path, kind)




def _normalize_width(pages: list[Page]) -> None:
    """Scale per-page dpi so every page has the same width in points
    (the reference tool keeps one page width per book)."""
    if not pages:
        return
    max_w = max(pg.width_px * 72.0 / pg.dpi for pg in pages)
    for pg in pages:
        pg.dpi = pg.width_px * 72.0 / max_w


def convert_book(src_dir: Path, out_pdf: Path) -> int:
    pages_src = list_pages(src_dir)
    if not pages_src:
        raise UnsupportedPayload(src_dir, None)
    pages: list[Page] = []
    for p in pages_src:
        pages.append(_load_page(p))
    _normalize_width(pages)
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_pdf.write_bytes(write_pdf(pages))
    return len(pages)


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print("usage: python -m engine.convert <book_dir> <out.pdf>",
              file=sys.stderr)
        return 2
    try:
        n = convert_book(Path(argv[1]), Path(argv[2]))
    except (UnsupportedPayload, UnsupportedImage) as exc:
        print(f"engine: {exc}", file=sys.stderr)
        return 1
    print(f"engine: {n} pages -> {argv[2]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
