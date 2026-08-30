import tempfile
import threading
import time
import unittest
from pathlib import Path

from src.services.tweet_export_service import ServiceExportResult
from src.webapp.jobs import ExportJobManager


class _FakeService:
    def __init__(self, root, gate=None, fail=False, translation_status="translated"):
        self.root = Path(root)
        self.gate = gate
        self.fail = fail
        self.translation_status = translation_status

    def export(self, username, start_date, end_date, progress_callback=None):
        if progress_callback:
            progress_callback({
                "stage": "fetching",
                "page": 1,
                "posts_fetched": 1,
                "posts_translated": 0,
                "posts_total": 1,
                "translation_status": "pending",
                "message": "fetch",
            })
        if self.gate is not None:
            self.gate.wait(timeout=2)
        if self.fail:
            raise RuntimeError("boom")
        csv_path = self.root / "out.csv"
        csv_path.write_text("tweet_id,text_vi\n1,x\n", encoding="utf-8")
        translated_count = 1 if self.translation_status == "translated" else 0
        text_vi = "x" if translated_count else ""
        return ServiceExportResult(
            username=username,
            start_date=start_date,
            end_date=end_date,
            csv_path=str(csv_path),
            records=[{"tweet_id": "1", "text_vi": text_vi}],
            pages_fetched=1,
            rows_written=1,
            stop_reason="done",
            translation_status=self.translation_status,
            translated_count=translated_count,
        )


def _wait_job(manager, job_id, timeout=3):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = manager.get(job_id)
        if job["status"] in {"done", "error"}:
            return job
        time.sleep(0.02)
    raise AssertionError("job did not finish")


class WebJobTests(unittest.TestCase):
    def test_job_lifecycle_and_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ExportJobManager(_FakeService(tmp))
            job = manager.start("user", "2026-08-01", "2026-08-02")
            done = _wait_job(manager, job["id"])
            self.assertEqual(done["status"], "done")
            self.assertEqual(done["rows_written"], 1)
            self.assertEqual(done["posts_translated"], 1)
            self.assertEqual(done["translation_status"], "translated")
            self.assertTrue(done["csv_url"].endswith("/csv"))
            result = manager.results(job["id"])
            self.assertEqual(result["total"], 1)
            self.assertEqual(result["translation_status"], "translated")
            self.assertEqual(Path(manager.csv_path(job["id"])).name, "out.csv")

    def test_skipped_translation_is_exposed_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ExportJobManager(
                _FakeService(tmp, translation_status="skipped_no_key")
            )
            job = manager.start("user", "2026-08-01", "2026-08-02")
            done = _wait_job(manager, job["id"])

            self.assertEqual(done["status"], "done")
            self.assertEqual(done["posts_translated"], 0)
            self.assertEqual(done["translation_status"], "skipped_no_key")
            self.assertIn("bỏ qua dịch", done["message"].lower())

    def test_job_failure_is_exposed(self):
        with tempfile.TemporaryDirectory() as tmp:
            manager = ExportJobManager(_FakeService(tmp, fail=True))
            job = manager.start("user", "2026-08-01", "2026-08-02")
            failed = _wait_job(manager, job["id"])
            self.assertEqual(failed["status"], "error")
            self.assertIn("boom", failed["error"])

    def test_only_one_export_runs_at_a_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            gate = threading.Event()
            manager = ExportJobManager(_FakeService(tmp, gate=gate))
            first = manager.start("user", "2026-08-01", "2026-08-02")
            with self.assertRaises(RuntimeError):
                manager.start("other", "2026-08-01", "2026-08-02")
            gate.set()
            self.assertEqual(_wait_job(manager, first["id"])["status"], "done")


if __name__ == "__main__":
    unittest.main()
