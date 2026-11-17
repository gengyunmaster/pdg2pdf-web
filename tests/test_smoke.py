"""Stdlib-only smoke tests (no FastAPI/Wine needed).

Run: python3 -m unittest discover -s tests
"""
from __future__ import annotations

import asyncio
import tempfile
import unittest
import zipfile
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.archives import (  # noqa: E402
    extract_any, find_pdg_files, load_passwords, sniff_format,
)
from app.workers.echo import EchoConverter  # noqa: E402


class SniffFormatTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = Path(self._tmp.name)

    def test_zip(self):
        p = Path(self._tmp.name) / "a.zip"
        with zipfile.ZipFile(p, "w") as zf:
            zf.writestr("x.txt", "hi")
        self.assertEqual(sniff_format(p), "zip")

    def test_rar_and_7z_magics(self):
        d = Path(self._tmp.name)
        rar = d / "a.rar"; rar.write_bytes(b"Rar!\x1a\x07\x01\x00" + b"\x00" * 20)
        s7z = d / "a.7z"; s7z.write_bytes(b"7z\xbc\xaf\x27\x1c" + b"\x00" * 20)
        self.assertEqual(sniff_format(rar), "rar")
        self.assertEqual(sniff_format(s7z), "7z")

    def test_unknown(self):
        p = Path(self._tmp.name) / "a.txt"
        p.write_text("hello")
        self.assertIsNone(sniff_format(p))


class PasswordListTest(unittest.TestCase):
    def test_load(self):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write("# comment\n\nfoo\n  bar  \n")
        self.assertEqual(load_passwords(Path(f.name)), ["foo", "bar"])
        self.assertEqual(load_passwords(None), [])
        self.assertEqual(load_passwords(Path("/nonexistent")), [])


class ExtractAndEchoTest(unittest.TestCase):
    def test_zip_roundtrip_with_echo_backend(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            z = d / "book.zip"
            with zipfile.ZipFile(z, "w") as zf:
                zf.writestr("bok001.pdg", b"\x00" * 32)
                zf.writestr("000001.pdg", b"\x01" * 32)
            ext = extract_any(z, d / "out", passwords=[])
            self.assertEqual(ext.fmt, "zip")
            self.assertEqual(ext.file_count, 2)
            self.assertEqual(len(find_pdg_files(ext.extract_dir)), 2)

            pdf = asyncio.run(EchoConverter().convert(ext, d / "res"))
            self.assertTrue(pdf.read_bytes().startswith(b"%PDF-1.4"))


if __name__ == "__main__":
    unittest.main()
