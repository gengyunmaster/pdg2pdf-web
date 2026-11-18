
"""CCITT T.6 (Group 4) encoder for bitonal images.

Pure-python, table driven. Validation strategy: the encoded streams are
rendered by an external PDF engine (poppler) and pixel-compared against
the decoded source PNGs — see scripts/diff_corpus.py / docker tests.

Only encoding is implemented; the reference decoder is intentionally not
reimplemented (poppler is the independent oracle).
"""
from __future__ import annotations

# --- T.4 Huffman tables (RFC 804 / ITU T.4): (code, bit_length) ------
WHITE_TERM = [
    (0b00110101, 8), (0b000111, 6), (0b0111, 4), (0b1000, 4),
    (0b1011, 4), (0b1100, 4), (0b1110, 4), (0b1111, 4),
    (0b10011, 5), (0b10100, 5), (0b00111, 5), (0b01000, 5),
    (0b001000, 6), (0b000011, 6), (0b110100, 6), (0b110101, 6),
    (0b101010, 6), (0b101011, 6), (0b0100111, 7), (0b0001100, 7),
    (0b0001000, 7), (0b0010111, 7), (0b0000011, 7), (0b0000100, 7),
    (0b0101000, 7), (0b0101011, 7), (0b0010011, 7), (0b0100100, 7),
    (0b0011000, 7), (0b00000010, 8), (0b00000011, 8), (0b00011010, 8),
    (0b00011011, 8), (0b00010010, 8), (0b00010011, 8), (0b00010100, 8),
    (0b00010101, 8), (0b00010110, 8), (0b00010111, 8), (0b00101000, 8),
    (0b00101001, 8), (0b00101010, 8), (0b00101011, 8), (0b00101100, 8),
    (0b00101101, 8), (0b00000100, 8), (0b00000101, 8), (0b00001010, 8),
    (0b00001011, 8), (0b01010010, 8), (0b01010011, 8), (0b01010100, 8),
    (0b01010101, 8), (0b00100100, 8), (0b00100101, 8), (0b01011000, 8),
    (0b01011001, 8), (0b01011010, 8), (0b01011011, 8), (0b01001010, 8),
    (0b01001011, 8), (0b00110010, 8), (0b00110011, 8), (0b00110100, 8),
]
BLACK_TERM = [
    (0b0000110111, 10), (0b010, 3), (0b11, 2), (0b10, 2),
    (0b011, 3), (0b0011, 4), (0b0010, 4), (0b00011, 5),
    (0b000101, 6), (0b000100, 6), (0b0000100, 7), (0b0000101, 7),
    (0b0000111, 7), (0b00000100, 8), (0b00000111, 8), (0b000011000, 9),
    (0b0000010111, 10), (0b0000011000, 10), (0b0000001000, 10),
    (0b00001100111, 11), (0b00001101000, 11), (0b00001101100, 11),
    (0b00000110111, 11), (0b00000101000, 11), (0b00000010111, 11),
    (0b00000011000, 11), (0b000011001010, 12), (0b000011001011, 12),
    (0b000011001100, 12), (0b000011001101, 12), (0b000001101000, 12),
    (0b000001101001, 12), (0b000001101010, 12), (0b000001101011, 12),
    (0b000011010010, 12), (0b000011010011, 12), (0b000011010100, 12),
    (0b000011010101, 12), (0b000011010110, 12), (0b000011010111, 12),
    (0b000001101100, 12), (0b000001101101, 12), (0b000011011010, 12),
    (0b000011011011, 12), (0b000001010100, 12), (0b000001010101, 12),
    (0b000001010110, 12), (0b000001010111, 12), (0b000001100100, 12),
    (0b000001100101, 12), (0b000001010010, 12), (0b000001010011, 12),
    (0b000000100100, 12), (0b000000110111, 12), (0b000000111000, 12),
    (0b000000100111, 12), (0b000000101000, 12), (0b000001011000, 12),
    (0b000001011001, 12), (0b000000101011, 12), (0b000000101100, 12),
    (0b000001011010, 12), (0b000001100110, 12), (0b000001100111, 12),
]
# make-up codes for 64..1728 step 64 (index = run//64 - 1)
WHITE_MAKEUP = [
    (0b11011, 5), (0b10010, 5), (0b010111, 6), (0b0110111, 7),
    (0b00110110, 8), (0b00110111, 8), (0b01100100, 8), (0b01100101, 8),
    (0b01101000, 8), (0b01100111, 8), (0b011001100, 9), (0b011001101, 9),
    (0b011010010, 9), (0b011010011, 9), (0b011010100, 9), (0b011010101, 9),
    (0b011010110, 9), (0b011010111, 9), (0b011011000, 9), (0b011011001, 9),
    (0b011011010, 9), (0b011011011, 9), (0b010011000, 9), (0b010011001, 9),
    (0b010011010, 9), (0b011000, 6), (0b010011011, 9),
]
BLACK_MAKEUP = [
    (0b0000001111, 10), (0b000011001000, 12), (0b000011001001, 12),
    (0b000001011011, 12), (0b000000110011, 12), (0b000000110100, 12),
    (0b000000110101, 12), (0b0000001101100, 13), (0b0000001101101, 13),
    (0b0000001001010, 13), (0b0000001001011, 13), (0b0000001001100, 13),
    (0b0000001001101, 13), (0b0000001110010, 13), (0b0000001110011, 13),
    (0b0000001110100, 13), (0b0000001110101, 13), (0b0000001110110, 13),
    (0b0000001110111, 13), (0b0000001010010, 13), (0b0000001010011, 13),
    (0b0000001010100, 13), (0b0000001010101, 13), (0b0000001011010, 13),
    (0b0000001011011, 13), (0b0000001100100, 13), (0b0000001100101, 13),
]
# extended make-ups 1792..2560 step 64
EXT = [
    (0b00000001000, 11), (0b00000001100, 11), (0b00000001101, 11),
    (0b000000010010, 12), (0b000000010011, 12), (0b000000010100, 12),
    (0b000000010101, 12), (0b000000010110, 12), (0b000000010111, 12),
    (0b000000011100, 12), (0b000000011101, 12), (0b000000011110, 12),
    (0b000000011111, 12),
]
# 2D mode codes
PASS = (0x1, 4)
HORIZ = (0x1, 3)
V = {0: (0b1, 1), (1, "r"): (0b011, 3), (-1, "l"): (0b010, 3),
     (2, "r"): (0b000011, 6), (-2, "l"): (0b000010, 6),
     (3, "r"): (0b0000011, 7), (-3, "l"): (0b0000010, 7)}
EOFB = 0b000000000001000000000001


import bisect


class _Bits:
    __slots__ = ("buf", "acc", "n")

    def __init__(self):
        self.buf = bytearray()
        self.acc = 0
        self.n = 0

    def put(self, code: int, length: int) -> None:
        self.acc = (self.acc << length) | code
        self.n += length
        while self.n >= 8:
            self.n -= 8
            self.buf.append((self.acc >> self.n) & 0xFF)
        self.acc &= (1 << self.n) - 1

    def align(self) -> None:
        if self.n:
            self.put(0, 8 - self.n)

    def bytes(self) -> bytes:
        if self.n:
            self.buf.append((self.acc << (8 - self.n)) & 0xFF)
            self.acc = 0
            self.n = 0
        return bytes(self.buf)


def _run_codes(run: int, white: bool) -> list[tuple[int, int]]:
    term = WHITE_TERM if white else BLACK_TERM
    makeup = WHITE_MAKEUP if white else BLACK_MAKEUP
    out = []
    while run >= 1792:
        chunk = min(run, 2560)
        out.append(EXT[(chunk - 1792) // 64])
        run -= chunk
    if run >= 64:
        out.append(makeup[run // 64 - 1])
        run %= 64
    out.append(term[run])
    return out


_TRANS = []
for _b in range(256):
    _bits = [(_b >> (7 - i)) & 1 for i in range(8)]
    _TRANS.append((_bits[0], _bits[-1],
                   [i for i in range(1, 8) if _bits[i] != _bits[i - 1]]))


def _ce_packed(row: bytes, width: int) -> list[int]:
    """Changing elements of a packed 1-bit row (fast, table driven)."""
    ce = []
    prev = 0
    nbytes = (width + 7) // 8
    for bi in range(nbytes):
        first, last, trans = _TRANS[row[bi]]
        base = bi * 8
        if first != prev and base < width:
            ce.append(base)
        for t in trans:
            x = base + t
            if x < width:
                ce.append(x)
        prev = last
    ce.append(width)
    return ce


def _changing_elements(line: list[int], width: int) -> list[int]:
    ce = []
    prev = 0
    for x in range(width):
        if line[x] != prev:
            ce.append(x)
            prev = line[x]
    ce.append(width)
    return ce


def encode_g4(pixels: bytes, width: int, height: int) -> bytes:
    """pixels: packed 1-bit rows (MSB first, 0=black), row stride padded."""
    stride = (width + 7) // 8
    bw = _Bits()
    ref = [width]  # all-white reference line
    for y in range(height):
        ce = _ce_packed(pixels[y * stride:(y + 1) * stride], width)
        _encode_row(bw, ce, ref, width)
        ref = ce
    bw.put(EOFB >> 12, 12)
    bw.put(EOFB & 0xFFF, 12)
    bw.align()
    return bw.bytes()


def _encode_row(bw: _Bits, ce: list[int], ref: list[int],
                width: int) -> None:
    """ce: changing elements of coding line (colors alternate starting
    white=0). ref: changing elements of reference line."""
    a0 = -1
    color = 0  # 0 = white
    i = 0  # index into ce
    while True:
        b1, b2 = _ref_ce_after(ref, a0)
        a1 = ce[i] if i < len(ce) else width
        a2 = ce[i + 1] if i + 1 < len(ce) else width
        if b2 < a1:
            bw.put(*PASS)
            a0 = b2
            continue
        d = a1 - b1
        if abs(d) <= 3:
            key = 0 if d == 0 else (d, "r" if d > 0 else "l")
            bw.put(*V[key])
            a0 = a1
            color = 1 - color
            i += 1
        else:
            bw.put(*HORIZ)
            start = a0 if a0 >= 0 else 0
            first = a1 - start
            second = a2 - a1
            for code in _run_codes(first, color == 0):
                bw.put(*code)
            for code in _run_codes(second, color == 1):
                bw.put(*code)
            a0 = a2
            i += 2
        if a0 >= width:
            break


_INF = 1 << 30


def _next_ref_ce(ref: list[int], pos: int) -> int:
    """First changing element strictly right of pos on the reference
    line (T.6 definition of b1/b2)."""
    i = bisect.bisect_right(ref, pos)
    return ref[i] if i < len(ref) else _INF


def _ref_ce_after(ref: list[int], pos: int):
    """(b1, b2) pair after pos."""
    i = bisect.bisect_right(ref, pos)
    b1 = ref[i] if i < len(ref) else _INF
    b2 = ref[i + 1] if i + 1 < len(ref) else _INF
    return b1, b2


# --- spec-based decoder (for validation and tests) ----------------------
def _build_decode_tables():
    white = {}
    black = {}
    for i, (c, l) in enumerate(WHITE_TERM):
        white[(c, l)] = ("T", i)
    for i, (c, l) in enumerate(BLACK_TERM):
        black[(c, l)] = ("T", i)
    for j, (c, l) in enumerate(WHITE_MAKEUP):
        white.setdefault((c, l), ("M", (j + 1) * 64))
    for j, (c, l) in enumerate(BLACK_MAKEUP):
        black.setdefault((c, l), ("M", (j + 1) * 64))
    for j, (c, l) in enumerate(EXT):
        white[(c, l)] = ("M", 1792 + j * 64)
        black[(c, l)] = ("M", 1792 + j * 64)
    modes = {
        (0b1, 1): ("V", 0), (0b011, 3): ("V", 1), (0b010, 3): ("V", -1),
        (0b000011, 6): ("V", 2), (0b000010, 6): ("V", -2),
        (0b0000011, 7): ("V", 3), (0b0000010, 7): ("V", -3),
        (0b0001, 4): ("P", 0), (0b001, 3): ("H", 0),
    }
    return white, black, modes


_WHITE_DEC, _BLACK_DEC, _MODES = _build_decode_tables()


class _BitReader:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0

    def get(self, n: int) -> int | None:
        v = 0
        for _ in range(n):
            byte = self.pos // 8
            if byte >= len(self.data):
                return None
            bit = (self.data[byte] >> (7 - self.pos % 8)) & 1
            self.pos += 1
            v = (v << 1) | bit
        return v

    def peek1(self) -> int | None:
        byte = self.pos // 8
        if byte >= len(self.data):
            return None
        return (self.data[byte] >> (7 - self.pos % 8)) & 1


def _read_code(br, table, max_len=13):
    code = 0
    for ln in range(1, max_len + 1):
        b = br.get(1)
        if b is None:
            return None
        code = (code << 1) | b
        if (code, ln) in table:
            return table[(code, ln)]
    return None


def decode_g4(data: bytes, width: int, height: int) -> bytes:
    """Return packed 1-bit rows (0=black)."""
    br = _BitReader(data)
    img = bytearray()
    ref = [width]  # all-white reference
    for _y in range(height):
        row = [0] * width
        ref_new = []
        a0 = -1
        color = 0
        while True:
            m = _read_code(br, _MODES, 7)
            if m is None:
                raise ValueError("bad 2D mode code")
            kind, val = m
            if kind == "V":
                b1 = _next_ref_ce(ref, a0)
                a1 = max(0, min(width, b1 + val))
                if color and a1 > a0:
                    row[a0:a1] = b"\x01" * (a1 - a0)
                ref_new.append(a1)
                a0 = a1
                color ^= 1
            elif kind == "P":
                _b1, b2 = _ref_ce_after(ref, a0)
                if b2 >= (1 << 29):
                    b2 = width
                if color and b2 > a0:
                    row[a0:b2] = b"\x01" * (b2 - a0)
                a0 = b2
            else:  # H
                runs = []
                for c in (color, color ^ 1):
                    total = 0
                    while True:
                        r = _read_code(br, _WHITE_DEC if c == 0 else _BLACK_DEC)
                        if r is None:
                            raise ValueError("bad run code")
                        t, v = r
                        total += v
                        if t == "T":
                            break
                    runs.append(total)
                start = a0 if a0 >= 0 else 0
                a1 = start + runs[0]
                a2 = a1 + runs[1]
                if color:
                    lo, hi = max(0, start), min(a1, width)
                else:
                    lo, hi = max(0, a1), min(a2, width)
                if hi > lo:
                    row[lo:hi] = b"\x01" * (hi - lo)
                ref_new.extend([min(a1, width), min(a2, width)])
                a0 = a2
            if a0 >= width:
                break
        # pack row
        out = bytearray((width + 7) // 8)
        for x in range(width):
            if row[x]:
                out[x // 8] |= 0x80 >> (x % 8)
        img += out
        ref = ref_new if ref_new else [width]
    return bytes(img)
