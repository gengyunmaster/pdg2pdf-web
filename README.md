# pdg2pdf-web

Convert PDG e-books to PDF through a browser. Upload an archive (zip / rar /
7z / uvz) that contains a book's PDG page files, get a single PDF back — with
optional OCR text search. All processing happens server-side in a headless
Linux Docker container; users only need a browser.

## Features

- **Drag & drop upload** of zip/rar/7z/uvz archives; nested folders and
  password-protected archives (tried against a bundled word list) are handled.
- **Self-developed conversion engine by default** (`engine/`, pure Python
  standard library): PDG payload sniffing, reading-order sorting, JPEG
  pass-through, PNG decoding (8-bit gray/RGB, packed 1-bit, palette),
  CCITT G4 bitonal encoding, uniform page width, PDF bookmarks, BookInfo
  appendix page, CJK text rendering.
- **Automatic fallback** to a Wine wrapper around the original freeware
  `Pdg2Pic` for the encrypted V2 container family that the engine does not
  handle yet (see `docs/FORMAT.md` §6b).
- **Optional OCR text layer** (Tesseract, `chi_sim` + `eng`): per-book
  checkbox in the web UI or `PDG2PDF_OCR=1`; adds selectable, searchable
  hidden text. Slower — roughly 5–15 s per page.
- Self-hosted single container; jobs are queued one at a time and survive
  restarts.

## Architecture

```
Browser ──upload archive──▶ FastAPI ──job queue──▶ Worker ──▶ PDF
                              │                        │
                              └── job status / download ◀┘
```

Backends (`PDG2PDF_CONVERTER` selects, default `auto`):

- `auto` — run the native engine; if any page is an encrypted V2 container,
  fall back to the Wine wrapper for that book.
- `native` — the self-developed engine only. Encrypted-V2 books fail with a
  clear error.
- `wine_pdg2pic` — the wrapper only (see "Wine wrapper backend" below).
- `echo` — self-test backend that emits a tiny blank PDF (no Wine, no
  engine; useful for development).

Repository layout:

```
app/            FastAPI service: upload API, job queue, static web UI
app/workers/    converter backends (auto / native / wine_pdg2pic / echo)
engine/         self-developed engine (spec in docs/FORMAT.md)
  pdgspec.py      payload sniffing, reading order, bookmark rules
  imgdec.py       PNG decoding (gray/RGB/1-bit/palette), JPEG info
  ccitt.py        CCITT T.6 (G4) encoder + decoder
  pdfdoc.py       minimal PDF writer (images, text pages, outlines)
  ocr.py          Tesseract hidden-text layer
  convert.py      orchestration + `python -m engine.convert <dir> <out.pdf>`
driver/         Win32 C tools: the Wine message-level driver (pdrive_main.c
                -> pdgdrive.exe) and the window recon tools used to build it
docker/         Dockerfile (runtime image) + entrypoint
scripts/        e2e_test.sh, diff_corpus.py, pdfimg.py, recon.sh,
                analyze_corpus.py
wordlists/      bundled archive-password list (see below)
docs/FORMAT.md  clean-room PDG format notes recovered by this project
tests/          stdlib-only unit tests
```

## Quick start (from a clean clone)

Prerequisites: Docker with the Compose plugin (v2). Linux x86_64 host (the
Wine fallback needs 32-bit userland support, which the image handles itself).

```bash
# 1. Clone
git clone https://github.com/gengyunmaster/pdg2pdf-web.git
cd pdg2pdf-web

# 2. (Recommended) provide the Pdg2Pic executable (BYOB — not redistributed
#    here). Obtain it from the author's page and place it in vendor/:
#    https://www.cnblogs.com/stronghorse/  ("Pdg2Pic" section / linked netdisk)
mkdir -p vendor
cp /path/to/Pdg2Pic.exe vendor/

# 3. Build and start
docker compose up --build

# 4. Open http://localhost:8000 and upload a book archive.
```

Notes:

- Without `vendor/Pdg2Pic.exe` the image still builds and runs; books that
  need the Wine fallback (the encrypted V2 container family) will fail with a
  clear error, everything else converts fine.
- The archive password word list is bundled — nothing else to prepare.
- Check **"OCR text layer"** in the UI when you want selectable/searchable
  text; expect the conversion to take much longer.

## Offline deployment (export / import)

Once the image is built, **the machine running the container no longer needs
internet access**. End users only need network reachability to the host that
serves the web UI (e.g. `http://<host>:8000`); the service depends on no
other network service.

Export the image on the machine that built it (the archive is ~1–2 GB):

```bash
docker compose build
docker save pdg2pdf-web-pdg2pdf | gzip > pdg2pdf-web.tar.gz
```

Copy `pdg2pdf-web.tar.gz` to the target machine by any means (USB, scp …).
The target machine only needs Docker installed — it does **not** need to be
online, and it does **not** need the source tree.

Import and run on the target machine (works fully offline):

```bash
gunzip -c pdg2pdf-web.tar.gz | docker load

docker run -d --name pdg2pdf --restart unless-stopped   -p 8000:8000   -v pdg2pdf-data:/srv/data   -e PDG2PDF_CONVERTER=auto   pdg2pdf-web-pdg2pdf:latest
```

Open `http://<host>:8000`.

Two optional mounts for the target machine:

- `-v /path/to/Pdg2Pic.exe:/srv/vendor/Pdg2Pic.exe:ro` — provide the BYOB
  binary so encrypted-V2 books can fall back to the Wine wrapper.
- `-v /path/to/my-wordlist.txt:/srv/vendor/passwords.txt:ro` plus
  `-e PDG2PDF_PASSWORD_LIST=/srv/vendor/passwords.txt` — use your own
  archive password list.

## Configuration

Environment variables (set them in `docker-compose.yml` or via `-e`):

| Variable | Default | Meaning |
|---|---|---|
| `PDG2PDF_CONVERTER` | `auto` | Backend: `auto`, `native`, `wine_pdg2pic`, `echo`. |
| `PDG2PIC_EXE` | `/srv/vendor/Pdg2Pic.exe` | Path to the deployer-provided binary (BYOB). |
| `PDG2PDF_OCR` | off | Default OCR setting; the web UI checkbox decides per book. |
| `PDG2PDF_PASSWORD_LIST` | bundled `wordlists/archive-passwords.txt` | One archive password per line, tried in order for encrypted archives. |
| `PDG2PDF_DATA_DIR` | `./data` (volume) | Uploads, job state, results. |
| `PDG2PDF_MAX_UPLOAD_MB` | `2048` | Upload size limit. |
| `PDG2PDF_CONVERT_TIMEOUT` | `1800` | Per-book conversion timeout (seconds). |

## The bundled word list

`wordlists/archive-passwords.txt` (315 entries) is a community-collected
list of passwords historically used on e-book sharing archives (zip/rar/7z
attachment passwords), gathered from public sources. It is redistributed
under this project's license. These passwords open **archive files only**;
PDG-level encryption is a separate matter (see Legal notes). Provide your own
list via `PDG2PDF_PASSWORD_LIST`.

## Native engine details

The default engine is a pure-standard-library Python implementation written
from our own format analysis (`docs/FORMAT.md`):

- Pages whose payloads are complete image formats (JPEG, PNG) are converted
  directly. JPEGs are embedded byte-for-byte the way the reference tool does
  (modulo the Adobe APP14 segment, which the reference adds or removes);
  bitonal pages are re-encoded as CCITT G4 with our own T.6 encoder
  (validated with an independent renderer).
- Every page of a book is normalized to one width; bookmarks follow the
  reference rules (section first pages + body page numbers, `cov002` as back
  cover); `BookInfo.dat` becomes a searchable text page.
- Books containing the encrypted V2 'HH' container family raise a fallback
  signal; the `auto` backend then re-runs the whole book through the Wine
  wrapper, so every book still converts.

On our 28-book calibration corpus (kept private; not part of this
repository) the engine matches the reference outputs page-for-page, with
byte-identical image streams on the JPEG books.

## Wine wrapper backend (BYOB)

For encrypted V2 containers, conversion is performed by the original
freeware `Pdg2Pic` (by Jian Ma / strnghrs) running under Wine/Xvfb, driven
by a small Win32 message-level automation program (`driver/pdrive_main.c`,
cross-compiled with MinGW at image build time — no Windows machine needed).
It clicks the real UI: source folder picker (with a tree walk to a staging
directory), start button, auto-dismisses the statistics dialog, and collects
the produced PDF. **The Pdg2Pic binary is NOT part of this repository** —
each deployer provides their own copy in `vendor/`.

## Development

Local run without Docker (echo backend, no Wine needed):

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
PDG2PDF_CONVERTER=echo uvicorn app.main:app --reload
```

Tests (stdlib only):

```bash
python3 -m unittest discover -s tests
```

End-to-end smoke test inside the built image (requires the BYOB exe and a
sample archive):

```bash
cp /path/to/Pdg2Pic.exe vendor/
docker compose build
docker run --rm -v "$PWD/vendor:/opt/orig:ro" \
  -v /path/to/sample.zip:/opt/fake/sample.zip:ro \
  -v "$PWD/scripts:/srv/scripts:ro" \
  pdg2pdf-web-pdg2pdf sh -c \
  'cp /opt/orig/Pdg2Pic.exe /srv/vendor/ && cp /opt/fake/sample.zip /tmp/ && BOOK_ZIP=/tmp/sample.zip sh /srv/scripts/e2e_test.sh'
```

Differential testing against reference outputs (used during development):

```bash
python3 -m scripts.diff_corpus <inbox_dir> <oracle_pdf_dir> <map.json>
```

The `driver/` directory also contains the recon tools (`windowdump`,
`clickdump`) used to discover the UI layout; see `driver/README.md` and
`scripts/recon.sh`.

## Known limitations

- Encrypted V2 'HH' containers need decoder reverse engineering; until then
  they go through the Wine fallback (entry points documented in
  `docs/FORMAT.md` §6b). Requires the BYOB binary.
- DjVu / JPEG2000 payloads: not present in our calibration corpus; the
  engine raises `UnsupportedPayload` and the `auto` backend falls back.
- OCR quality depends on Tesseract (`chi_sim`); weak on old prints and
  handwriting. The OCR layer is applied on the native-engine path only.
- Page width follows each image's own density metadata when the PDG header
  carries none; some books may come out scaled differently from the
  reference tool (a constant factor; see `docs/FORMAT.md` §6).
- One job runs at a time by design; scale by running more containers.

## Legal notes

- `Pdg2Pic` is freeware by Jian Ma (strnghrs), distributed from his blog.
  This project does not redistribute his binary or documentation. The author
  has given personal consent for a CLI/Web port; every deployer should
  obtain the program from the author's own distribution channels.
- This tool is for converting PDG files you are legally entitled to use, for
  personal reading. Encrypted/DRM-protected PDG is out of scope.
- Archive password guessing is limited to the bundled word list (or a
  user-supplied one) and exists solely to open archives you own.

## Roadmap

- [x] Project skeleton: FastAPI app, job queue, archive extraction
- [x] Wine wrapper backend (Win32 driver) + Dockerfile
- [x] Self-developed engine as the default backend (auto-fallback)
- [x] Web UI: drag & drop, inline errors, per-job metadata
- [x] Bookmarks, BookInfo text page, CJK appendix
- [x] CCITT G4 encoding for bitonal pages
- [x] OCR text layer (Tesseract), per-book option
- [x] End-to-end and differential testing
- [ ] Encrypted V2 container decryption (reverse engineering; entry points
      documented in `docs/FORMAT.md`)
- [ ] DjVu / JPEG2000 payload support (needs sample books)
- [ ] Job retention/cleanup policies
- [ ] First release

## License

Apache-2.0. See [LICENSE](LICENSE).
