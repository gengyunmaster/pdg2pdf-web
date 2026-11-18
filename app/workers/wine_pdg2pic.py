"""Phase A backend: drive Pdg2Pic.exe under Wine/Xvfb via the Win32 driver.

Flow per conversion job:
  1. Copy the deployer-provided Pdg2Pic.exe into a writable per-job staging
     dir (the app writes Pdg2Pic.ini / logs next to its own executable).
  2. Locate the directory that actually holds the PDG files (archives often
     nest a top-level folder).
  3. Run driver/pgdrive.exe under Wine: it sets the source-folder edit
     control, clicks the start button, watches for the output PDF and
     dismisses completion/error popups.
  4. Collect the produced PDF. The app's default "target = source folder"
     setting means the PDF appears next to the PDG files.
"""
from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path

from ..archives import Extraction, find_pdg_files
from ..config import PDG2PIC_EXE

DRIVER = Path(__file__).resolve().parents[2] / "driver" / "pdgdrive.exe"
TIMEOUT = int(os.environ.get("PDG2PDF_CONVERT_TIMEOUT", "1800"))



def env_wineprefix() -> str:
    return os.environ.get("WINEPREFIX", str(Path.home() / ".wine"))


def _book_root(extracted: Extraction) -> Path:
    """Directory that directly contains the PDG files."""
    pdgs = find_pdg_files(extracted.extract_dir)
    if not pdgs:
        raise RuntimeError("no PDG files found in the archive")
    parents = {p.parent for p in pdgs}
    if len(parents) == 1:
        return parents.pop()
    # nested layouts: pick the directory holding the majority of pages
    counts: dict[Path, int] = {}
    for p in pdgs:
        counts[p.parent] = counts.get(p.parent, 0) + 1
    return max(counts, key=counts.get)


class WinePdg2PicConverter:
    name = "wine_pdg2pic"

    async def convert(self, extracted: Extraction, out_dir: Path) -> Path:
        if not PDG2PIC_EXE.exists():
            raise RuntimeError(
                f"Pdg2Pic.exe not found at {PDG2PIC_EXE}. Obtain it from the "
                "author's distribution page (see README) or set PDG2PIC_EXE."
            )
        if not DRIVER.exists():
            raise RuntimeError(f"driver not built: {DRIVER} (run 'make -C driver')")

        src = _book_root(extracted)
        stage = out_dir.parent / "wine"
        stage.mkdir(parents=True, exist_ok=True)
        exe = stage / "Pdg2Pic.exe"
        shutil.copyfile(PDG2PIC_EXE, exe)
        # the driver launches Pdg2Pic.exe from its own directory
        driver = stage / "pdgdrive.exe"
        shutil.copyfile(DRIVER, driver)

        # Plant a symlink to the book on the Wine desktop so the driver's
        # tree walk only needs Desktop -> <name> (Wine does not enumerate
        # drive contents inside the folder picker).
        link_name = os.environ.get("PDG2PDF_DESKTOP_NAME", "pdgbook")
        prefix = Path(env_wineprefix())
        for desk in (prefix / "drive_c/users/root/Desktop",
                     prefix / "drive_c/users/Public/Desktop"):
            try:
                desk.mkdir(parents=True, exist_ok=True)
                link = desk / link_name
                if link.exists() or link.is_symlink():
                    if link.is_symlink():
                        link.unlink()
                    else:
                        continue
                link.symlink_to(src.resolve())
            except OSError:
                continue

        env = dict(os.environ)
        env.setdefault("WINEDEBUG", "-1")
        cmd = ["wine", str(driver), "--src", str(src), "--watch", str(src),
               "--name", link_name, "--timeout", str(TIMEOUT)]

        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=stage,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env=env,
        )
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), TIMEOUT + 120)
        except asyncio.TimeoutError:
            proc.kill()
            raise RuntimeError("conversion timed out")
        finally:
            subprocess_wineserver_kill(env)

        text = out.decode("utf-8", "replace") if out else ""
        pdf_line = next((l for l in text.splitlines() if l.startswith("PDF=")), None)
        if proc.returncode != 0 or not pdf_line:
            tail = "\n".join(text.splitlines()[-10:])
            raise RuntimeError(
                f"pdgdrive failed (rc={proc.returncode}): {tail}"
            )
        pdf = Path(pdf_line[4:])
        if not pdf.exists():
            raise RuntimeError(f"pdgdrive reported missing file: {pdf}")
        result = out_dir / "result.pdf"
        out_dir.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(pdf, result)
        return result


def subprocess_wineserver_kill(env: dict) -> None:
    """Best-effort cleanup so a crashed app cannot poison the next job."""
    try:
        import subprocess

        subprocess.run(["wineserver", "-k"], env=env, timeout=15,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass
