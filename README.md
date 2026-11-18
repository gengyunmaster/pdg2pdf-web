# pdg2pdf-web

Convert PDG e-books to PDF through a browser. Upload an archive that contains
PDG files, get a PDF back. All processing happens server-side in a headless
Linux Docker container.

## Status

Phase A functional: the full pipeline (upload archive -> extract -> drive
Pdg2Pic under Wine -> download PDF) works end-to-end. The automation relies
on discoveries from live UI reconnaissance under Wine:

- source selection: the app only accepts a source folder via its own folder
  picker (button `1000`) — the driver walks the picker's tree to a staging
  directory planted on the Wine desktop (Wine pickers cannot resolve
  symlinks or enumerate drive contents, hence the real directory there);
- the auto-statistics modal dialog is auto-dismissed;
- `Pdg2Pic.ini` pre-seeding (UTF-16 `[ParaBlock]`, `PARA_TGT_TYPE=1`,
  `PARA_AUTO_CHK=0`, `PARA_PREVIEW=0`) puts the app into direct-PDF mode;
- the produced PDF is searched in the target directory and the Wine user
  profile directory (the app writes `<source folder name>.pdf` there).

Known limitations: OCR (double-layer PDF) is unsupported (MODI is
Windows-only); encrypted PDG is unsupported (as in the original).

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
- [ ] Web UI polish, job retention/cleanup
- [ ] Phase B: self-developed engine (`FORMAT.md`, pure open-source stack), worker swap
- [ ] Release

## License

Apache-2.0. See [LICENSE](LICENSE).
