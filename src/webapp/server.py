from __future__ import annotations

import argparse
import json
import mimetypes
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.services.tweet_export_service import TweetExportService
from src.webapp.jobs import ExportJobManager


STATIC_DIR = Path(__file__).with_name("static")
STATIC_FILES = {
    "/static/styles.css": STATIC_DIR / "styles.css",
    "/static/app.js": STATIC_DIR / "app.js",
}


class WebApplication:
    def __init__(
        self,
        root: Path,
        config_path: Path | None = None,
        cookies_dir: Path | None = None,
        jobs: ExportJobManager | None = None,
    ) -> None:
        self.root = root.resolve()
        if jobs is None:
            service = TweetExportService(
                self.root,
                config_path=config_path,
                cookies_dir=cookies_dir,
            )
            jobs = ExportJobManager(service)
        self.jobs = jobs


class XMonitorHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def _parse_int(query: dict[str, list[str]], name: str, default: int) -> int:
    raw = query.get(name, [str(default)])[0]
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def build_handler(app: WebApplication) -> type[BaseHTTPRequestHandler]:
    class XMonitorHandler(BaseHTTPRequestHandler):
        server_version = "x-monitor-web/1.0"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            try:
                if parsed.path in {"/", "/index.html"}:
                    self._send_file(STATIC_DIR / "index.html", "text/html; charset=utf-8")
                    return
                if parsed.path in STATIC_FILES:
                    path = STATIC_FILES[parsed.path]
                    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                    if content_type.startswith("text/") or content_type in {
                        "application/javascript",
                        "application/json",
                    }:
                        content_type += "; charset=utf-8"
                    self._send_file(path, content_type)
                    return
                if parsed.path == "/api/health":
                    self._send_json({"ok": True, "active_job": app.jobs.active()})
                    return

                job_route = self._job_route(parsed.path)
                if job_route is not None:
                    job_id, suffix = job_route
                    if suffix == "":
                        self._send_json(app.jobs.get(job_id))
                        return
                    if suffix == "/results":
                        query = parse_qs(parsed.query)
                        offset = _parse_int(query, "offset", 0)
                        limit = _parse_int(query, "limit", 200)
                        self._send_json(app.jobs.results(job_id, offset, limit))
                        return
                    if suffix == "/csv":
                        self._send_csv(Path(app.jobs.csv_path(job_id)))
                        return

                self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except KeyError:
                self._send_json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            except Exception as exc:
                self._send_json(
                    {"error": f"internal error: {exc}"},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            try:
                if parsed.path != "/api/export":
                    self._send_json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                    return

                payload = self._read_json()
                username = str(payload.get("username", ""))
                start_date = str(payload.get("start_date", ""))
                end_date = str(payload.get("end_date", ""))
                job = app.jobs.start(username, start_date, end_date)
                self._send_json(job, HTTPStatus.ACCEPTED)
            except ValueError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except RuntimeError as exc:
                self._send_json({"error": str(exc)}, HTTPStatus.CONFLICT)
            except Exception as exc:
                self._send_json(
                    {"error": f"internal error: {exc}"},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        @staticmethod
        def _job_route(path: str) -> tuple[str, str] | None:
            prefix = "/api/jobs/"
            if not path.startswith(prefix):
                return None
            remainder = path[len(prefix):]
            if not remainder:
                return None
            if "/" in remainder:
                job_id, suffix_part = remainder.split("/", 1)
                return job_id, "/" + suffix_part
            return remainder, ""

        def _read_json(self) -> dict:
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length <= 0 or length > 16_384:
                raise ValueError("invalid JSON body size")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("invalid JSON body") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object")
            return payload

        def _send_json(
            self,
            payload: object,
            status: HTTPStatus = HTTPStatus.OK,
        ) -> None:
            body = json.dumps(
                payload,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_response(status.value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_file(self, path: Path, content_type: str) -> None:
            try:
                body = path.read_bytes()
            except OSError:
                self._send_json({"error": "static file not found"}, HTTPStatus.NOT_FOUND)
                return
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(body)

        def _send_csv(self, path: Path) -> None:
            try:
                body = path.read_bytes()
            except OSError:
                self._send_json({"error": "CSV file not found"}, HTTPStatus.NOT_FOUND)
                return
            filename = path.name.replace('"', "")
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args) -> None:  # noqa: A002
            return

    return XMonitorHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="x-monitor-web",
        description="Local dark web UI for exporting historical X posts to translated CSV.",
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--cookies", type=Path, default=None)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.port <= 65535:
        raise SystemExit("error: --port must be between 1 and 65535")

    app = WebApplication(args.root, config_path=args.config, cookies_dir=args.cookies)
    server = XMonitorHTTPServer((args.host, args.port), build_handler(app))
    url = f"http://{args.host}:{args.port}"

    print(f"x-monitor web: {url}")
    print(f"root: {app.root}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
