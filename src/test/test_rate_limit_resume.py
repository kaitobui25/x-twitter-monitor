import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from src.core.watcher import RateLimitError, _read_rate_limit_reset_at
from src.exporters.tweet_history import TweetHistoryExporter
from src.services.translation_config import TranslationSettings
from src.services.tweet_export_service import TweetExportService


class _FakeClock:
    def __init__(self, now=1000.0):
        self.now = float(now)
        self.sleeps = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


class _FakeWatcher:
    def __init__(self, reset_at):
        self.reset_at = reset_at
        self.search_calls = []
        self.rate_limit_raised = False

    def get_user_by_username(self, username):
        return {"data": {"user": {"result": {"rest_id": "42"}}}}

    def query(self, api_name, params, *, raise_rate_limit=False):
        self.search_calls.append(dict(params))
        if len(self.search_calls) == 1:
            return _timeline_page("101", "Sun Aug 30 10:00:00 +0000 2026", "CURSOR_1")
        if len(self.search_calls) == 2:
            self.rate_limit_raised = True
            raise RateLimitError(api_name, self.reset_at, ["auth1"])
        return _timeline_page("100", "Sat Aug 29 10:00:00 +0000 2026", None)


def _tweet_entry(tweet_id, created_at):
    return {
        "entryId": f"tweet-{tweet_id}",
        "content": {
            "itemContent": {
                "tweet_results": {
                    "result": {
                        "__typename": "Tweet",
                        "rest_id": tweet_id,
                        "legacy": {
                            "id_str": tweet_id,
                            "user_id_str": "42",
                            "created_at": created_at,
                            "full_text": f"tweet {tweet_id}",
                            "conversation_id_str": tweet_id,
                        },
                    }
                }
            }
        },
    }


def _timeline_page(tweet_id, created_at, cursor):
    entries = [_tweet_entry(tweet_id, created_at)]
    if cursor:
        entries.append({
            "entryId": "cursor-bottom",
            "content": {
                "cursorType": "Bottom",
                "value": cursor,
            },
        })
    return {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {
                        "instructions": [{
                            "type": "TimelineAddEntries",
                            "entries": entries,
                        }]
                    }
                }
            }
        }
    }


class _ProgressOnlyExporter:
    def __init__(self, progress_callback):
        self.progress_callback = progress_callback

    def export(self, username, start_dt, end_exclusive, output_path):
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("raw", encoding="utf-8")
        self.progress_callback({
            "stage": "rate_limited",
            "page": 50,
            "total": 1000,
            "message": "X đang giới hạn request. Tự tiếp tục sau 02:15.",
        })
        return SimpleNamespace(
            pages_fetched=50,
            rows_written=0,
            stop_reason="no_bottom_cursor",
        )


class RateLimitResumeTests(unittest.TestCase):
    def test_reset_header_is_read_as_unix_timestamp(self):
        self.assertEqual(
            _read_rate_limit_reset_at({"x-rate-limit-reset": "12345"}, now=1000),
            12345,
        )
        self.assertEqual(
            _read_rate_limit_reset_at({}, now=1000),
            1060,
        )

    def test_export_waits_and_retries_same_cursor_after_429(self):
        clock = _FakeClock(1000)
        watcher = _FakeWatcher(reset_at=1002)
        progress = []

        exporter = TweetHistoryExporter(
            watcher,
            progress_callback=progress.append,
            clock=clock.time,
            sleep=clock.sleep,
        )

        with tempfile.TemporaryDirectory() as tmp:
            result = exporter.export(
                username="target",
                start_dt=datetime(2026, 8, 1, tzinfo=timezone.utc),
                end_exclusive=datetime(2026, 9, 1, tzinfo=timezone.utc),
                output_path=str(Path(tmp) / "out.csv"),
            )

        self.assertTrue(watcher.rate_limit_raised)
        self.assertEqual(result.pages_fetched, 2)
        self.assertEqual(result.rows_written, 2)
        self.assertEqual(len(watcher.search_calls), 3)
        self.assertNotIn("cursor", watcher.search_calls[0])
        self.assertEqual(watcher.search_calls[1]["cursor"], "CURSOR_1")
        self.assertEqual(watcher.search_calls[2]["cursor"], "CURSOR_1")

        waiting = [item for item in progress if item.get("stage") == "rate_limited"]
        self.assertTrue(waiting)
        self.assertEqual(waiting[0]["page"], 1)
        self.assertIn("Tự tiếp tục sau", waiting[0]["message"])
        self.assertEqual(waiting[-1]["rate_limit_remaining_seconds"], 0)
        self.assertGreaterEqual(sum(clock.sleeps), 3)

    def test_service_preserves_rate_limit_countdown_for_web_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cookies = root / "cookies"
            cookies.mkdir()
            (cookies / "auth.json").write_text("{}", encoding="utf-8")
            service = TweetExportService(
                root,
                cookies_dir=cookies,
                translation_settings=TranslationSettings(mode="auto"),
                watcher_factory=lambda users, cookie_dir: object(),
                exporter_factory=lambda watcher, progress, record: _ProgressOnlyExporter(progress),
            )
            progress = []
            service.export(
                "target",
                "2026-08-01",
                "2026-08-30",
                progress_callback=progress.append,
            )

        waiting = [item for item in progress if item.get("stage") == "rate_limited"]
        self.assertEqual(len(waiting), 1)
        self.assertEqual(waiting[0]["page"], 50)
        self.assertEqual(waiting[0]["posts_fetched"], 1000)
        self.assertIn("02:15", waiting[0]["message"])


if __name__ == "__main__":
    unittest.main()
