# 02 — X Export Web Tool Plan

## Mục tiêu

Xây một web tool local tối màu cho `x-twitter-monitor`, dựa trên cách tổ chức web app của repo `stockdata`, nhưng tái sử dụng logic X GraphQL/export hiện có thay vì tạo crawler mới.

Web v1 có một nhiệm vụ chính:

1. Nhập username X, không bắt buộc `@`.
2. Chọn ngày bắt đầu và ngày kết thúc (ngày kết thúc inclusive, cùng semantics với CLI hiện tại).
3. Nhấn **Xuất bài đăng**.
4. Trong lúc đang chạy, nút Xuất có **viền sáng chạy xung quanh** để biểu thị job đang hoạt động.
5. Backend lấy toàn bộ bài trong khoảng ngày bằng `TweetHistoryExporter`/`SearchTimeline` hiện có.
6. Dịch nội dung sang tiếng Việt bằng Gemini, dùng pool key trong config.
7. Xuất CSV UTF-8 BOM để mở tốt trong Excel.
8. Hiển thị preview phía dưới gồm ngày/giờ, nội dung gốc, bản dịch tiếng Việt và link X dạng rút gọn để hiển thị nhưng href vẫn là URL thật.
9. Các nhóm ngày liên tiếp dùng hai màu nền nhạt xen kẽ để dễ theo dõi.

## Nguyên tắc kiến trúc

- Không đưa logic GraphQL vào web server.
- Không phình `main.py`.
- Web server chỉ làm HTTP routing/static serving.
- Job manager quản lý thread/progress/error state.
- Service layer điều phối watcher -> exporter -> translator -> CSV.
- Translator có interface riêng để dễ mock/test và thay provider.
- Không cần React/Node/Vite; dùng stdlib `ThreadingHTTPServer` + vanilla HTML/CSS/JS giống tinh thần `stockdata`.
- Không dùng dịch vụ URL shortener bên ngoài; chỉ rút gọn phần text hiển thị.
- Không đọc lại CSV để tạo preview: exporter phát record callback, service giữ record trong memory rồi ghi CSV enriched cuối cùng.

## Cấu trúc dự kiến

```text
src/
  services/
    __init__.py
    translator.py
    tweet_export_service.py
  webapp/
    __init__.py
    __main__.py
    jobs.py
    server.py
    static/
      index.html
      styles.css
      app.js
src/test/
  test_translator.py
  test_tweet_export_service.py
  test_web_jobs.py
  test_web_server.py
START_WEB.bat
.github/workflows/test.yml
```

## Backend flow

```text
POST /api/export
  -> validate username/date
  -> ExportJobManager.start()
  -> worker thread
      -> resolve auth cookie accounts
      -> TwitterWatcher
      -> TweetHistoryExporter(record_callback=...)
      -> GeminiVietnameseTranslator.translate_many()
      -> write final translated CSV
      -> expose preview records + CSV path
```

## API v1

- `GET /api/health`
- `POST /api/export`
- `GET /api/jobs/{job_id}`
- `GET /api/jobs/{job_id}/results?offset=0&limit=200`
- `GET /api/jobs/{job_id}/csv`

## Job state

Các stage chuẩn:

- `queued`
- `fetching`
- `translating`
- `writing`
- `done`
- `error`

Progress payload giữ các số liệu:

- page hiện tại
- số post đã lấy
- số post đã dịch
- tổng post cần dịch
- message cho UI

## Translation

- Đọc `gemini_api_keys` từ `config/config.json`.
- Hỗ trợ dict (`key1`, `key2`, ...) và list.
- Batch nhiều tweet trong một request để tránh quá nhiều API call.
- Round-robin key giữa các batch/retry.
- Bắt buộc Gemini trả JSON array đúng thứ tự input.
- Retry hữu hạn; nếu vẫn lỗi thì fail job rõ ràng thay vì sinh bản dịch giả.
- Tweet tiếng Việt vẫn đi qua translator; model được yêu cầu giữ nguyên ý và không thêm bình luận.

## CSV

Final CSV giữ metadata hiện có và thêm `text_vi` ngay sau `text`:

```text
tweet_id
username
created_at
text
text_vi
url
post_type
conversation_id
in_reply_to_status_id
in_reply_to_user_id
quoted_tweet_id
retweeted_tweet_id
```

File mặc định:

```text
exports/<username>/<username>_<start>_<end>.csv
```

Exporter core vẫn ghi raw file tạm trong lúc fetch; service xoá raw file sau khi final CSV đã ghi xong hoặc khi job fail.

## UI

Dark utility UI, ưu tiên đọc nhanh và ít decoration.

Form đầu trang:

- Username
- Từ ngày
- Đến ngày
- Nút `Xuất bài đăng`

Trong lúc job chạy:

- disable form controls để tránh chạy đè job
- nút đổi text thành `Đang xuất...`
- thêm class `is-running`
- pseudo-element dùng `conic-gradient` + animation quay quanh border để tạo viền sáng chạy liên tục
- progress text hiển thị stage/page/post count

Sau khi hoàn tất:

- nút `Tải CSV`
- preview tối đa theo pagination API
- mỗi post: timestamp, Original, Tiếng Việt, link X
- link hiển thị `x.com/<username>/status/<prefix>…`, nhưng `href` là URL đầy đủ, mở tab mới
- group theo ngày local của browser
- day group index chẵn/lẻ dùng hai tint nền nhẹ khác nhau

## Validation và lỗi

- strip `@` ở cả frontend và backend
- username rỗng -> 400
- username chỉ cho phép ký tự hợp lệ của X (`A-Z`, `a-z`, `0-9`, `_`, tối đa 15 ký tự)
- date sai format -> 400
- start > end -> 400
- không có cookie auth -> job error rõ ràng
- không có Gemini key -> job error rõ ràng
- X user không tồn tại -> job error từ exporter
- Gemini lỗi -> retry rồi job error
- zero posts -> job `done`, CSV vẫn có header và preview empty state
- download chỉ dùng CSV path được giữ trong job state; không nhận arbitrary filesystem path từ client

## Test plan

### Unit

- sanitize/validate username
- parse inclusive date range
- translator parse fenced/plain JSON
- translator batch order + key rotation + retry
- service collect exporter records, translate, write enriched CSV
- raw temp cleanup
- zero-post export
- job lifecycle queued -> running -> done
- job error state
- single-active-job conflict

### HTTP integration

Khởi động server trên port `0` với fake service/job manager và test bằng stdlib HTTP client:

- `/api/health`
- `POST /api/export`
- invalid JSON/input
- job status
- paginated results
- CSV download headers/body
- unknown route/job -> 404

### Static/UI smoke

- index chứa form và các id JS cần thiết
- CSS có `.export-button.is-running` và animation border
- JS có day-group alternating render + safe text insertion

### CI

Thêm GitHub Actions chạy Python 3.11:

```bash
python -m unittest discover -s src/test -p 'test_*.py'
```

Không chạy test Telegram thủ công vì file đó không phải `unittest.TestCase` và cần secret thật.

## Definition of done

- Web chạy bằng `START_WEB.bat` hoặc `python -m src.webapp`.
- Browser tự mở local URL mặc định `http://127.0.0.1:8766`.
- Export thật dùng lại X SearchTimeline core hiện có.
- Dịch tiếng Việt được ghi vào preview và CSV.
- Nút Xuất có viền sáng chạy đúng thời gian job đang chạy và dừng khi done/error.
- Hai ngày liền nhau có hai màu tint xen kẽ.
- Tests mới pass trên CI.
- Không làm hỏng CLI `export-tweets` hiện tại.
