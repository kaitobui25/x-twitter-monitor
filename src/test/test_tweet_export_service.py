import csv
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from src.services.tweet_export_service import (
    TweetExportService,
    parse_inclusive_date_range,
    sanitize_username,
)


class _FakeTranslator:
    def translate_many(self, texts, progress_callback=None):
        result = [f"VI: {text}" for text in texts]
        if progress_callback:
            progress_callback(len(result), len(result))
        return result


class _FakeExporter:
    def __init__(self, progress_callback, record_callback, records):
        self.progress_callback = progress_callback
        self.record_callback = record_callback
        self.records = records

    def export(self, username, start_dt, end_exclusive, output_path):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("raw", encoding="utf-8")
        for record in self.records:
            self.record_callback(record)
        self.progress_callback({
            "page": 2,
            "added": len(self.records),
            "total": len(self.records),
            "newest": None,
            "oldest": None,
        })
        return SimpleNamespace(
            pages_fetched=2,
            rows_written=len(self.records),
            stop_reason="no_bottom_cursor",
        )


class TweetExportServiceTests(unittest.TestCase):
    def test_username_sanitization_and_validation(self):
        self.assertEqual(sanitize_username("  @DaanCrypto "), "DaanCrypto")
        with self.assertRaises(ValueError):
            sanitize_username("bad-name")
        with self.assertRaises(ValueError):
            sanitize_username("x" * 16)

    def test_inclusive_date_range(self):
        start, end_exclusive = parse_inclusive_date_range("2026-08-01", "2026-08-30")
        self.assertEqual(start.date().isoformat(), "2026-08-01")
        self.assertEqual(end_exclusive.date().isoformat(), "2026-08-31")
        with self.assertRaises(ValueError):
            parse_inclusive_date_range("2026-09-01", "2026-08-30")

    def test_export_collects_translates_and_writes_final_csv(self):
        records = [
            {
                "tweet_id": "2",
                "username": "DaanCrypto",
                "created_at": "2026-08-30T10:00:00+00:00",
                "text": "second",
                "url": "https://x.com/DaanCrypto/status/2",
                "post_type": "tweet",
            },
            {
                "tweet_id": "1",
                "username": "DaanCrypto",
                "created_at": "2026-08-29T10:00:00+00:00",
                "text": "first",
                "url": "https://x.com/DaanCrypto/status/1",
                "post_type": "reply",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cookies = root / "cookies"
            cookies.mkdir()
            (cookies / "authuser.json").write_text("{}", encoding="utf-8")

            service = TweetExportService(
                root,
                watcher_factory=lambda users, cookie_dir: object(),
                exporter_factory=lambda watcher, progress, record: _FakeExporter(
                    progress, record, records
                ),
                translator_factory=lambda config: _FakeTranslator(),
            )
            progress = []
            result = service.export(
                "@DaanCrypto",
                "2026-08-01",
                "2026-08-30",
                progress_callback=progress.append,
            )

            self.assertEqual(result.rows_written, 2)
            self.assertEqual(result.records[0]["tweet_id"], "2")
            self.assertEqual(result.records[0]["text_vi"], "VI: second")
            final_path = Path(result.csv_path)
            self.assertTrue(final_path.is_file())
            raw_path = final_path.parent / ".DaanCrypto_2026-08-01_2026-08-30.raw.csv"
            self.assertFalse(raw_path.exists())

            with final_path.open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["text_vi"], "VI: second")
            self.assertIn("translating", [item.get("stage") for item in progress])
            self.assertEqual(progress[-1]["stage"], "writing")

    def test_zero_posts_writes_header_without_building_translator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cookies = root / "cookies"
            cookies.mkdir()
            (cookies / "auth.json").write_text("{}", encoding="utf-8")
            service = TweetExportService(
                root,
                watcher_factory=lambda users, cookie_dir: object(),
                exporter_factory=lambda watcher, progress, record: _FakeExporter(
                    progress, record, []
                ),
                translator_factory=lambda config: self.fail("translator should not be created"),
            )
            result = service.export("user", "2026-08-01", "2026-08-01")
            self.assertEqual(result.rows_written, 0)
            with open(result.csv_path, "r", encoding="utf-8-sig") as handle:
                header = handle.readline().strip()
            self.assertIn("text_vi", header)


if __name__ == "__main__":
    unittest.main()
