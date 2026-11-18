# pdg2pdf-web

Convert PDG e-books to PDF through a browser. Upload an archive that contains
PDG files, get a PDF back. All processing happens server-side in a headless
Linux Docker container.

## Status

**Phase B (self-developed engine) is the default.** Two backends exist:

- `native` — a pure-stdlib engine (`engine/`, spec in `docs/FORMAT.md`):
  payload sniffing, PDG reading order, JPEG pass-through (byte-identical to
  the reference but for the Adobe APP14 segment), PNG decoding (8-bit gray,
  RGB, 1-bit packed, palette), uniform page width, BookInfo appendix page.
  On the 28-book calibration corpus it reaches full page/box parity with
  the reference outputs and ~100% image-stream parity on JPEG books.
- `wine_pdg2pic` — the Phase A wrapper (Win32 message-level driver for the
  original freeware under Wine/Xvfb), kept as the fallback for the
  encrypted V2 'HH' container family (~6% of corpus pages; see
  `docs/FORMAT.md` section 6b for the recovered structure and the RE
  entry points).

The default `auto` backend runs native first and falls back per-book.
Set `PDG2PDF_CONVERTER=native|wine_pdg2pic|echo` to force one.

Differential testing: `python3 -m scripts.diff_corpus <inbox> <oracle_dir>
<map.json>` compares engine output against reference PDFs page-by-page
(page counts, boxes, image-stream bytes with APP14 normalization).

Known limitations: OCR (double-layer PDF) unsupported; the encrypted V2
container family needs decoder reverse engineering (documented entry
points in FORMAT.md); DjVu/JPEG2000 payloads are not in the calibration
corpus and raise UnsupportedPayload (they then fall back to Wine).

## How it works

```
Browser ──upload archive──▶ FastAPI ──job queue──▶ Worker ──▶ PDF
                              │                        │
                              └── job status / download ◀┘
```

- **Phase A (current)**: a *wrapper* backend. Conversion is performed by the
  original freeware `Pdg2Pic` (by Jian Ma / strnghrs) running under Wine/Xvfb,
  driven by a tiny Win32 message-level automation program (`driver/pgdrive.c`,
  cross-compiled with MinGW). **The Pdg2Pic binary is NOT part of this
  repository** — bring your own (see below).
- **Phase B (planned)**: a fully self-developed conversion engine. The worker
  interface stays identical, so the Wine layer can be dropped by changing one
  environment variable. Goal: a clean, permissively licensed, cross-platform
  implementation described in `FORMAT.md` (to be written from our own format
  analysis).

## Quick start (Docker)

```bash
# 1. Obtain Pdg2Pic from the author's distribution page and put it here:
#    https://www.cnblogs.com/stronghorse/  ("Pdg2Pic" section / linked netdisk)
mkdir -p vendor
cp /path/to/Pdg2Pic.exe vendor/

# 2. Build and run (the archive password word list is bundled, nothing else to prepare)

docker compose up --build
# open http://localhost:8000
```

Environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `PDG2PDF_CONVERTER` | `wine_pdg2pic` | Backend: `wine_pdg2pic` or `echo` (self-test backend, no Wine needed). |
| `PDG2PIC_EXE` | `/srv/vendor/Pdg2Pic.exe` | Path to the deployer-provided binary. |
| `PDG2PDF_PASSWORD_LIST` | bundled `wordlists/archive-passwords.txt` | One archive password per line, tried in order when an archive is encrypted. |
| `PDG2PDF_DATA_DIR` | `./data` | Uploads, job state, results. |
| `PDG2PDF_MAX_UPLOAD_MB` | `2048` | Upload size limit. |

## Bundled word list

`wordlists/archive-passwords.txt` is a community-collected list of passwords
historically used on e-book sharing archives (zip/rar/7z attachment
passwords), gathered from public sources by the project maintainer. It is
redistributed under this project's Apache-2.0 license. These passwords open
**archive files only**; PDG files themselves are a separate matter (see
below). To use your own list, set `PDG2PDF_PASSWORD_LIST`.

## Local development (no Wine required)

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
PDG2PDF_CONVERTER=echo uvicorn app.main:app --reload
```

Stdlib-only smoke tests (no dependencies):

```bash
python3 -m unittest discover -s tests
```

## Legal notes

- `Pdg2Pic` is freeware by Jian Ma (strnghrs), distributed from his blog. This
  project does not redistribute his binary or documentation. The author has
  given personal consent for a CLI/Web port, but every deployer should obtain
  the program from the author's own distribution channels.
- This tool is for converting PDG files you are legally entitled to use, for
  personal reading. Encrypted/DRM-protected PDG is **out of scope** and will
  not be supported.
- Archive password brute-forcing is limited to the bundled word list (or a
  user-supplied one) and exists solely to open archives you own.

## Roadmap

- [x] Project skeleton: FastAPI app, job queue, archive extraction (zip/rar/7z/uvz with password list)
- [x] Phase A: Wine wrapper backend (`wine_pdg2pic`) + Win32 driver + Dockerfile
- [x] End-to-end smoke test (`scripts/e2e_test.sh`)
- [x] Web UI polish (drag&drop, inline errors, per-job metadata)
- [x] Phase B: self-developed engine + `auto` backend (native first, Wine fallback)
- [x] Differential corpus testing (`scripts/diff_corpus.py`)
- [ ] Encrypted V2 container decryption (reverse engineering; entry points documented)
- [ ] DjVu / JPEG2000 payload support (no samples in the current corpus)
- [ ] Job retention/cleanup, OCR via Tesseract
- [ ] Release

## License

Apache-2.0. See [LICENSE](LICENSE).
