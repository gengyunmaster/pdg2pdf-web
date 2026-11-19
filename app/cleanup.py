"""Retention cleanup for uploads, results and job records.

Uploaded archives, produced PDFs and job metadata are kept for
PDG2PDF_RETENTION_HOURS (default 24) after a job finishes, then deleted by
a periodic sweep. Set the retention to 0 to keep everything forever.

Work directories are already removed after each job; this covers the
durable files only.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from .config import JOB_DIR, RESULT_DIR, UPLOAD_DIR

SWEEP_INTERVAL_S = 1800  # sweep every 30 minutes


def retention_hours() -> float:
    return float(os.environ.get("PDG2PDF_RETENTION_HOURS", "24"))


def cleanup_once(
    now: float | None = None,
    job_dir: Path = JOB_DIR,
    upload_dir: Path = UPLOAD_DIR,
    result_dir: Path = RESULT_DIR,
    ttl_hours: float | None = None,
) -> int:
    """Delete finished-job artifacts older than the retention window.
    Returns the number of files deleted."""
    ttl = retention_hours() if ttl_hours is None else ttl_hours
    if ttl <= 0:
        return 0
    now = time.time() if now is None else now
    horizon = ttl * 3600
    deleted = 0

    # 1. per-job cleanup: finished/error jobs past their retention
    for jf in job_dir.glob("*.json"):
        try:
            job = json.loads(jf.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if job.get("status") not in ("done", "error"):
            continue
        ref = job.get("finished") or job.get("created") or 0
        if now - ref <= horizon:
            continue
        stored = job.get("meta", {}).get("stored", job.get("filename"))
        for p in (upload_dir / stored, result_dir / f"{job['id']}.pdf"):
            try:
                if p.exists():
                    p.unlink()
                    deleted += 1
            except OSError:
                pass
        try:
            jf.unlink()
            deleted += 1
        except OSError:
            pass

    # 2. orphan sweep: any leftover file older than the horizon
    for d in (upload_dir, result_dir):
        for f in d.glob("*"):
            try:
                if f.is_file() and now - f.stat().st_mtime > horizon:
                    f.unlink()
                    deleted += 1
            except OSError:
                pass
    return deleted


async def cleaner_loop(interval_s: int = SWEEP_INTERVAL_S) -> None:
    while True:
        await asyncio.sleep(interval_s)
        try:
            cleanup_once()
        except Exception:
            pass  # never let the sweeper kill the service
