# PDG container format — implementation notes

> Clean-room specification for the self-developed engine (Phase B).
> Written in our own words from observed behavior of sample files and
> public descriptions. No third-party code or verbatim documentation is
> reproduced here.

## 1. What a PDG file is

A PDG file is a *container* around a page image. Historical variants exist
(V1, V2 with sub-types), but the wrapped payload is always one of a small
set of standard image formats, detected by magic bytes — never by file
extension. The wrapper carries a small header with page geometry
(width, height, DPI) and a type tag.

The original tool classifies pages as:

- **T1** — black & white page. Payload: CCITT Group 4 fax data.
- **T2** — grayscale / color page. Payload: JPEG (baseline) or JPEG 2000.
- **T3** — multi-layer page (a text/base layer plus one or more image
  layers). Layers are stored like ordinary pages and merged on output.

## 2. Payload detection (magic bytes)

| Payload      | Magic (hex)                              |
|--------------|------------------------------------------|
| JPEG         | `FF D8 FF`                                |
| PNG          | `89 50 4E 47 0D 0A 1A 0A`                 |
| TIFF         | `49 49 2A 00` or `4D 4D 00 2A`            |
| JPEG 2000    | `00 00 00 0C 6A 50 20 20` (jp2) or raw JPX|
| DjVu         | `41 54 26 54 46 4F 52 4D` ("AT&TFORM") + `44 4A 56 55`/`44 4A 56 4D` |
| PDF          | `25 50 44 46` ("%PDF")                    |
| ZIP (textPDG)| `50 4B 03 04` ("PK..")                    |

Files whose payload is a standard format (JPEG/PNG/TIFF/JP2/DjVu/PDF) are
passed through unchanged by the reference converter, except DjVu which is
transcoded.

Text-type PDG files are encrypted ZIP archives whose members are PDF page
fragments; naming encodes page ranges (see §4).

## 3. Page geometry and DPI

Page width/height are properties of the payload image itself (SOF marker
for JPEG, IHDR for PNG/TIFF/JP2). DPI may come from:

- JPEG: APP0 JFIF density units or APP1/EXIF resolution
- PNG: `pHYs` chunk (pixels per meter)
- container header (authoritative when present; exact offset TBD by
  corpus analysis — see §6)

When no DPI is known, 150 dpi is the conventional default for scanned
books of this origin.

## 4. Naming convention and reading order

Page order is derived from file names:

- `covNNN` — cover (cov001 front, cov002 often the back cover)
- `bokNNN` — title page
- `fowNNN` — foreword / front matter
- `!NNNNN` — table of contents pages
- `legNNN` — copyright page
- `NNNNNN` — body pages, numbered by printed page number
- `appNNN` / `bacNNN` — appendix / back cover

Sort order: cover → bok → fow → `!` → leg → numeric body → appendix → bac,
then by number. The reference tool additionally offers "cov002 to the end".

## 5. Book metadata

- `bookcontents.dat` — table of contents (nested bookmark structure)
- `BookInfo.dat` — INI-style metadata (title, author, subject, keywords)
- `FreePic2Pdf.itf` — interface file the reference tool emits when
  producing per-layer images; records page width, layer mapping, bookmark
  tree, and section page numbering (cover/TOC/body segments).

## 6. Open questions for corpus analysis

Observed on the calibration corpus: the reference tool renders every page
of a book at one uniform width, sized as ``page_px * 72 / header_dpi``
(yielding ~477 pt for 1984 px-wide pages, i.e. a 300 dpi convention on
those samples). Our engine currently trusts the image's own density hint,
which can disagree with the container header by a constant factor — the
header field is authoritative and its byte offset is the key recovery
target below.

The exact byte layout of the proprietary header (per V1/V2 variant) is not
yet fully pinned down. It will be recovered by:

1. hex comparison across the sample corpus in `test-inbox/`
   (kept private; not part of this repository);
2. differential observation of the reference tool's per-file info output;
3. validating the self-developed decoder against the reference outputs
   until byte-identical page images are produced.

## 6b. The encrypted V2 container family (corpus findings)

A minority of pages (~6% of our corpus) live in a container with magic
``48 48`` (``"HH"``) plus a 2-byte variant tag (observed: ``02 00``,
``02 4a``). Differential analysis against the reference outputs shows:

- page width/height as little-endian u16 pair at offset 16;
- a layer directory of 20-byte records ``[u32 payload_offset]
  [u32 payload_length] ...``; records start after the fixed header
  (observed at offset 24 for a single-layer file, offset 152 for a
  multi-layer one; layer payloads are packed contiguously to EOF);
- JPEG layers are self-delimiting and can be walked by scanning for
  ``FF D8 FF`` / ``FF D9`` pairs;
- the bitonal base layer payload is NOT stored verbatim: it is
  transformed (high entropy; not XOR/reversal/bit-reversal, not
  zlib/gzip/bz2/lzma). Until it is cracked, such books go through the
  optional Wine backend.

### Static-analysis progress (Pdg2Pic.exe)

The format-detect dispatch lives around 0x5c6600-0x5c6700. The sniffer
at 0x5c6738 cascades over payload magics: JPEG (``FF D8``), PNG
(``89 50 4E 47``), ``GIF8``, ``BM``, TIFF (``II``/``MM``), WEBP at
offset 8, DjVu (``AT&T``); GIF dimensions are the little-endian u16 pair
at offsets 6/8 (codec tag 0x60), WEBP's branch (0x5c6c7d) calls
0x5f99b4 with tag 0xC00, TIFF (0x5c6cd2) calls 0x5dd1cc. The encrypted
V2 branch runs through 0x5c7bb0 / 0x5c7b44 — the transform itself is one
call level deeper and remains unrecovered. Bookmarks (default, no
bookcontents.dat): the reference emits a flat outline — section firsts
(封面/书名页/版权/前言/目录) in the order cov,bok,leg,fow,! — one entry
per body page titled by printed page number, and 封底 (bac page, or the
last page when bac is absent; cov002 then acts as the back cover and is
moved to the end). BookInfo.dat is appended as a GBK text page set in
STSong-Light (GBK-EUC-H, Tm-per-line, first baseline height-79.2, 14 pt
leading).

## 7. Out of scope

- Encrypted/DRM-protected PDG (unsupported by the reference tool as well).
- OCR text layers (double-layer PDF) — planned later via Tesseract.
