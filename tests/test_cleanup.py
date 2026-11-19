"""Retention cleaner tests."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.cleanup import cleanup_once  # noqa: E402

NOW = 1_800_000_000.0


class CleanupTest(unittest.TestCase):
    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        d = Path(self.td.name)
        self.job_dir = d / "jobs"
        self.up_dir = d / "uploads"
        self.res_dir = d / "results"
        for p in (self.job_dir, self.up_dir, self.res_dir):
            p.mkdir()

    def tearDown(self):
        self.td.cleanup()

    def _job(self, jid, status, finished, stored=None, name="book.zip"):
        meta = {"stored": stored or f"{jid}_{name}"}
        (self.job_dir / f"{jid}.json").write_text(json.dumps(
            {"id": jid, "filename": name, "status": status,
             "created": finished - 100, "finished": finished,
             "meta": meta}), encoding="utf-8")

    def _mk(self, path: Path, age_hours: float):
        path.write_bytes(b"x")
        import os
        os.utime(path, (NOW - age_hours * 3600,) * 2)

    def run_clean(self, ttl=24.0):
        return cleanup_once(now=NOW, job_dir=self.job_dir,
                            upload_dir=self.up_dir, result_dir=self.res_dir,
                            ttl_hours=ttl)

    def test_old_done_job_removed_everywhere(self):
        self._job("j1", "done", NOW - 100 * 3600)
        self._mk(self.up_dir / "j1_book.zip", 100)
        self._mk(self.res_dir / "j1.pdf", 100)
        self.assertEqual(self.run_clean(), 3)
        self.assertFalse((self.job_dir / "j1.json").exists())
        self.assertFalse((self.up_dir / "j1_book.zip").exists())
        self.assertFalse((self.res_dir / "j1.pdf").exists())

    def test_recent_job_kept(self):
        self._job("j2", "done", NOW - 3600)
        self._mk(self.up_dir / "j2_book.zip", 1)
        self._mk(self.res_dir / "j2.pdf", 1)
        self.assertEqual(self.run_clean(), 0)
        self.assertTrue((self.res_dir / "j2.pdf").exists())

    def test_running_job_never_removed(self):
        self._job("j3", "running", NOW - 100 * 3600)
        self._mk(self.up_dir / "j3_book.zip", 100)
        self.assertEqual(self.run_clean(), 0)

    def test_orphan_files_swept(self):
        self._mk(self.up_dir / "stray.zip", 100)
        self._mk(self.res_dir / "stray.pdf", 100)
        self.assertEqual(self.run_clean(), 2)

    def test_disabled_retention_keeps_everything(self):
        self._job("j4", "done", NOW - 100 * 3600)
        self._mk(self.up_dir / "j4_book.zip", 100)
        self.assertEqual(self.run_clean(ttl=0), 0)


if __name__ == "__main__":
    unittest.main()
