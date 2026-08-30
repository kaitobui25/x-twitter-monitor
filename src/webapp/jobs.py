from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from src.services.tweet_export_service import (
    ServiceExportResult,
    TweetExportService,
    parse_inclusive_date_range,
    sanitize_username,
)


class ExportJobManager:
    def __init__(self, service: TweetExportService) -> None:
        self.service = service
        self._lock = threading.RLock()
        self._jobs: dict[str, dict] = {}
        self._results: dict[str, ServiceExportResult] = {}
        self._active_job_id: str | None = None

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def start(self, username: str, start_date: str, end_date: str) -> dict:
        username = sanitize_username(username)
        parse_inclusive_date_range(start_date, end_date)

        with self._lock:
            if self._active_job_id:
                active = self._jobs.get(self._active_job_id)
                if active and active.get("status") in {"queued", "running"}:
                    raise RuntimeError("Another export job is already running.")
                self._active_job_id = None

            job_id = uuid.uuid4().hex
            job = {
                "id": job_id,
                "status": "queued",
                "stage": "queued",
                "username": username,
                "start_date": start_date,
                "end_date": end_date,
                "page": 0,
                "posts_fetched": 0,
                "posts_translated": 0,
                "posts_total": 0,
                "translation_status": "pending",
                "message": "Đã xếp hàng tác vụ xuất dữ liệu.",
                "error": None,
                "created_at": self._now(),
                "updated_at": self._now(),
                "rows_written": 0,
                "pages_fetched": 0,
                "stop_reason": None,
                "csv_url": None,
            }
            self._jobs[job_id] = job
            self._active_job_id = job_id

        thread = threading.Thread(
            target=self._run,
            args=(job_id,),
            name=f"x-export-{job_id[:8]}",
            daemon=True,
        )
        thread.start()
        return self.get(job_id)

    def _update(self, job_id: str, **fields) -> None:
        with self._lock:
            job = self._jobs[job_id]
            job.update(fields)
            job["updated_at"] = self._now()

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = dict(self._jobs[job_id])
        self._update(job_id, status="running", stage="fetching")

        def progress(info: dict) -> None:
            allowed = {
                key: info[key]
                for key in (
                    "stage",
                    "page",
                    "posts_fetched",
                    "posts_translated",
                    "posts_total",
                    "translation_status",
                    "message",
                )
                if key in info
            }
            self._update(job_id, status="running", **allowed)

        try:
            result = self.service.export(
                username=job["username"],
                start_date=job["start_date"],
                end_date=job["end_date"],
                progress_callback=progress,
            )
        except Exception as exc:
            self._update(
                job_id,
                status="error",
                stage="error",
                error=str(exc),
                message=f"Xuất dữ liệu thất bại: {exc}",
            )
        else:
            with self._lock:
                self._results[job_id] = result

            if result.translation_status == "skipped_no_key":
                done_message = (
                    f"Hoàn tất: {result.rows_written} bài đăng. "
                    "Đã bỏ qua dịch vì chưa có Gemini API key."
                )
            elif result.translation_status == "disabled":
                done_message = (
                    f"Hoàn tất: {result.rows_written} bài đăng. Dịch tiếng Việt đang tắt."
                )
            else:
                done_message = f"Hoàn tất: {result.rows_written} bài đăng."

            self._update(
                job_id,
                status="done",
                stage="done",
                page=result.pages_fetched,
                pages_fetched=result.pages_fetched,
                posts_fetched=result.rows_written,
                posts_translated=result.translated_count,
                posts_total=result.rows_written,
                translation_status=result.translation_status,
                rows_written=result.rows_written,
                stop_reason=result.stop_reason,
                csv_url=f"/api/jobs/{job_id}/csv",
                message=done_message,
            )
        finally:
            with self._lock:
                if self._active_job_id == job_id:
                    self._active_job_id = None

    def get(self, job_id: str) -> dict:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            return dict(self._jobs[job_id])

    def active(self) -> dict | None:
        with self._lock:
            if not self._active_job_id:
                return None
            job = self._jobs.get(self._active_job_id)
            return dict(job) if job else None

    def results(self, job_id: str, offset: int = 0, limit: int = 200) -> dict:
        if offset < 0:
            raise ValueError("offset must be >= 0")
        if limit < 1 or limit > 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            result = self._results.get(job_id)
            if result is None:
                raise RuntimeError("Export result is not ready.")
            records = result.records[offset:offset + limit]
            return {
                "job_id": job_id,
                "username": result.username,
                "total": len(result.records),
                "offset": offset,
                "limit": limit,
                "translation_status": result.translation_status,
                "translated_count": result.translated_count,
                "records": [dict(record) for record in records],
            }

    def csv_path(self, job_id: str) -> str:
        with self._lock:
            if job_id not in self._jobs:
                raise KeyError(job_id)
            result = self._results.get(job_id)
            if result is None:
                raise RuntimeError("Export CSV is not ready.")
            return result.csv_path
