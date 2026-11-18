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
    """Linear-scan extraction: find object headers, then a bounded window
    after each for the dict + stream."""
    out = []
    last_num = 0
    for m in _OBJ_HEAD.finditer(pdf):
        obj_num = int(m.group(1))
        if obj_num != last_num + 1:
            continue  # phantom match inside stream data
        last_num = obj_num
        start = m.end()
        dict_start = pdf.find(b"<<", start, start + 4096)
        if dict_start < 0:
            continue
        dict_end = pdf.find(b">>", dict_start, dict_start + 8192)
        if dict_end < 0:
            continue
        d = pdf[dict_start:dict_end]
        if b"/Subtype /Image" not in d:
            continue
        # stream must follow the dict closely
        stream_pos = pdf.find(b"stream", dict_end, dict_end + 16)
        if stream_pos < 0:
            continue
        data_start = stream_pos + 6
        if pdf[data_start:data_start + 2] == b"\r\n":
            data_start += 2
        elif pdf[data_start:data_start + 1] in (b"\n", b"\r"):
            data_start += 1
        end = pdf.find(b"endstream", data_start, data_start + 400_000_000)
        if end < 0:
            continue
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
