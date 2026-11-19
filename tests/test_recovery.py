"""Restart-recovery tests: interrupted jobs are requeued on startup."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.jobs import Job, load, save  # noqa: E402
from app.queueing import recover_pending  # noqa: E402


class RecoverTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.job_dir = Path(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def _mk(self, jid, status):
        job = Job.new(f"{jid}.zip")
        job.id = jid
        job.status = status
        save(self.job_dir, job)
        return job

    def test_running_and_queued_requeued_done_ignored(self):
        self._mk("a", "running")
        self._mk("b", "queued")
        self._mk("c", "done")
        self._mk("d", "error")
        ids = recover_pending(self.job_dir)
        self.assertEqual(ids, ["a", "b"])
        self.assertEqual(load(self.job_dir, "a").status, "queued")
        self.assertEqual(load(self.job_dir, "b").status, "queued")
        self.assertEqual(load(self.job_dir, "c").status, "done")

    def test_corrupt_record_skipped(self):
        (self.job_dir / "bad.json").write_text("{not json", encoding="utf-8")
        self.assertEqual(recover_pending(self.job_dir), [])


if __name__ == "__main__":
    unittest.main()
