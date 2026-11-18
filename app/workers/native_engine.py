"""Phase B backend: the self-developed engine (see docs/FORMAT.md)."""
from __future__ import annotations

from pathlib import Path

from ..archives import Extraction, find_pdg_files
from ..workers_support import book_root_or_raise


class NativeEngineConverter:
    name = "native"

    async def convert(self, extracted: Extraction, out_dir: Path) -> Path:
        from engine.convert import (  # noqa: PLC0415
            UnsupportedPayload, convert_book,
        )

        book = book_root_or_raise(extracted)
        result = out_dir / "book.pdf"
        try:
            convert_book(book, result)
        except UnsupportedPayload as exc:
            raise RuntimeError(
                f"native engine cannot handle {exc.path.name} "
                f"(payload={exc.kind}); use the wine backend"
            ) from exc
        return result
