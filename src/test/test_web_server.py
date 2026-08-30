import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.webapp.server import WebApplication, XMonitorHTTPServer, build_handler


class _FakeJobs:
    def __init__(self, csv_path):
        self.csv_path_value = str(csv_path)
        self.started = []

    def active(self):
        return None

    def start(self, username, start_date, end_date):
        self.started.append((username, start_date, end_date))
        if not username.strip().lstrip("@"):
            raise ValueError("Username is required.")
        return {
            "id": "abc",
            "status": "queued",
            "stage": "queued",
            "username": username.strip().lstrip("@"),
            "start_date": start_date,
            "end_date": end_date,
        }

    def get(self, job_id):
        if job_id != "abc":
            raise KeyError(job_id)
        return {"id": "abc", "status": "done", "stage": "done", "csv_url": "/api/jobs/abc/csv"}

    def results(self, job_id, offset=0, limit=200):
        if job_id != "abc":
            raise KeyError(job_id)
        return {
            "job_id": "abc",
            "username": "user",
            "total": 1,
            "offset": offset,
            "limit": limit,
            "records": [{"tweet_id": "1", "text": "hello", "text_vi": "xin chào"}],
        }

    def csv_path(self, job_id):
        if job_id != "abc":
            raise KeyError(job_id)
        return self.csv_path_value


class WebServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        csv_path = Path(self.tmp.name) / "sample.csv"
        csv_path.write_bytes(b"tweet_id,text_vi\n1,xin chao\n")
        self.jobs = _FakeJobs(csv_path)
        app = WebApplication(Path(self.tmp.name), jobs=self.jobs)
        self.server = XMonitorHTTPServer(("127.0.0.1", 0), build_handler(app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        host, port = self.server.server_address
        self.base = f"http://{host}:{port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def _json(self, path, method="GET", body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_export_status_results_and_csv(self):
        status, health = self._json("/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(health["ok"])

        status, job = self._json(
            "/api/export",
            method="POST",
            body={"username": "@user", "start_date": "2026-08-01", "end_date": "2026-08-30"},
        )
        self.assertEqual(status, 202)
        self.assertEqual(job["id"], "abc")

        status, snapshot = self._json("/api/jobs/abc")
        self.assertEqual(snapshot["status"], "done")

        status, results = self._json("/api/jobs/abc/results?offset=0&limit=10")
        self.assertEqual(results["records"][0]["text_vi"], "xin chào")

        with urlopen(self.base + "/api/jobs/abc/csv", timeout=2) as response:
            self.assertEqual(response.status, 200)
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertIn(b"tweet_id", response.read())

    def test_invalid_json_and_unknown_job(self):
        request = Request(
            self.base + "/api/export",
            data=b"not-json",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with self.assertRaises(HTTPError) as ctx:
            urlopen(request, timeout=2)
        self.assertEqual(ctx.exception.code, 400)

        with self.assertRaises(HTTPError) as ctx:
            urlopen(self.base + "/api/jobs/missing", timeout=2)
        self.assertEqual(ctx.exception.code, 404)

    def test_static_ui_contains_running_border_contract(self):
        with urlopen(self.base + "/", timeout=2) as response:
            html = response.read().decode("utf-8")
        with urlopen(self.base + "/static/styles.css", timeout=2) as response:
            css = response.read().decode("utf-8")
        with urlopen(self.base + "/static/app.js", timeout=2) as response:
            js = response.read().decode("utf-8")

        self.assertIn('id="exportButton"', html)
        self.assertIn(".export-button.is-running::before", css)
        self.assertIn("conic-gradient", css)
        self.assertIn("export-border-run", css)
        self.assertIn("day-a", js)
        self.assertIn("day-b", js)
        self.assertIn("textContent", js)


if __name__ == "__main__":
    unittest.main()
