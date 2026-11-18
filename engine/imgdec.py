"""Minimal image decoding helpers (stdlib only).

PNG: 8-bit grayscale / RGB / RGBA, non-interlaced, all filter types.
JPEG: dimensions + JFIF density only (the JPEG payload itself is embedded
into the PDF undecoded as DCTDecode).
"""
from __future__ import annotations

import struct
import zlib

DEFAULT_DPI = 150
MIN_DPI, MAX_DPI = 50, 1200


def sane_dpi(dpi: int) -> int:
    return dpi if MIN_DPI <= dpi <= MAX_DPI else DEFAULT_DPI


class UnsupportedImage(ValueError):
    pass


def png_decode(data: bytes, packed_1bit: bool = True):
    """Return (width, height, dpi, colorspace, bits, samples).

    colorspace is "/DeviceGray" or "/DeviceRGB". 1-bit grayscale may be
    returned packed (bits=1, one pixel per bit, MSB first, 0=black) or
    expanded to 8-bit samples.
    """
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise UnsupportedImage("not a PNG")
    pos = 8
    width = height = bitdepth = colortype = None
    idat = bytearray()
    dpi = DEFAULT_DPI
    palette = None
    while pos + 8 <= len(data):
        (length,) = struct.unpack_from(">I", data, pos)
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bitdepth, colortype, _c, _f, inter = \
                struct.unpack(">IIBBBBB", body)
            if bitdepth not in (1, 2, 4, 8) or inter != 0:
                raise UnsupportedImage(
                    f"png bitdepth={bitdepth} interlace={inter}")
        elif ctype == b"PLTE":
            palette = [bytes(body[i:i + 3]) for i in range(0, len(body), 3)]
        elif ctype == b"pHYs" and len(body) == 9:
            ppm_x, _ppm_y, unit = struct.unpack(">IIB", body)
            if unit == 1 and ppm_x > 0:
                dpi = sane_dpi(round(ppm_x * 0.0254))
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if width is None:
        raise UnsupportedImage("png missing IHDR")
    if colortype == 3 and not palette:
        raise UnsupportedImage("png palette missing PLTE")
    if colortype not in (0, 2, 3):
        raise UnsupportedImage(f"png colortype={colortype}")

    raw = zlib.decompress(bytes(idat))
    stride = (width * bitdepth + 7) // 8
    rows = []
    prev = bytearray(stride)
    p = 0
    for _ in range(height):
        ftype = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        _unfilter(ftype, line, prev, 1)
        rows.append(bytes(line))
        prev = line
    packed = b"".join(rows)

    if colortype == 0 and bitdepth == 1:
        if packed_1bit:
            return width, height, dpi, "/DeviceGray", 1, packed
        lut = bytes((i & 1) * 255 for i in range(256))
        expand = [bytes(((i >> (7 - k)) & 1) for k in range(8))
                  for i in range(256)]
        out = b"".join(b"".join(expand[b] for b in row).translate(lut)
                       for row in rows)
        return width, height, dpi, "/DeviceGray", 8, out

    if colortype == 0 and bitdepth == 8:
        return width, height, dpi, "/DeviceGray", 8, packed

    if colortype == 2 and bitdepth == 8:
        return width, height, dpi, "/DeviceRGB", 8, packed

    # colortype == 3 (palette), bitdepth 1/2/4/8: expand to RGB
    per_byte = 8 // bitdepth
    mask = (1 << bitdepth) - 1
    t3 = [
        b"".join(
            palette[(i >> (8 - bitdepth * (k + 1))) & mask]
            if (i >> (8 - bitdepth * (k + 1))) & mask < len(palette)
            else b"\x00\x00\x00"
            for k in range(per_byte)
        )
        for i in range(256)
    ]
    out = b"".join(b"".join(t3[b] for b in row) for row in rows)
    return width, height, dpi, "/DeviceRGB", 8, out

def _unfilter(ftype: int, line: bytearray, prev: bytearray, bpp: int) -> None:
    if ftype == 0:
        return
    if ftype == 1:  # Sub
        for i in range(bpp, len(line)):
            line[i] = (line[i] + line[i - bpp]) & 0xFF
    elif ftype == 2:  # Up
        for i in range(len(line)):
            line[i] = (line[i] + prev[i]) & 0xFF
    elif ftype == 3:  # Average
        for i in range(len(line)):
            a = line[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + (a + prev[i]) // 2) & 0xFF
    elif ftype == 4:  # Paeth
        for i in range(len(line)):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            line[i] = (line[i] + _paeth(a, b, c)) & 0xFF
    else:
        raise UnsupportedImage(f"png filter {ftype}")


def _paeth(a: int, b: int, c: int) -> int:
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    if pa <= pb and pa <= pc:
        return a
    return b if pb <= pc else c


def jpeg_info(data: bytes) -> tuple[int, int, int]:
    """Return (width, height, dpi) from a JPEG stream (JFIF/EXIF density)."""
    if not data.startswith(b"\xff\xd8"):
        raise UnsupportedImage("not a JPEG")
    dpi = DEFAULT_DPI
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        (length,) = struct.unpack_from(">H", data, pos + 2)
        seg = data[pos + 4:pos + 2 + length]
        if marker == 0xE0 and seg.startswith(b"JFIF\x00") and len(seg) >= 12:
            units, xd, yd = struct.unpack_from(">BHH", seg, 7)
            if units == 1 and xd:
                dpi = sane_dpi(xd)
            elif units == 2 and xd:
                dpi = sane_dpi(round(xd * 2.54))
        elif marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack_from(">HH", seg, 1)
            return w, h, dpi
        pos += 2 + length
    raise UnsupportedImage("jpeg missing SOF")
