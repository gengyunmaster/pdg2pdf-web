"""Minimal image-only PDF writer with a plain-text appendix page (stdlib)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Page:
    width_px: int
    height_px: int
    dpi: int
    colorspace: str          # /DeviceGray or /DeviceRGB
    bits: int                # 1 or 8
    stream: bytes            # image samples (raw) or DCT data
    filter: str              # /FlateDecode, /DCTDecode or /CCITTFaxDecode
    decode_parms: str | None = None   # e.g. "<< /K -1 /Columns N /Rows M >>"
    extra_content: bytes | None = None  # e.g. OCR hidden-text layer


@dataclass
class TextPage:
    """The BookInfo.dat appendix page (GBK text, STSong-Light)."""
    lines: list[str]
    width_pt: float = 595.0
    height_pt: float = 842.0


@dataclass
class OutlineEntry:
    """A bookmark; children make it nested."""
    title: str                 # unicode
    page_index: int            # 0-based page number
    children: list | None = None


def _utf16_literal(text: str) -> bytes:
    raw = text.encode("utf-16-be", "replace")
    raw = raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")
    return raw


def _text_stream(tp: TextPage) -> bytes:
    """Match the reference layout: 10 pt, x=72, first baseline
    height-79.2, 14 pt leading, one Tm per line, GBK bytes."""
    parts = ["BT", "/F1 10 Tf"]
    y = tp.height_pt - 79.2
    for line in tp.lines[:60]:
        parts.append(f"1 0 0 1 72 {y:.4f} Tm".rstrip("0").rstrip(".")
                     if False else f"1 0 0 1 72 {y:.4f} Tm")
        parts.append(b"(" + _utf16_literal(line) + b")Tj")
        y -= 14
    parts.append("ET")
    head = "\n".join(parts[:2]).encode("latin-1")
    body = b"\n".join(p if isinstance(p, bytes) else p.encode("latin-1")
                       for p in parts[2:])
    return head + b"\n" + body




def _page_height(pg) -> float:
    if isinstance(pg, TextPage):
        return pg.height_pt
    return pg.height_px * 72.0 / pg.dpi


def write_pdf(pages: list[Page | TextPage],
              outlines: list[OutlineEntry] | None = None) -> bytes:
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)

    add(b"<< /Type /Catalog /Pages 2 0 R >>")
    add(b"")  # pages tree placeholder (object 2)
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    cjk_desc = add(
        b"<< /Type /Font /Subtype /CIDFontType0 /BaseFont /STSong-Light "
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (GB1) /Supplement 5 >> "
        b"/FontDescriptor << /Type /FontDescriptor /FontName /STSong-Light "
        b"/Flags 4 /FontBBox [0 -200 1000 900] /ItalicAngle 0 /Ascent 880 "
        b"/Descent -120 /CapHeight 700 /StemV 80 >> >>"
    )
    touni = add(
        b"<< /Length 360 >>
stream
"
        b"/CIDInit /ProcSet findresource begin
"
        b"12 dict begin
"
        b"begincmap
"
        b"/CIDSystemInfo << /Registry (Adobe) /Ordering (UCS) "
        b"/Supplement 0 >> /CMapName /Adobe-Identity-UCS "
        b"/CMapType 2 def
"
        b"1 begincodespacerange
"
        b"<0000> <FFFF>
"
        b"endcodespacerange
"
        b"2 beginbfrange
"
        b"<0000> <D7FF> <0000>
"
        b"<E000> <FFFD> <E000>
"
        b"endbfrange
"
        b"endcmap
"
        b"CMapName currentdict /CMap defineresource pop
"
        b"end
end
"
        b"endstream"
    )
    cjk_font_id = add(
        b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light "
        b"/Encoding /UniGB-UCS2-H /DescendantFonts ["
        + f"{cjk_desc} 0 R".encode()
        + f"] /ToUnicode {touni} 0 R >>".encode()
    )

    page_ids = []
    for pg in pages:
        if isinstance(pg, TextPage):
            content = _text_stream(pg)
            cont = add(
                f"<< /Length {len(content)} >>\nstream\n".encode()
                + content + b"\nendstream"
            )
            page_ids.append(add(
                f"<< /Type /Page /Parent 2 0 R ".encode()
                + f"/MediaBox [0 0 {pg.width_pt:.2f} {pg.height_pt:.2f}] ".encode()
                + f"/Resources << /Font << /F1 {cjk_font_id} 0 R >> >> ".encode()
                + f"/Contents {cont} 0 R >>".encode()
            ))
            continue
        parms = f"/DecodeParms {pg.decode_parms} ".encode() if pg.decode_parms else b""
        img = add(
            b"<< /Type /XObject /Subtype /Image "
            + f"/Width {pg.width_px} /Height {pg.height_px} ".encode()
            + f"/ColorSpace {pg.colorspace} /BitsPerComponent {pg.bits} ".encode()
            + f"/Filter {pg.filter} ".encode() + parms
            + f"/Length {len(pg.stream)} ".encode()
            + b">>\nstream\n" + pg.stream + b"\nendstream"
        )
        w_pt = pg.width_px * 72.0 / pg.dpi
        h_pt = pg.height_px * 72.0 / pg.dpi
        content = (f"{w_pt:.2f} 0 0 {h_pt:.2f} 0 0 cm /Im0 Do\n".encode()
                   + (pg.extra_content or b""))
        resources = (f"/Resources << /XObject << /Im0 {img} 0 R >> ".encode()
                     + (b"/Font << /F1 " + f"{cjk_font_id} 0 R".encode()
                        + b" >> " if pg.extra_content else b"")
                     + b">> ")
        cont = add(
            f"<< /Length {len(content)} >>\nstream\n".encode()
            + content + b"endstream"
        )
        page_ids.append(add(
            f"<< /Type /Page /Parent 2 0 R ".encode()
            + f"/MediaBox [0 0 {w_pt:.2f} {h_pt:.2f}] ".encode()
            + resources
            + f"/Contents {cont} 0 R >>".encode()
        ))

    objs[1] = (b"<< /Type /Pages /Kids ["
               + b" ".join(f"{i} 0 R".encode() for i in page_ids)
               + f"] /Count {len(page_ids)} >>".encode())

    outlines = outlines or []
    if outlines:
        def _ut16(t: str) -> bytes:
            return b"(\xfe\xff" + t.encode("utf-16-be") + b")"

        entry_ids = []
        for i, oe in enumerate(outlines):
            if not (0 <= oe.page_index < len(page_ids)):
                continue
            dest = (f"[{page_ids[oe.page_index]} 0 R/XYZ 0 "
                    f"{_page_height(pages[oe.page_index]):.0f} 0.0]")
            body = (b"<< /Parent {ROOT} /Title".replace(b"{ROOT}", b"?")
                    + b" " + _ut16(oe.title) + f" /Dest{dest}".encode())
            if i + 1 < len(outlines):
                body += b" /Next {NEXT} 0 R".replace(b"{NEXT}",
                        f"{0}".encode())  # placeholder, fixed below
            body += b" >>"
            entry_ids.append(add(body))
        root_id = len(objs) + 1
        for i, eid in enumerate(entry_ids):
            b = objs[eid - 1]
            b = b.replace(b"/Parent ?", f"/Parent {root_id} 0 R".encode())
            if i + 1 < len(entry_ids):
                b = b.replace(b"/Next {NEXT} 0 R".replace(b"{NEXT}", b"0"),
                              f"/Next {entry_ids[i + 1]} 0 R".encode())
            else:
                b = b.replace(b" /Next {NEXT} 0 R".replace(b"{NEXT}", b"0"), b"")
            objs[eid - 1] = b
        add(f"<< /Type /Outlines /First {entry_ids[0]} 0 R "
            f"/Count {len(entry_ids)} /Last {entry_ids[-1]} 0 R >>".encode())
        objs[0] = (b"<< /Type /Catalog /Pages 2 0 R /Outlines "
                   + f"{root_id} 0 R".encode() + b" >>")

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
