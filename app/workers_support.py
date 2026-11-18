"""Shared helper: locate the directory that holds a book's pages."""
from __future__ import annotations

from pathlib import Path

from .archives import Extraction, find_pdg_files


def book_root_or_raise(extracted: Extraction) -> Path:
    pdgs = find_pdg_files(extracted.extract_dir)
    if not pdgs:
        raise RuntimeError("no PDG files found in the archive")
    parents = {p.parent for p in pdgs}
    if len(parents) == 1:
        return parents.pop()
    counts: dict[Path, int] = {}
    for p in pdgs:
        counts[p.parent] = counts.get(p.parent, 0) + 1
    return max(counts, key=counts.get)


class FallbackToWine(Exception):
    """The native engine cannot handle this book; retry with the wrapper."""
