"""In-process asyncio job runner with JSON-persisted state.

Jobs survive a restart: state files live under DATA_DIR/jobs and a queued
job is re-run after startup. One job at a time (the wrapped application is
single-instance by design); scale by running more containers.
"""
from __future__ import annotations

import asyncio
import shutil
import traceback
from pathlib import Path

from .archives import extract_any, load_passwords
from .config import (
    CONVERTER_BACKEND, JOB_DIR, PASSWORD_LIST_FILE, RESULT_DIR,
    UPLOAD_DIR, WORK_DIR, ensure_dirs,
)
from .jobs import Job, load, save
from .workers import get_converter


class JobRunner:
    def __init__(self, backend: str = CONVERTER_BACKEND) -> None:
        self.backend = backend
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        ensure_dirs()
        self._task = asyncio.create_task(self._loop(), name="job-runner")

    async def _loop(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run(job_id)
            finally:
                self._queue.task_done()

    def enqueue(self, job_id: str) -> None:
        self._queue.put_nowait(job_id)

    async def _run(self, job_id: str) -> None:
        job = load(JOB_DIR, job_id)
        job.status = "running"
        save(JOB_DIR, job)
        work = WORK_DIR / job_id
        try:
            src = UPLOAD_DIR / job.filename
            passwords = load_passwords(PASSWORD_LIST_FILE)
            extracted = extract_any(src, work / "book", passwords)
            pdf = await get_converter(self.backend).convert(
                extracted, work / "out"
            )
            result = RESULT_DIR / f"{job.id}.pdf"
            shutil.copyfile(pdf, result)
            job.status = "done"
            job.result = result.name
            job.meta = {
                "archive_format": extracted.fmt,
                "archive_password_used": extracted.password is not None,
                "extracted_files": extracted.file_count,
                "backend": self.backend,
            }
        except Exception as exc:  # noqa: BLE001 - report any failure to the UI
            job.status = "error"
            job.error = "".join(
                traceback.format_exception_only(type(exc), exc)
            ).strip()[:2000]
        finally:
            import time

            job.finished = time.time()
            save(JOB_DIR, job)
            shutil.rmtree(work, ignore_errors=True)


runner = JobRunner()
