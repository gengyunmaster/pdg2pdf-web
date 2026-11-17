"""Archive sniffing and extraction (zip / rar / 7z / uvz).

Formats are detected by magic bytes, never by file extension: ".uvz" files
are simply zip or rar archives under the hood. Encrypted archives are opened
by trying every password from a deployer-supplied word list.
"""
from __future__ import annotations

import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

MAGICS: list[tuple[bytes, str]] = [
    (b"PK\x03\x04", "zip"),
    (b"PK\x05\x06", "zip"),          # empty archive
    (b"Rar!\x1a\x07\x00", "rar"),
    (b"Rar!\x1a\x07\x01\x00", "rar"),
    (b"7z\xbc\xaf\x27\x1c", "7z"),
    (b"\x1f\x8b", "gzip"),
]


@dataclass
class Extraction:
    source: Path
    fmt: str
    extract_dir: Path
    password: str | None     # password that worked, or None if not needed
    file_count: int


def sniff_format(path: Path) -> str | None:
    with path.open("rb") as f:
        head = f.read(8)
    for magic, name in MAGICS:
        if head.startswith(magic):
            return name
    return None


def load_passwords(path: Path | None) -> list[str]:
    """One password per line; blank lines and '#' comments are ignored."""
    if not path or not path.exists():
        return []
    out: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def _extract_with_7z(archive: Path, dest: Path, passwords: list[str]) -> str | None:
    """Try 7z with no password, then each password. Returns the working one."""
    attempts: list[str | None] = [None, *passwords]
    for pw in attempts:
        dest.mkdir(parents=True, exist_ok=True)
        cmd = ["7z", "x", "-y", f"-o{dest}", str(archive), f"-p{pw or ''}"]
        proc = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL, timeout=1800,
        )
        if proc.returncode == 0 and any(dest.iterdir()):
            return pw
        shutil.rmtree(dest, ignore_errors=True)
    raise ValueError("archive is encrypted and no password from the list worked")


def _extract_zip_stdlib(archive: Path, dest: Path) -> str | None:
    """Fast path for plain zip archives. Returns None (no password used)."""
    try:
        with zipfile.ZipFile(archive) as zf:
            if any(i.flag_bits & 0x1 for i in zf.infolist()):
                raise ValueError("encrypted entries")  # fall back to 7z loop
            zf.extractall(dest)
        return None
    except (zipfile.BadZipFile, ValueError):
        raise


def extract_any(archive: Path, dest: Path, passwords: list[str]) -> Extraction:
    fmt = sniff_format(archive)
    if fmt is None:
        raise ValueError(f"unrecognized archive format: {archive.name}")
    if fmt == "zip":
        try:
            used = _extract_zip_stdlib(archive, dest)
            count = sum(1 for _ in dest.rglob("*") if _.is_file())
            return Extraction(archive, fmt, dest, used, count)
        except ValueError:
            pass  # encrypted zip -> 7z password loop
    used = _extract_with_7z(archive, dest, passwords)
    count = sum(1 for _ in dest.rglob("*") if _.is_file())
    return Extraction(archive, fmt, dest, used, count)


def find_pdg_files(root: Path) -> list[Path]:
    exts = {".pdg", ".000", ".001", ".002", ".003", ".004", ".005"}
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts]
    files.sort(key=lambda p: str(p).lower())
    return files
