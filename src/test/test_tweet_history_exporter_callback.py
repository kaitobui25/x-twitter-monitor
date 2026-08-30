import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.exporters.tweet_history import TweetHistoryExporter


class _Watcher:
    def get_user_by_username(self, username):
        return {"data": {"user": {"result": {"rest_id": "42"}}}}

    def query(self, operation, variables):
        self.operation = operation
        self.variables = variables
        return {
            "data": {
                "search_by_raw_query": {
                    "search_timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        {
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {
                                                        "result": {
                                                            "__typename": "Tweet",
                                                            "rest_id": "123",
                                                            "legacy": {
                                                                "user_id_str": "42",
                                                                "id_str": "123",
                                                                "created_at": "Sun Aug 30 03:04:05 +0000 2026",
                                                                "full_text": "Hello &amp; world",
                                                                "conversation_id_str": "123",
                                                            },
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }


class TweetHistoryExporterCallbackTests(unittest.TestCase):
    def test_record_callback_receives_same_record_written_to_csv(self):
        watcher = _Watcher()
        records = []
        exporter = TweetHistoryExporter(watcher, record_callback=records.append)
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "tweets.csv"
            result = exporter.export(
                "user",
                datetime(2026, 8, 30, tzinfo=timezone.utc),
                datetime(2026, 8, 31, tzinfo=timezone.utc),
                str(output),
            )
        self.assertEqual(result.rows_written, 1)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["tweet_id"], "123")
        self.assertEqual(records[0]["text"], "Hello & world")
        self.assertEqual(records[0]["post_type"], "tweet")
        self.assertEqual(watcher.operation, "SearchTimeline")


if __name__ == "__main__":
    unittest.main()
