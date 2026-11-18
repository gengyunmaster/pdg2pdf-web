"""Minimal image-only PDF writer (stdlib only)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Page:
    width_px: int
    height_px: int
    dpi: int
    colorspace: str          # /DeviceGray or /DeviceRGB
    bits: int                # 8
    stream: bytes            # image samples (raw) or DCT data
    filter: str              # /FlateDecode or /DCTDecode


def write_pdf(pages: list[Page]) -> bytes:
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(b"")  # pages tree placeholder (object 2)

    page_ids = []
    for pg in pages:
        img = add(
            b"<< /Type /XObject /Subtype /Image "
            + f"/Width {pg.width_px} /Height {pg.height_px} ".encode()
            + f"/ColorSpace {pg.colorspace} /BitsPerComponent {pg.bits} ".encode()
            + f"/Filter {pg.filter} /Length {len(pg.stream)} ".encode()
            + b">>\nstream\n" + pg.stream + b"\nendstream"
        )
        w_pt = pg.width_px * 72.0 / pg.dpi
        h_pt = pg.height_px * 72.0 / pg.dpi
        content = f"0 0 {w_pt:.2f} {h_pt:.2f} cm /Im0 Do\n".encode()
        cont = add(
            f"<< /Length {len(content)} >>\nstream\n".encode()
            + content + b"endstream"
        )
        page_ids.append(add(
            f"<< /Type /Page /Parent 2 0 R ".encode()
            + f"/MediaBox [0 0 {w_pt:.2f} {h_pt:.2f}] ".encode()
            + f"/Resources << /XObject << /Im0 {img} 0 R >> >> ".encode()
            + f"/Contents {cont} 0 R >>".encode()
        ))

    objs[1] = (b"<< /Type /Pages /Kids ["
               + b" ".join(f"{i} 0 R".encode() for i in page_ids)
               + f"] /Count {len(page_ids)} >>".encode())

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs)+1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(out)
