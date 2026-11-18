"""Worker backends.

- echo: self-test backend (no dependencies)
- wine_pdg2pic: Phase A wrapper around the original freeware under Wine
- native: Phase B self-developed engine
"""
from .base import Converter
from .echo import EchoConverter
from .native_engine import NativeEngineConverter
from .wine_pdg2pic import WinePdg2PicConverter

_BACKENDS = {c.name: c for c in (
    EchoConverter, WinePdg2PicConverter, NativeEngineConverter,
)}


def get_converter(name: str) -> Converter:
    if name not in _BACKENDS:
        raise ValueError(f"unknown converter backend: {name}")
    return _BACKENDS[name]()


__all__ = [
    "Converter", "EchoConverter", "WinePdg2PicConverter",
    "NativeEngineConverter", "get_converter",
]
