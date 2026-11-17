"""Worker backends."""
from .base import Converter
from .echo import EchoConverter
from .wine_pdg2pic import WinePdg2PicConverter

_BACKENDS = {c.name: c for c in (EchoConverter, WinePdg2PicConverter)}


def get_converter(name: str) -> Converter:
    if name not in _BACKENDS:
        raise ValueError(f"unknown converter backend: {name}")
    return _BACKENDS[name]()


__all__ = ["Converter", "EchoConverter", "WinePdg2PicConverter", "get_converter"]
