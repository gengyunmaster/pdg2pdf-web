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
    # the reference tool moves cov002 to the end as the back cover when
    # the book has cov001+cov002, no cov003 and no bacXXX page
    stems = {p.stem.lower() for p in pages}
    if (any(s.startswith("cov001") for s in stems)
            and any(s.startswith("cov002") for s in stems)
            and not any(s.startswith("cov003") for s in stems)
            and not any(s.startswith("bac") for s in stems)):
        cov2 = [p for p in pages if p.stem.lower().startswith("cov002")]
        pages = [p for p in pages if not p.stem.lower().startswith("cov002")]
        pages.extend(cov2)
    return pages


_SECTIONS = {"cov": "封面", "bok": "书名页", "leg": "版权",
             "fow": "前言", "!": "目录", "app": "附录", "bac": "封底"}
# bookmark emission order differs from page reading order
_BKMARK_RANK = {"cov": 0, "bok": 1, "leg": 2, "fow": 3, "!": 4}


def classify(name: str) -> tuple[str, int]:
    """(prefix, number): 'cov',12 / 'bok',1 / '!',5 / 'body',273 ..."""
    stem = Path(name).stem.lower()
    for prefix in ("cov", "bok", "leg", "fow", "app", "bac"):
        if stem.startswith(prefix):
            rest = stem[len(prefix):]
            return prefix, int(rest) if rest.isdigit() else 0
    if stem.startswith("!"):
        rest = stem[1:]
        return "!", int(rest) if rest.isdigit() else 0
    m = re.match(r"^(\d+)", stem)
    if m:
        return "body", int(m.group(1))
    return "other", 0


def default_bookmarks(names: list[str]) -> list[tuple[str, int]]:
    """Flat (title, page_index) bookmarks matching the reference tool's
    no-bookcontents behavior: first page of each named section plus one
    per body page (titled by printed page number)."""
    classes = [classify(n) for n in names]
    out: list[tuple[int, str, int]] = []   # (role_rank, title, page_index)
    seen: set[str] = set()
    for i, (prefix, _num) in enumerate(classes):
        if prefix in _BKMARK_RANK and prefix not in seen:
            out.append((_BKMARK_RANK[prefix], _SECTIONS[prefix], i))
            seen.add(prefix)
    for i, (prefix, num) in enumerate(classes):
        if prefix == "body":
            out.append((5, str(num), i))
    bac_idx = next((i for i, (p, _n) in enumerate(classes) if p == "bac"),
                   None)
    out.append((7, _SECTIONS["bac"], bac_idx if bac_idx is not None
                else len(classes) - 1))
    out.sort(key=lambda t: (t[0], t[2]))
    return [(title, idx) for _rank, title, idx in out]


def parse_bookcontents(path) -> list:
    """Best-effort parser for bookcontents.dat / catalog.dat.

    Line format (no sample in the corpus): indentation (tab or spaces)
    expresses depth; the page number is the last |- or tab-separated
    field. Returns nested OutlineEntry-compatible tuples
    (title, page_index, children).
    """
    from .pdfdoc import OutlineEntry  # local import avoids a cycle

    def make(entries, depth=0):
        out = []
        i = 0
        while i < len(entries):
            d, title, page = entries[i]
            if d < depth:
                break
            if d > depth:
                sub, i = make(entries[i:], d)
                if out:
                    out[-1].children = sub
                continue
            out.append(OutlineEntry(title, page))
            i += 1
        return out, i

    entries = []
    try:
        text = path.read_bytes().decode("gb18030", "replace")
    except OSError:
        return []
    for line in text.replace("\r", "").split("\n"):
        if not line.strip():
            continue
        stripped = line.lstrip("\t ")
        depth = (len(line) - len(stripped))
        depth = line[:len(line) - len(stripped)].count("\t") or depth // 2
        fields = [f.strip() for f in stripped.replace("|", "\t").split("\t")]
        fields = [f for f in fields if f]
        if not fields:
            continue
        try:
            page = int(fields[-1]) - 1
        except ValueError:
            continue
        title = " ".join(fields[:-1]) or fields[-1]
        entries.append((depth, title, page))
    tree, _ = make(entries, 0)
    return tree
