"""Corpus analysis for the self-developed engine.

For every book archive in a directory:
  1. extract it (same code path as the service),
  2. sniff every page file's payload type,
  3. compare against the reference PDF produced by the wrapper backend
     (given in a parallel directory) to locate payload bytes inside the
     .pdg containers — revealing the proprietary header layout.

Usage:
    python3 -m scripts.analyze_corpus <inbox_dir> <oracle_pdf_dir> [--books N]
"""
from __future__ import annotations

import sys
import tempfile
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.archives import extract_any, find_pdg_files, load_passwords  # noqa: E402
from engine.pdgspec import sniff_file  # noqa: E402
from scripts.pdfimg import extract_images  # noqa: E402


WORDLIST = Path(__file__).resolve().parent.parent / "wordlists" / "archive-passwords.txt"


def analyze_book(archive: Path, tmp: Path) -> dict:
    dest = tmp / archive.stem
    ext = extract_any(archive, dest, passwords=load_passwords(WORDLIST))
    stats = Counter()
    page_kinds: list[tuple[Path, str | None]] = []
    for p in find_pdg_files(dest):
        kind = sniff_file(p)
        stats[kind or "unknown"] += 1
        page_kinds.append((p, kind))
    return {"archive": archive.name, "stats": stats, "pages": page_kinds,
            "extract_dir": dest}


def locate_payloads(book: dict, oracle_pdf: Path | None) -> list[dict]:
    """Find each oracle image stream inside its source .pdg file."""
    findings = []
    if oracle_pdf is None or not oracle_pdf.exists():
        return findings
    imgs = extract_images(oracle_pdf.read_bytes())
    pages = sorted(book["pages"], key=lambda t: t[0].name)
    # match by order; counts should agree
    for (path, kind), im in zip(pages, imgs):
        data = path.read_bytes()
        off = data.find(im.raw[:64]) if len(im.raw) >= 64 else -1
        if off < 0 and im.raw:
            off = data.find(im.raw[:16])
        findings.append({
            "file": path.name, "kind": kind, "filter": im.filter,
            "file_size": len(data), "stream_len": len(im.raw),
            "payload_offset": off,
            "header_hex": data[:off].hex() if 0 < off <= 64 else
                          (data[:32].hex() if off <= 0 else ""),
            "oracle_wh": (im.width, im.height),
        })
    return findings


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    inbox = Path(argv[1])
    oracle_dir = Path(argv[2])
    only = None
    if "--books" in argv:
        only = int(argv[argv.index("--books") + 1])
    import json
    oracle_by_name: dict[str, Path] = {}
    for jf in oracle_dir.glob("*.json"):
        try:
            name = json.loads(jf.read_text(encoding="utf-8")).get("filename")
        except Exception:  # noqa: BLE001
            continue
        if name:
            pdf = jf.with_suffix(".pdf")
            if pdf.exists():
                oracle_by_name[name] = pdf

    total = Counter()
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        books = sorted(inbox.iterdir())
        for i, arch in enumerate(books):
            if only and i >= only:
                break
            try:
                book = analyze_book(arch, tmp)
            except Exception as exc:  # noqa: BLE001
                print(f"[{arch.name}] extract failed: {exc}")
                continue
            total.update(book["stats"])
            print(f"[{arch.name}] {dict(book['stats'])}")
            oracle = oracle_by_name.get(arch.name)
            if oracle is None:
                continue
            findings = locate_payloads(book, oracle)
            seen_offsets = {}
            for f in findings[:400]:
                key = (f["kind"], f["filter"], f["payload_offset"])
                seen_offsets[key] = seen_offsets.get(key, 0) + 1
            interesting = {k: v for k, v in seen_offsets.items()
                           if k[2] is not None and k[2] >= 0}
            if interesting:
                print(f"    payload offsets (kind, filter, offset): count")
                for k, v in sorted(interesting.items(),
                                   key=lambda kv: -kv[1])[:6]:
                    print(f"      {k}: {v}")
                sample = next(f for f in findings
                              if f["payload_offset"] not in (None, -1)
                              and f["payload_offset"] <= 64)
                print(f"    sample header ({sample['file']}): "
                      f"{sample['header_hex']}")
                print(f"    oracle page size: {sample['oracle_wh']}")
    print(f"\nTOTAL payload distribution over corpus: {dict(total)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
