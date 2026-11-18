"""Extract embedded image streams from a PDF (both our writer's and the
reference tool's outputs) for differential comparison and corpus analysis.

Usage:
    python3 -m scripts.pdfimg <file.pdf>          # list image objects
    python3 -m scripts.pdfimg <file.pdf> <n>      # dump stream n to stdout.buffer
"""
from __future__ import annotations

import re
import sys
import zlib
from dataclasses import dataclass


@dataclass
class ImageStream:
    index: int
    width: int | None
    height: int | None
    filter: str
    colorspace: str | None
    params: dict
    raw: bytes

    def pixels(self) -> bytes:
        """Best-effort pixel decoding for hashing (jpeg stays encoded)."""
        if self.filter == "/FlateDecode":
            return zlib.decompress(self.raw)
        return self.raw


_OBJ_HEAD = re.compile(rb"(\d+)\s+(\d+)\s+obj")


def extract_images(pdf: bytes) -> list[ImageStream]:
    """Layout-driven extraction: jump from endobj to the next header so
    binary stream content can never inject phantom objects."""
    out = []
    pos = 0
    n = len(pdf)
    while pos < n:
        m = _OBJ_HEAD.search(pdf, pos)
        if not m:
            break
        dict_start = pdf.find(b"<<", m.end(), m.end() + 4096)
        if dict_start < 0:
            pos = m.end()
            continue
        # locate this object's own stream first (the dict may contain
        # nested << >> from DecodeParms, so '>>' alone cannot bound it)
        stream_pos = pdf.find(b"stream", dict_start, dict_start + 8192)
        if stream_pos < 0:
            pos = m.end()
            continue
        d = pdf[dict_start:stream_pos]
        if b"/Subtype /Image" not in d:
            endobj = pdf.find(b"endobj", m.end())
            if endobj < 0:
                break
            pos = endobj + 6
            continue
        data_start = stream_pos + 6
        if pdf[data_start:data_start + 2] == b"\r\n":
            data_start += 2
        elif pdf[data_start:data_start + 1] in (b"\n", b"\r"):
            data_start += 1
        end = pdf.find(b"endstream", data_start)
        if end < 0:
            break
        raw = pdf[data_start:end]
        while raw.endswith((b"\r", b"\n")):
            raw = raw[:-1]

        def num(key):
            mm = re.search(rb"/" + key + rb"\s+(-?\d+)", d)
            return int(mm.group(1)) if mm else None
        f = re.search(rb"/Filter\s*/(\w+)", d)
        cs = re.search(rb"/ColorSpace\s*/(\w+)", d)
        params = {}
        for k in (b"K", b"Columns", b"Rows", b"BlackIs1"):
            mm = re.search(rb"/" + k + rb"\s+(-?\w+)", d)
            if mm:
                params[k.decode()] = mm.group(1).decode()
        out.append(ImageStream(
            index=len(out), width=num(b"Width"), height=num(b"Height"),
            filter=f.group(1).decode() if f else "?",
            colorspace=cs.group(1).decode() if cs else None,
            params=params, raw=raw,
        ))
        endobj = pdf.find(b"endobj", end)
        if endobj < 0:
            break
        pos = endobj + 6
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    pdf = open(argv[1], "rb").read()
    imgs = extract_images(pdf)
    if len(argv) == 3:
        idx = int(argv[2])
        sys.stdout.buffer.write(imgs[idx].raw)
        return 0
    print(f"{len(imgs)} image streams")
    for im in imgs[:8]:
        print(f"[{im.index}] {im.width}x{im.height} {im.filter} "
              f"{im.colorspace or ''} {im.params} len={len(im.raw)}")
    if len(imgs) > 8:
        print("...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
