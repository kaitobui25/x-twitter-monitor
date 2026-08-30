import csv
import os
from typing import Iterable


class CsvWriter:
    FIELDNAMES = [
        'tweet_id',
        'username',
        'created_at',
        'text',
        'url',
        'post_type',
        'conversation_id',
        'in_reply_to_status_id',
        'in_reply_to_user_id',
        'quoted_tweet_id',
        'retweeted_tweet_id',
    ]

    def __init__(self, output_path: str):
        self.output_path = output_path
        self.rows_written = 0
        self._file = None
        self._writer = None

    def __enter__(self):
        directory = os.path.dirname(os.path.abspath(self.output_path))
        os.makedirs(directory, exist_ok=True)
        self._file = open(self.output_path, 'w', encoding='utf-8-sig', newline='')
        self._writer = csv.DictWriter(self._file, fieldnames=self.FIELDNAMES)
        self._writer.writeheader()
        return self

    def write_row(self, record: dict) -> None:
        if self._writer is None:
            raise RuntimeError('CsvWriter is not open.')
        self._writer.writerow({key: record.get(key, '') for key in self.FIELDNAMES})
        self.rows_written += 1

    def write_rows(self, records: Iterable[dict]) -> int:
        before = self.rows_written
        for record in records:
            self.write_row(record)
        return self.rows_written - before

    def __exit__(self, exc_type, exc, tb):
        if self._file is not None:
            self._file.close()
        self._file = None
        self._writer = None
