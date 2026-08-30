# X Export Web Tool

Web local tối màu để lấy lịch sử bài đăng của một tài khoản X theo khoảng ngày, preview nhanh, dịch tiếng Việt khi có cấu hình và tải CSV.

## Chạy

Trên Windows, double-click:

```text
START_WEB.bat
```

Hoặc chạy trực tiếp:

```bash
python -m src.webapp --root .
```

Mặc định web mở tại:

```text
http://127.0.0.1:8766
```

Các option override:

```bash
python -m src.webapp --root . --host 127.0.0.1 --port 8766 --no-browser
python -m src.webapp --root . --settings path/to/config.yaml
python -m src.webapp --root . --config path/to/monitor-config.json --cookies path/to/cookies
```

## Cấu hình web ở root

Web đọc `config.yaml` ở root repo. File này chỉ quản lý settings của web/export và không thay thế `config/config.json` của monitor CLI.

Mặc định:

```yaml
web:
  host: 127.0.0.1
  port: 8766
  open_browser: true

x:
  monitor_config: config/config.json
  cookies_dir: cookies

translation:
  mode: auto
  provider: gemini
  model: gemini-2.5-flash-lite
  batch_size: 20
  max_attempts_per_batch: 3
  gemini_api_keys: []
```

Các path tương đối được resolve từ root repo.

### Translation mode

`translation.mode` có 3 giá trị:

- `auto`: có Gemini key thì dịch; chưa có key thì **bỏ qua dịch nhưng export vẫn hoàn tất**.
- `off`: luôn bỏ qua dịch.
- `required`: bắt buộc phải có key; thiếu key thì job báo lỗi.

Repo mặc định dùng:

```yaml
translation:
  mode: auto
  gemini_api_keys: []
```

Vì vậy có thể chạy web ngay khi chưa có Gemini API key. Cột `text_vi` trong CSV sẽ để trống và preview sẽ hiện `Chưa dịch`.

Khi có key, thêm vào YAML:

```yaml
translation:
  mode: auto
  provider: gemini
  model: gemini-2.5-flash-lite
  batch_size: 20
  max_attempts_per_batch: 3
  gemini_api_keys:
    key1: YOUR_KEY_1
    key2: YOUR_KEY_2
```

Có thể dùng list thay vì mapping:

```yaml
gemini_api_keys:
  - YOUR_KEY_1
  - YOUR_KEY_2
```

## Cookie X

Web dùng cookie X hiện có.

- Mặc định đọc `cookies/*.json`.
- `x.monitor_config` trỏ tới `config/config.json` để đọc `twitter_accounts`.
- Có thể đổi `x.cookies_dir` trong `config.yaml`.
- CLI monitor hiện tại vẫn tiếp tục dùng config JSON như cũ.

## Cách dùng

1. Nhập username X, có hoặc không có `@` đều được.
2. Chọn `Từ ngày` và `Đến ngày`.
3. Nhấn **Xuất bài đăng**.
4. Trong lúc job chạy, nút Xuất có viền sáng chạy quanh nút.
5. Nếu chưa có Gemini key và mode là `auto`, job tự bỏ qua dịch và tiếp tục ghi CSV.
6. Khi xong, phần preview hiện theo từng ngày. Hai ngày liền nhau được tô hai tint nền nhẹ khác nhau.
7. Nhấn **Tải CSV** để tải file.

Ngày kết thúc là inclusive, giống CLI `export-tweets` hiện tại.

## CSV

CSV dùng UTF-8 BOM và có các cột:

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

Nếu translation bị skip, `text_vi` để trống.

Output mặc định:

```text
exports/<username>/<username>_<start>_<end>.csv
```

## API

```text
GET  /api/health
POST /api/export
GET  /api/jobs/<job_id>
GET  /api/jobs/<job_id>/results?offset=0&limit=200
GET  /api/jobs/<job_id>/csv
```

`GET /api/health` cũng trả `translation_mode` và `translation_has_key` để UI/tooling biết trạng thái runtime.

Web chỉ cho chạy một export job tại một thời điểm để tránh nhiều job cùng tranh cookie/rate limit.

## Test

```bash
python -m compileall -q main.py src
python -m unittest discover -s src/test -p "test_*.py" -v
```

GitHub Actions cũng chạy hai bước này cho branch `feature/**` và pull request.
