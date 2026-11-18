"""Engine orchestration: a folder of PDG pages -> one PDF.

Milestone 1 supports payloads that are complete image formats (JPEG, PNG).
CCITT/JPEG2000/DjVu/TIFF payloads and text-type (ZIP) books raise
UnsupportedPayload so the caller can fall back to the wrapper backend.
"""
from __future__ import annotations

import os
import struct
import sys
import zlib
from pathlib import Path

from .imgdec import UnsupportedImage, jpeg_info, png_decode
from .pdfdoc import OutlineEntry, Page, TextPage, write_pdf
from .pdgspec import default_bookmarks, list_pages, sniff_file


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
        if bits == 1:
            from .ccitt import encode_g4  # noqa: PLC0415
            g4 = encode_g4(raw, w, h)
            parms = f"<< /K -1 /Columns {w} /Rows {h} >>"
            return Page(w, h, dpi, cs, 1, g4, "/CCITTFaxDecode",
                        decode_parms=parms)
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


def book_supported(src_dir: Path) -> bool:
    """True when every page is a self-describing image (jpeg/png). The
    encrypted V2 'HH' container family and DjVu/JP2/TIFF payloads are not
    yet handled by the self-developed engine."""
    from .pdgspec import sniff_file
    pages = list_pages(src_dir)
    if not pages:
        return False
    return all(sniff_file(p) in ("jpeg", "png") for p in pages)




def _bookinfo_lines(src_dir: Path) -> list[str]:
    """BookInfo.dat rendered as plain text lines (GBK ini metadata)."""
    for name in ("BookInfo.dat", "bookinfo.dat"):
        p = src_dir / name
        if p.exists():
            try:
                text = p.read_bytes().decode("gb18030", "replace")
            except OSError:
                return []
            lines = [l.strip() for l in text.replace("\r", "").split("\n")]
            return [l for l in lines if l]
    return []


def convert_book(src_dir: Path, out_pdf: Path,
                 ocr: bool | None = None) -> int:
    if ocr is None:
        ocr = os.environ.get("PDG2PDF_OCR", "") == "1"
    pages_src = list_pages(src_dir)
    if not pages_src:
        raise UnsupportedPayload(src_dir, None)
    pages: list[Page] = []
    for p in pages_src:
        pg = _load_page(p)
        if ocr:
            from .ocr import ocr_page  # noqa: PLC0415
            layer = ocr_page(pg)
            if layer:
                pg.extra_content = layer
        pages.append(pg)
    _normalize_width(pages)
    info = _bookinfo_lines(src_dir)
    if info and pages:
        pages.append(TextPage(info, width_pt=pages[0].width_px * 72.0 / pages[0].dpi,
                              height_pt=pages[0].height_px * 72.0 / pages[0].dpi))
    outlines = [OutlineEntry(title, idx)
                for title, idx in default_bookmarks([p.name for p in pages_src])]
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    out_pdf.write_bytes(write_pdf(pages, outlines=outlines))
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
