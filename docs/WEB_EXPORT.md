# X Export Web Tool

Web local tối màu để lấy lịch sử bài đăng của một tài khoản X theo khoảng ngày, dịch sang tiếng Việt, preview nhanh và tải CSV.

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

Các option:

```bash
python -m src.webapp --root . --host 127.0.0.1 --port 8766 --no-browser
python -m src.webapp --root . --config path/to/config.json --cookies path/to/cookies
```

## Cấu hình cần có

Web dùng cùng cookie X và config của monitor hiện tại.

- Cookie JSON trong `cookies/`, hoặc `advanced.cookies_dir` trong config.
- `twitter_accounts` có thể cung cấp danh sách auth account. Nếu không có, web tự lấy tên file `*.json` trong thư mục cookie.
- Dịch tiếng Việt dùng `gemini_api_keys` trong config.

Ví dụ:

```json
{
  "gemini_api_keys": {
    "key1": "YOUR_KEY_1",
    "key2": "YOUR_KEY_2"
  },
  "advanced": {
    "gemini_translation_model": "gemini-2.5-flash-lite"
  }
}
```

`gemini_translation_model` là optional. Nếu không cấu hình, web dùng `gemini-2.5-flash-lite`.

## Cách dùng

1. Nhập username X, có hoặc không có `@` đều được.
2. Chọn `Từ ngày` và `Đến ngày`.
3. Nhấn **Xuất bài đăng**.
4. Trong lúc job chạy, nút Xuất có viền sáng chạy quanh nút.
5. Khi xong, phần preview hiện theo từng ngày. Hai ngày liền nhau được tô hai tint nền nhẹ khác nhau.
6. Nhấn **Tải CSV** để tải file.

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

Web chỉ cho chạy một export job tại một thời điểm để tránh nhiều job cùng tranh cookie/rate limit.

## Test

```bash
python -m compileall -q main.py src
python -m unittest discover -s src/test -p "test_*.py" -v
```

GitHub Actions cũng chạy hai bước này cho branch `feature/**` và pull request.
