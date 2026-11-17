"""Self-test backend: emits a minimal valid one-page PDF.

Used to exercise the whole web pipeline (upload -> queue -> convert ->
download) on machines without Wine or Pdg2Pic.
"""
from __future__ import annotations

from pathlib import Path

from ..archives import Extraction, find_pdg_files


def _build_blank_pdf() -> bytes:
    objs = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_pos = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<</Size {len(objs)+1}/Root 1 0 R>>\n"
            f"startxref\n{xref_pos}\n%%EOF\n").encode()
    return bytes(out)


class EchoConverter:
    name = "echo"

    async def convert(self, extracted: Extraction, out_dir: Path) -> Path:
        pdg = find_pdg_files(extracted.extract_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        pdf = out_dir / "result.pdf"
        pdf.write_bytes(_build_blank_pdf())
        pdf.with_suffix(".meta.txt").write_text(
            f"echo backend\nsource={extracted.source.name}\n"
            f"format={extracted.fmt}\npassword_used={extracted.password!r}\n"
            f"files={extracted.file_count}\npdg={len(pdg)}\n",
            encoding="utf-8",
        )
        return pdf
