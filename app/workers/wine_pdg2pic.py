"""Phase A backend: drive Pdg2Pic.exe under Wine/Xvfb via the Win32 driver.

The driver program (driver/pgdrive.exe, cross-compiled from driver/pgdrive.c)
finds the Pdg2Pic main window and drives it with Win32 messages only
(WM_SETTEXT / WM_DROPFILES / BM_CLICK) — no coordinate-based automation.
This module is completed in Phase A; see driver/README.md for the design.
"""
from __future__ import annotations

from pathlib import Path

from ..archives import Extraction
from ..config import PDG2PIC_EXE


def write_pdg2pic_ini(path: Path, source_dir: Path, options: dict) -> None:
    """Write Pdg2Pic.ini next to the executable.

    TODO(Phase A): the exact key names must be confirmed empirically by
    diffing an ini produced by the real application after changing settings.
    """
    raise NotImplementedError("ini key layout pending empirical confirmation")


class WinePdg2PicConverter:
    name = "wine_pdg2pic"

    async def convert(self, extracted: Extraction, out_dir: Path) -> Path:
        if not PDG2PIC_EXE.exists():
            raise RuntimeError(
                f"Pdg2Pic.exe not found at {PDG2PIC_EXE}. "
                "Obtain it from the author's distribution page (see README) "
                "or set PDG2PIC_EXE."
            )
        raise NotImplementedError(
            "Wine backend wiring is implemented in Phase A "
            "(driver/pgdrive.c + Xvfb orchestration). "
            "Use PDG2PDF_CONVERTER=echo for now."
        )
