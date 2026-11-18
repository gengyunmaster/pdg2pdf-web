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


def _gbk_literal(text: str) -> bytes:
    raw = text.encode("gbk", "replace")
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
        parts.append(b"(" + _gbk_literal(line) + b")Tj")
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




def _flatten_outlines(outlines, _depth, flat):
    for oe in outlines:
        flat.append((_depth, oe.title, oe.page_index))
        if oe.children:
            _flatten_outlines(oe.children, _depth + 1, flat)


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
    cjk_font_id = add(
        b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light "
        b"/Encoding /GBK-EUC-H /DescendantFonts ["
        + f"{cjk_desc} 0 R".encode() + b"] >>"
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

    if outlines:
        flat: list[tuple[int, str, int]] = []
        _flatten_outlines(outlines, 0, flat)
        ids: list[int] = []
        bodies: list[bytes] = []
        n = len(flat)

        def ut16(t: str) -> bytes:
            return b"(\xfe\xff" + t.encode("utf-16-be") + b")"

        # depth-first numbering: node i gets object id assigned in order
        # compute object id per node = base + i (order of `flat`)
        def emit(i: int, parent_id: int, prev_id: int,
                 next_id: int) -> tuple[int, int]:
            depth, title, page_idx = flat[i]
            if not (0 <= page_idx < len(page_ids)):
                page_idx = 0
            dest = (f"[{page_ids[page_idx]} 0 R/XYZ 0 "
                    f"{_page_height(pages[page_idx]):.0f} 0.0]")
            body = (f"<< /Title ".encode() + ut16(title)
                    + f" /Parent {parent_id} 0 R".encode())
            if prev_id:
                body += f" /Prev {prev_id} 0 R".encode()
            if next_id:
                body += f" /Next {next_id} 0 R".encode()
            body += f" /Dest{dest}".encode()
            return depth, body

        # first pass: allocate objects in flat order and link siblings
        node_ids = list(range(len(objs) + 1, len(objs) + 1 + n))
        root_id = node_ids[0] - 1  # placeholder; root appended after
        id_of = {i: node_ids[i] for i in range(n)}
        # parent/sibling relations from depth structure
        parent_of = [-1] * n
        prev_of = [-1] * n
        next_of = [-1] * n
        children_of: dict[int, list[int]] = {}
        stack: list[int] = []
        for i in range(n):
            d = flat[i][0]
            while stack and flat[stack[-1]][0] >= d:
                stack.pop()
            if stack:
                parent_of[i] = stack[-1]
                children_of.setdefault(stack[-1], []).append(i)
            stack.append(i)
        # sibling pass: nodes with same parent are consecutive
        by_parent: dict[int, list[int]] = {}
        for i in range(n):
            by_parent.setdefault(parent_of[i], []).append(i)
        for kids in by_parent.values():
            for k, i in enumerate(kids):
                if k:
                    prev_of[i] = kids[k - 1]
                if k + 1 < len(kids):
                    next_of[i] = kids[k + 1]
        # descendant counts
        desc = [0] * n
        for i in range(n - 1, -1, -1):
            d = 0
            for c in children_of.get(i, []):
                d += 1 + desc[c]
            desc[i] = d

        root_outline_id = len(objs) + 1 + n  # after all nodes
        for i in range(n):
            depth, title, page_idx = flat[i]
            if not (0 <= page_idx < len(page_ids)):
                page_idx = 0
            dest = (f"[{page_ids[page_idx]} 0 R/XYZ 0 "
                    f"{_page_height(pages[page_idx]):.0f} 0.0]")
            pid = (root_outline_id if parent_of[i] < 0
                   else id_of[parent_of[i]])
            body = (b"<< /Title " + ut16(title)
                    + f" /Parent {pid} 0 R".encode())
            if prev_of[i]:
                body += f" /Prev {id_of[prev_of[i]]} 0 R".encode()
            if next_of[i]:
                body += f" /Next {id_of[next_of[i]]} 0 R".encode()
            kids = children_of.get(i)
            if kids:
                body += (f" /First {id_of[kids[0]]} 0 R /Last "
                         f"{id_of[kids[-1]]} 0 R /Count {desc[i]}".encode())
            body += f" /Dest{dest}".encode() + b" >>"
            bodies.append(body)
        for b in bodies:
            add(b)
        top = by_parent.get(-1, [])
        add(f"<< /Type /Outlines /First {id_of[top[0]]} 0 R "
            f"/Count {len(top)} /Last {id_of[top[-1]]} 0 R >>".encode())
        objs[0] = (b"<< /Type /Catalog /Pages 2 0 R /Outlines "
                   + f"{root_outline_id} 0 R".encode() + b" >>")
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
    cjk_font_id = add(
        b"<< /Type /Font /Subtype /Type0 /BaseFont /STSong-Light "
        b"/Encoding /GBK-EUC-H /DescendantFonts ["
        + f"{cjk_desc} 0 R".encode() + b"] >>"
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
