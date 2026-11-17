"""Job model and JSON persistence.

State machine: queued -> running -> done | error
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path


@dataclass
class Job:
    id: str
    filename: str          # stored upload file name (sanitized)
    status: str = "queued"
    created: float = field(default_factory=time.time)
    finished: float | None = None
    error: str | None = None
    result: str | None = None   # file name in RESULT_DIR when done
    meta: dict = field(default_factory=dict)

    @staticmethod
    def new(filename: str) -> "Job":
        return Job(id=uuid.uuid4().hex[:12], filename=filename)


def save(job_dir: Path, job: Job) -> None:
    (job_dir / f"{job.id}.json").write_text(
        json.dumps(asdict(job), ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load(job_dir: Path, job_id: str) -> Job:
    data = json.loads((job_dir / f"{job_id}.json").read_text(encoding="utf-8"))
    return Job(**data)


def list_all(job_dir: Path, limit: int = 50) -> list[Job]:
    jobs = [load(job_dir, p.stem) for p in job_dir.glob("*.json")]
    jobs.sort(key=lambda j: j.created, reverse=True)
    return jobs[:limit]
