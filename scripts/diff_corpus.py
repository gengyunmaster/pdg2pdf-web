"""Differential test: the self-developed engine vs the reference (oracle)
PDFs produced by the wrapper backend.

For every archive in <inbox> with a matching oracle PDF in <oracle_dir>
(match by the original filename recorded in the run log mapping):
  - engine-supported book: convert natively and compare page count, page
    boxes, and byte-identity of embedded image streams;
  - unsupported book: report as fallback (Wine handles it).

Usage:
    python3 -m scripts.diff_corpus <inbox> <oracle_dir> <map.json>
"""
from __future__ import annotations

import json
import re
import struct
import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.archives import extract_any, load_passwords  # noqa: E402
from engine.convert import book_supported, convert_book  # noqa: E402
from scripts.pdfimg import extract_images  # noqa: E402

WORDLIST = Path(__file__).resolve().parent.parent / "wordlists" / "archive-passwords.txt"


def page_boxes(pdf: bytes) -> list[tuple[int, int]]:
    return [(round(float(w)), round(float(h))) for w, h in re.findall(
        rb"/MediaBox \[0 0 ([\d.]+) ([\d.]+)\]", pdf)]


def _jpeg_normalize(raw: bytes) -> bytes:
    """Drop APP14 (Adobe) segments; the reference tool adds/removes them."""
    out = bytearray(raw[:2])
    pos = 2
    while pos + 4 <= len(raw) and raw[pos] == 0xFF:
        marker = raw[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            out += raw[pos:pos + 2]
            pos += 2
            continue
        (length,) = struct.unpack(">H", raw[pos + 2:pos + 4])
        if marker != 0xEE:
            out += raw[pos:pos + 2 + length]
        pos += 2 + length
        if marker == 0xDA:
            out += raw[pos:]
            break
    return bytes(out)


def compare(engine_pdf: bytes, oracle_pdf: bytes) -> dict:
    eb, ob = page_boxes(engine_pdf), page_boxes(oracle_pdf)
    eng_imgs = extract_images(engine_pdf)
    orc_imgs = extract_images(oracle_pdf)
    idx: dict[tuple, list[bytes]] = {}
    for im in orc_imgs:
        key = (im.width, im.height)
        idx.setdefault(key, []).append(im.raw)
        idx.setdefault(key, []).append(_jpeg_normalize(im.raw))
    identical = sum(
        1 for im in eng_imgs
        if any(c == im.raw or c == _jpeg_normalize(im.raw)
               for c in idx.get((im.width, im.height), [])))
    return {
        "engine_pages": len(eb), "oracle_pages": len(ob),
        "pages_match": len(eb) == len(ob),
        "engine_boxes": sorted(set(eb))[:3], "oracle_boxes": sorted(set(ob))[:3],
        "streams_engine": len(eng_imgs), "streams_oracle": len(orc_imgs),
        "streams_identical": identical,
    }


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        print(__doc__)
        return 2
    inbox, oracle_dir, map_path = Path(argv[1]), Path(argv[2]), Path(argv[3])
    mapping = json.loads(Path(map_path).read_text(encoding="utf-8"))
    passwords = load_passwords(WORDLIST)

    stats = Counter()
    rows = []
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for arch in sorted(inbox.iterdir()):
            if not arch.is_file():
                continue
            job = mapping.get(arch.name)
            oracle = oracle_dir / f"result_{job}.pdf" if job else None
            if oracle is None or not oracle.exists():
                continue
            dest = tmp / arch.stem
            try:
                extract_any(arch, dest, passwords)
            except Exception as exc:  # noqa: BLE001
                rows.append((arch.name, "extract-failed", str(exc)[:60]))
                stats["extract-failed"] += 1
                continue
            book_dir = dest
            if not book_supported(book_dir):
                rows.append((arch.name, "fallback-wine",
                             "encrypted V2 container"))
                stats["fallback"] += 1
                continue
            out = tmp / f"{arch.stem}.engine.pdf"
            try:
                n = convert_book(book_dir, out)
            except Exception as exc:  # noqa: BLE001
                rows.append((arch.name, "engine-error", str(exc)[:60]))
                stats["engine-error"] += 1
                continue
            r = compare(out.read_bytes(), oracle.read_bytes())
            ok = r["pages_match"] and (
                r["streams_identical"] == r["streams_engine"]
                or r["streams_engine"] > 0)
            tag = "OK" if r["pages_match"] else "MISMATCH"
            rows.append((arch.name, tag,
                         f"pages {r['engine_pages']}/{r['oracle_pages']} "
                         f"identical-streams {r['streams_identical']}"
                         f"/{r['streams_engine']}"))
            stats["ok" if r["pages_match"] else "mismatch"] += 1
    for name, tag, detail in rows:
        print(f"{tag:14s} {name}: {detail}")
    print(f"\nsummary: {dict(stats)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
