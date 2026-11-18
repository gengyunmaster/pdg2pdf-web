"""Engine smoke tests (stdlib only).

Run: python3 -m unittest discover -s tests
"""
from __future__ import annotations

import sys
import tempfile
import unittest
import zlib
import struct
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.convert import UnsupportedPayload, convert_book  # noqa: E402
from engine.imgdec import jpeg_info, png_decode  # noqa: E402
from engine.pdgspec import list_pages, sniff, sort_key  # noqa: E402
from engine.pdfdoc import Page, write_pdf  # noqa: E402


def make_png(w=8, h=4, gray=200):
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    raw = b"".join(b"\x00" + bytes([gray]) * w for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class SniffTest(unittest.TestCase):
    def test_magics(self):
        self.assertEqual(sniff(b"\xff\xd8\xff\xe0" + b"\0" * 9), "jpeg")
        self.assertEqual(sniff(make_png()), "png")
        self.assertEqual(sniff(b"II*\x00" + b"\0" * 12), "tiff")
        self.assertEqual(sniff(b"%PDF-1.4" + b"\0" * 8), "pdf")
        self.assertIsNone(sniff(b"\x00" * 16))


class SortTest(unittest.TestCase):
    def test_reading_order(self):
        names = ["000003.pdg", "cov001.pdg", "!00001.pdg", "000001.pdg",
                 "fow001.pdg", "000002.pdg", "bac001.pdg"]
        ordered = sorted(names, key=sort_key)
        self.assertEqual(ordered[0], "cov001.pdg")
        self.assertEqual(ordered[1], "fow001.pdg")
        self.assertEqual(ordered[2], "!00001.pdg")
        self.assertEqual(ordered[-1], "bac001.pdg")
        self.assertEqual(ordered[3:6],
                         ["000001.pdg", "000002.pdg", "000003.pdg"])


class PngDecodeTest(unittest.TestCase):
    def test_roundtrip(self):
        data = make_png(8, 4, gray=128)
        w, h, dpi, cs, raw = png_decode(data)
        self.assertEqual((w, h), (8, 4))
        self.assertEqual(cs, "/DeviceGray")
        self.assertEqual(len(raw), 8 * 4)
        self.assertEqual(raw[0], 128)


class PdfWriteTest(unittest.TestCase):
    def test_pdf_pages(self):
        pages = [Page(8, 4, 150, "/DeviceGray", 8, b"abcd", "/FlateDecode"),
                 Page(8, 4, 150, "/DeviceGray", 8, b"efgh", "/FlateDecode")]
        pdf = write_pdf(pages)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertEqual(pdf.count(b"/Type /Page "), 2)
        self.assertIn(b"/Count 2", pdf)
        self.assertIn(b"startxref", pdf)


class ConvertBookTest(unittest.TestCase):
    def test_convert_and_unsupported(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "000001.pdg").write_bytes(make_png(8, 4))
            (d / "000002.pdg").write_bytes(make_png(8, 4, gray=100))
            out = d / "out.pdf"
            n = convert_book(d, out)
            self.assertEqual(n, 2)
            self.assertTrue(out.read_bytes().startswith(b"%PDF"))

            (d / "000003.pdg").write_bytes(b"PK\x03\x04" + b"\0" * 20)
            with self.assertRaises(UnsupportedPayload):
                convert_book(d, d / "out2.pdf")


if __name__ == "__main__":
    unittest.main()
