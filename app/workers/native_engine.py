"""Phase B backend: the self-developed engine (see docs/FORMAT.md)."""
from __future__ import annotations

from pathlib import Path

from ..archives import Extraction, find_pdg_files
from ..workers_support import book_root_or_raise


class NativeEngineConverter:
    name = "native"

    async def convert(self, extracted: Extraction, out_dir: Path,
                      ocr: bool = False) -> Path:
        import sys  # noqa: PLC0415

        root = str(Path(__file__).resolve().parents[2])
        if root not in sys.path:
            sys.path.insert(0, root)
        from engine.convert import (  # noqa: PLC0415
            UnsupportedPayload, convert_book,
        )

        from engine.convert import book_supported  # noqa: PLC0415
        from ..workers_support import FallbackToWine  # noqa: PLC0415

        book = book_root_or_raise(extracted)
        if not book_supported(book):
            print("[worker] native: unsupported pages, falling back to wine",
                  flush=True)
            raise FallbackToWine(book)
        result = out_dir / "book.pdf"
        try:
            convert_book(book, result, ocr=ocr or None)
        except UnsupportedPayload as exc:
            raise FallbackToWine(book) from exc
        return result
