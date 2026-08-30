from __future__ import annotations

import csv
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from src.core.watcher import TwitterWatcher
from src.exporters.tweet_history import ExportError, TweetHistoryExporter
from src.services.translator import (
    GeminiVietnameseTranslator,
    TranslationError,
    Translator,
    normalize_api_keys,
)


USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
FINAL_FIELDNAMES = [
    "tweet_id",
    "username",
    "created_at",
    "text",
    "text_vi",
    "url",
    "post_type",
    "conversation_id",
    "in_reply_to_status_id",
    "in_reply_to_user_id",
    "quoted_tweet_id",
    "retweeted_tweet_id",
]


class ExportServiceError(RuntimeError):
    pass


@dataclass
class ServiceExportResult:
    username: str
    start_date: str
    end_date: str
    csv_path: str
    records: list[dict]
    pages_fetched: int
    rows_written: int
    stop_reason: str


def sanitize_username(value: str) -> str:
    username = str(value or "").strip().lstrip("@").strip()
    if not username:
        raise ValueError("Username is required.")
    if not USERNAME_RE.fullmatch(username):
        raise ValueError(
            "Invalid X username. Use 1-15 letters, numbers, or underscore characters."
        )
    return username


def parse_inclusive_date_range(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError) as exc:
        raise ValueError("Dates must use YYYY-MM-DD.") from exc

    if start_dt > end_dt:
        raise ValueError("Start date must be before or equal to end date.")
    return start_dt, end_dt + timedelta(days=1)


def _strip_comments(obj: object) -> object:
    if isinstance(obj, dict):
        return {
            key: _strip_comments(value)
            for key, value in obj.items()
            if not str(key).startswith("//")
        }
    if isinstance(obj, list):
        return [_strip_comments(value) for value in obj]
    return obj


def _load_config(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ExportServiceError(f"Cannot read config: {exc}") from exc
    cleaned = _strip_comments(data)
    return cleaned if isinstance(cleaned, dict) else {}


class TweetExportService:
    def __init__(
        self,
        root: str | os.PathLike[str],
        config_path: str | os.PathLike[str] | None = None,
        cookies_dir: str | os.PathLike[str] | None = None,
        watcher_factory: Callable[[list[str], str], object] | None = None,
        exporter_factory: Callable[[object, Callable[[dict], None], Callable[[dict], None]], object] | None = None,
        translator_factory: Callable[[dict], Translator] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.config_path = (
            Path(config_path).resolve()
            if config_path is not None
            else self.root / "config" / "config.json"
        )
        self.cookies_dir_override = Path(cookies_dir).resolve() if cookies_dir else None
        self.watcher_factory = watcher_factory or (
            lambda auth_usernames, cookie_path: TwitterWatcher(auth_usernames, cookie_path)
        )
        self.exporter_factory = exporter_factory or self._default_exporter_factory
        self.translator_factory = translator_factory or self._default_translator_factory

    @staticmethod
    def _default_exporter_factory(watcher, progress_callback, record_callback):
        return TweetHistoryExporter(
            watcher,
            progress_callback=progress_callback,
            record_callback=record_callback,
        )

    @staticmethod
    def _default_translator_factory(config: dict) -> Translator:
        keys = normalize_api_keys(config.get("gemini_api_keys", {}))
        advanced = config.get("advanced", {}) if isinstance(config.get("advanced"), dict) else {}
        model = str(
            advanced.get("gemini_translation_model")
            or config.get("gemini_translation_model")
            or "gemini-2.5-flash-lite"
        )
        return GeminiVietnameseTranslator(keys, model=model)

    def _runtime(self) -> tuple[dict, str, list[str]]:
        config = _load_config(self.config_path)
        advanced = config.get("advanced", {}) if isinstance(config.get("advanced"), dict) else {}

        if self.cookies_dir_override is not None:
            cookies_dir = self.cookies_dir_override
        else:
            configured = advanced.get("cookies_dir")
            if configured:
                path = Path(str(configured))
                cookies_dir = path if path.is_absolute() else self.root / path
            else:
                cookies_dir = self.root / "cookies"

        auth_usernames = []
        accounts = config.get("twitter_accounts", [])
        if isinstance(accounts, list):
            auth_usernames = [
                str(account.get("username", "")).strip()
                for account in accounts
                if isinstance(account, dict) and str(account.get("username", "")).strip()
            ]

        if not auth_usernames and cookies_dir.is_dir():
            auth_usernames = sorted(
                path.stem
                for path in cookies_dir.iterdir()
                if path.is_file() and path.suffix.lower() == ".json"
            )

        if not cookies_dir.is_dir():
            raise ExportServiceError(f"Cookie directory not found: {cookies_dir}")
        if not auth_usernames:
            raise ExportServiceError("No X auth cookie JSON files found.")

        return config, str(cookies_dir), auth_usernames

    @staticmethod
    def _write_final_csv(path: Path, records: list[dict]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FINAL_FIELDNAMES)
            writer.writeheader()
            for record in records:
                writer.writerow({key: record.get(key, "") for key in FINAL_FIELDNAMES})

    def export(
        self,
        username: str,
        start_date: str,
        end_date: str,
        progress_callback: Callable[[dict], None] | None = None,
    ) -> ServiceExportResult:
        username = sanitize_username(username)
        start_dt, end_exclusive = parse_inclusive_date_range(start_date, end_date)
        config, cookies_dir, auth_usernames = self._runtime()

        output_dir = self.root / "exports" / username
        final_path = output_dir / f"{username}_{start_date}_{end_date}.csv"
        raw_path = output_dir / f".{username}_{start_date}_{end_date}.raw.csv"
        records: list[dict] = []

        def emit(payload: dict) -> None:
            if progress_callback:
                progress_callback(payload)

        def fetch_progress(info: dict) -> None:
            emit({
                "stage": "fetching",
                "page": info.get("page", 0),
                "posts_fetched": info.get("total", len(records)),
                "posts_translated": 0,
                "posts_total": 0,
                "message": f"Đang lấy trang {info.get('page', 0)} từ X...",
            })

        def collect(record: dict) -> None:
            records.append(dict(record))

        watcher = self.watcher_factory(auth_usernames, cookies_dir)
        exporter = self.exporter_factory(watcher, fetch_progress, collect)

        emit({
            "stage": "fetching",
            "page": 0,
            "posts_fetched": 0,
            "posts_translated": 0,
            "posts_total": 0,
            "message": "Đang kết nối X và lấy bài đăng...",
        })

        try:
            result = exporter.export(
                username=username,
                start_dt=start_dt,
                end_exclusive=end_exclusive,
                output_path=str(raw_path),
            )

            records.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
            total = len(records)
            if total:
                emit({
                    "stage": "translating",
                    "page": result.pages_fetched,
                    "posts_fetched": total,
                    "posts_translated": 0,
                    "posts_total": total,
                    "message": f"Đang dịch 0/{total} bài sang tiếng Việt...",
                })
                translator = self.translator_factory(config)

                def translation_progress(done: int, count: int) -> None:
                    emit({
                        "stage": "translating",
                        "page": result.pages_fetched,
                        "posts_fetched": total,
                        "posts_translated": done,
                        "posts_total": count,
                        "message": f"Đang dịch {done}/{count} bài sang tiếng Việt...",
                    })

                translated = translator.translate_many(
                    [str(record.get("text", "")) for record in records],
                    progress_callback=translation_progress,
                )
                if len(translated) != total:
                    raise ExportServiceError("Translation result count mismatch.")
                for record, text_vi in zip(records, translated):
                    record["text_vi"] = text_vi
            else:
                translated = []

            emit({
                "stage": "writing",
                "page": result.pages_fetched,
                "posts_fetched": total,
                "posts_translated": len(translated),
                "posts_total": total,
                "message": "Đang ghi CSV...",
            })
            self._write_final_csv(final_path, records)
        except (ExportError, TranslationError, ExportServiceError):
            raise
        except Exception as exc:
            raise ExportServiceError(str(exc)) from exc
        finally:
            try:
                raw_path.unlink(missing_ok=True)
            except OSError:
                pass

        return ServiceExportResult(
            username=username,
            start_date=start_date,
            end_date=end_date,
            csv_path=str(final_path),
            records=records,
            pages_fetched=result.pages_fetched,
            rows_written=len(records),
            stop_reason=result.stop_reason,
        )
