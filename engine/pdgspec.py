"""Payload sniffing and PDG reading-order rules (docs/FORMAT.md sec.2,4)."""
from __future__ import annotations

import re
from pathlib import Path

MAGICS: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "jpeg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
    (b"\x00\x00\x00\x0cjP  ", "jp2"),
    (b"\xff\x4f\xff\x51", "jpx"),          # raw JPEG 2000 codestream
    (b"AT&TFORM", "djvu"),
    (b"%PDF", "pdf"),
    (b"PK\x03\x04", "zip"),
]

PAGE_EXTS = {".pdg", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp",
             ".gif", ".webp", ".jp2", ".djvu"}


def sniff(data: bytes) -> str | None:
    for magic, kind in MAGICS:
        if data.startswith(magic):
            return kind
    return None


def sniff_file(path: Path, peek: int = 16) -> str | None:
    with path.open("rb") as f:
        return sniff(f.read(peek))


_PREFIX_ORDER = {"cov": 0, "bok": 1, "fow": 2, "!": 3, "leg": 4,
                 "app": 6, "bac": 7}
_NUM_RE = re.compile(r"^(\d+)")


def sort_key(name: str):
    """Reading-order key for a PDG page file name (stem, lowercased)."""
    stem = Path(name).stem.lower()
    for prefix, rank in _PREFIX_ORDER.items():
        if stem.startswith(prefix):
            num = stem[len(prefix):]
            return (rank, int(num) if num.isdigit() else 0, stem)
    m = _NUM_RE.match(stem)
    if m:
        return (5, int(m.group(1)), stem)
    return (8, 0, stem)


def is_page_file(path: Path) -> bool:
    return path.suffix.lower() in PAGE_EXTS and path.is_file()


def list_pages(root: Path) -> list[Path]:
    pages = [p for p in root.rglob("*") if is_page_file(p)]
    pages.sort(key=lambda p: sort_key(p.name))
    return pages
