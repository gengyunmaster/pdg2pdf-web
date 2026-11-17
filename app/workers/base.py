"""Converter backends (worker interface).

A converter turns an extracted PDG book directory into a single PDF file.
Phase A: WinePdg2PicConverter drives the original freeware under Wine.
Phase B: a self-developed engine will implement the same interface.
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..archives import Extraction


class Converter(Protocol):
    name: str

    async def convert(self, extracted: Extraction, out_dir: Path) -> Path:
        """Produce a PDF at out_dir and return its path. Raise on failure."""
        ...
