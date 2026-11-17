"""FastAPI application: upload, job status, download, static UI."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from .config import JOB_DIR, MAX_UPLOAD_BYTES, RESULT_DIR, UPLOAD_DIR, ensure_dirs
from .jobs import Job, list_all, load, save
from .queueing import runner

app = FastAPI(title="pdg2pdf-web", version="0.1.0")
STATIC_DIR = Path(__file__).parent / "static"
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


@app.on_event("startup")
async def startup() -> None:
    ensure_dirs()
    await runner.start()


@app.post("/api/jobs")
async def create_job(file: UploadFile) -> dict:
    name = _SAFE_NAME.sub("_", Path(file.filename or "upload.bin").name)
    job = Job.new(name)
    save(JOB_DIR, job)

    dest = UPLOAD_DIR / job.filename
    written = 0
    with dest.open("wb") as f:
        while chunk := await file.read(1 << 20):
            written += len(chunk)
            if written > MAX_UPLOAD_BYTES:
                dest.unlink(missing_ok=True)
                raise HTTPException(413, "upload too large")
            f.write(chunk)
    if written == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, "empty upload")

    runner.enqueue(job.id)
    return {"job_id": job.id, "status": job.status}


@app.get("/api/jobs")
async def jobs() -> dict:
    return {"jobs": [vars(j) for j in list_all(JOB_DIR)]}


@app.get("/api/jobs/{job_id}")
async def job_status(job_id: str) -> dict:
    try:
        return vars(load(JOB_DIR, job_id))
    except FileNotFoundError:
        raise HTTPException(404, "job not found")


@app.get("/api/jobs/{job_id}/download")
async def download(job_id: str) -> FileResponse:
    job = await job_status(job_id)
    if job["status"] != "done" or not job["result"]:
        raise HTTPException(409, "job has no result yet")
    path = RESULT_DIR / job["result"]
    if not path.exists():
        raise HTTPException(410, "result was cleaned up")
    return FileResponse(
        path, media_type="application/pdf", filename="book.pdf"
    )


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")
