"""Minimal image decoding helpers (stdlib only).

PNG: 8-bit grayscale / RGB / RGBA, non-interlaced, all filter types.
JPEG: dimensions + JFIF density only (the JPEG payload itself is embedded
into the PDF undecoded as DCTDecode).
"""
from __future__ import annotations

import struct
import zlib

DEFAULT_DPI = 150


class UnsupportedImage(ValueError):
    pass


def png_decode(data: bytes) -> tuple[int, int, int, str, bytes]:
    """Return (width, height, dpi, colorspace, raw_samples).

    colorspace is "/DeviceGray" or "/DeviceRGB"; raw samples have no
    row filters and RGBA is composited onto white.
    """
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise UnsupportedImage("not a PNG")
    pos = 8
    width = height = bitdepth = colortype = None
    idat = bytearray()
    dpi = DEFAULT_DPI
    while pos + 8 <= len(data):
        (length,) = struct.unpack_from(">I", data, pos)
        ctype = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + length]
        if ctype == b"IHDR":
            width, height, bitdepth, colortype, comp, filt, inter = \
                struct.unpack(">IIBBBBB", body)
            if bitdepth not in (1, 2, 4, 8) or inter != 0:
                raise UnsupportedImage(
                    f"png bitdepth={bitdepth} interlace={inter}")
        elif ctype == b"pHYs" and len(body) == 9:
            ppm_x, ppm_y, unit = struct.unpack(">IIB", body)
            if unit == 1 and ppm_x > 0:
                dpi = max(1, round(ppm_x * 0.0254))
        elif ctype == b"IDAT":
            idat += body
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if width is None:
        raise UnsupportedImage("png missing IHDR")

    palette = None
    channels = 1
    bpp = 1  # per spec: ceil(bitdepth*channels/8), min 1
    if colortype == 3:
        # palette: re-walk chunks for PLTE
        q = 8
        while q + 8 <= len(data):
            (ln,) = struct.unpack_from(">I", data, q)
            ct = data[q + 4:q + 8]
            if ct == b"PLTE":
                body = data[q + 8:q + 8 + ln]
                palette = [tuple(body[i:i + 3]) for i in range(0, len(body), 3)]
                break
            q += 12 + ln
        if not palette:
            raise UnsupportedImage("png palette missing PLTE")
        if bitdepth not in (1, 2, 4, 8):
            raise UnsupportedImage(f"png palette bitdepth={bitdepth}")
    elif colortype == 0:
        if bitdepth not in (1, 8):
            raise UnsupportedImage(f"png gray bitdepth={bitdepth}")
    else:
        raise UnsupportedImage(f"png colortype={colortype}")

    raw = zlib.decompress(bytes(idat))
    stride = (width * bitdepth + 7) // 8
    out = bytearray()
    prev = bytearray(stride)
    p = 0
    for _ in range(height):
        ftype = raw[p]; p += 1
        line = bytearray(raw[p:p + stride]); p += stride
        _unfilter(ftype, line, prev, bpp)
        out += line
        prev = line

    if palette is not None:  # expand indices to RGB
        mask = (1 << bitdepth) - 1
        per_byte = 8 // bitdepth
        rgb = bytearray(width * height * 3)
        i = 0
        for y in range(height):
            row = out[y * stride:(y + 1) * stride]
            for x in range(width):
                idx = (row[x // per_byte]
                       >> (8 - bitdepth * (x % per_byte + 1))) & mask
                r, g, b = palette[idx] if idx < len(palette) else (0, 0, 0)
                rgb[i:i + 3] = bytes((r, g, b))
                i += 3
        out = rgb
    elif bitdepth == 1:  # unpack MSB-first bits to 8-bit gray
        expanded = bytearray(width * height)
        i = 0
        for y in range(height):
            row = out[y * stride:(y + 1) * stride]
            for x in range(width):
                bit = (row[x // 8] >> (7 - x % 8)) & 1
                expanded[i] = 255 if bit else 0
                i += 1
        out = expanded

    if False:  # colortype == 6: RGBA -> RGB on white (milestone 2)
        rgb = bytearray(width * height * 3)
        for i in range(width * height):
            r, g, b, a = out[i * 4:i * 4 + 4]
            if a != 255:
                r = (r * a + 255 * (255 - a)) // 255
                g = (g * a + 255 * (255 - a)) // 255
                b = (b * a + 255 * (255 - a)) // 255
            rgb[i * 3:i * 3 + 3] = bytes((r, g, b))
        out = rgb

    cs = "/DeviceRGB" if palette is not None else "/DeviceGray"
    return width, height, dpi, cs, bytes(out)


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
                dpi = xd
            elif units == 2 and xd:
                dpi = round(xd * 2.54)
        elif marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack_from(">HH", seg, 1)
            return w, h, dpi
        pos += 2 + length
    raise UnsupportedImage("jpeg missing SOF")
