"""Engine orchestration: a folder of PDG pages -> one PDF.

Milestone 1 supports payloads that are complete image formats (JPEG, PNG).
CCITT/JPEG2000/DjVu/TIFF payloads and text-type (ZIP) books raise
UnsupportedPayload so the caller can fall back to the wrapper backend.
"""
from __future__ import annotations

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


def _load_page(path: Path) -> Page:
    kind = sniff_file(path)
    data = path.read_bytes()
    if kind == "jpeg":
        w, h, dpi = jpeg_info(data)
        return Page(w, h, dpi, "/DeviceRGB", 8, data, "/DCTDecode")
    if kind == "png":
        w, h, dpi, cs, raw = png_decode(data)
        return Page(w, h, dpi, cs, 8, zlib.compress(raw), "/FlateDecode")
    raise UnsupportedPayload(path, kind)


def convert_book(src_dir: Path, out_pdf: Path) -> int:
    pages_src = list_pages(src_dir)
    if not pages_src:
        raise UnsupportedPayload(src_dir, None)
    pages: list[Page] = []
    for p in pages_src:
        pages.append(_load_page(p))
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
