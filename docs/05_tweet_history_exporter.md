# Tweet History Exporter — Debugging Summary

## Mục tiêu

Thêm chức năng export lịch sử post/tweet của một tài khoản X theo khoảng ngày ra CSV:

```powershell
python main.py export-tweets `
  --username DaanCrypto `
  --start 2025-01-01 `
  --end 2025-02-28
```

Output mặc định:

```text
exports/<username>/<username>_<start>_<end>.csv
```

---

## Các vấn đề đã gặp và cách xử lý

### 1. Syndication API không đủ dữ liệu

**Vấn đề:** endpoint `syndication.twitter.com` trả được tweet nhưng dữ liệu bị chọn lọc, không theo timeline đầy đủ và không có cursor phù hợp.

**Xử lý:** bỏ hướng Syndication.

---

### 2. Legacy Search API bị 403

**Vấn đề:** các endpoint Search Adaptive cũ trả HTTP 403.

**Xử lý:** chuyển sang internal GraphQL API của X.

---

### 3. Cookie cũ không còn dùng được

**Vấn đề:** cookie cũ có thể mở `x.com/home` nhưng request API authenticated trả 401.

**Xử lý:** tạo cookie mới bằng Chrome thật + Playwright CDP.

Các cookie quan trọng:

```text
auth_token
ct0
```

---

### 4. Login bằng `requests` bị Cloudflare chặn

**Vấn đề:** flow login của repo gọi `api.x.com/1.1/onboarding/task.json` và nhận HTTP 403 HTML Cloudflare, sau đó lỗi JSON decode.

**Xử lý:** không tiếp tục login bằng `requests`; login trực tiếp trên Chrome rồi lấy cookie bằng Playwright CDP.

---

### 5. Chrome CDP cần profile riêng

**Vấn đề:** Playwright cần attach vào Chrome đang chạy qua remote debugging.

**Xử lý:** chạy Chrome với:

```powershell
chrome.exe `
  --remote-debugging-port=9222 `
  --user-data-dir="C:\...\.chrome-debug"
```

Sau đó Playwright kết nối qua:

```text
http://127.0.0.1:9222
```

---

### 6. `GraphqlAPI` lỗi khi init `XClientTransaction`

**Vấn đề:** `https://x.com` không còn chứa dữ liệu `ondemand` cần thiết, gây lỗi:

```text
AttributeError: 'NoneType' object has no attribute 'group'
```

**Xử lý:** đổi:

```python
session.get('https://x.com')
```

thành:

```python
session.get('https://x.com/home')
```

Sau đó `GraphqlAPI.init()` hoạt động lại.

---

### 7. Shape của User response đã thay đổi

**Vấn đề:** `screen_name` và `name` không còn nằm trong `legacy` như code cũ mong đợi.

**Xử lý:** đọc từ:

```python
result['core']['screen_name']
result['core']['name']
```

`rest_id` vẫn dùng làm user ID.

---

### 8. `UserTweetsAndReplies` có nhiều loại timeline entry

**Vấn đề:** response có:

- tweet thường;
- conversation module;
- pinned tweet;
- quoted tweet;
- Who-to-follow;
- top/bottom cursor.

Nếu recurse toàn bộ JSON sẽ dễ lấy nhầm quoted tweet của user khác.

**Xử lý:** chỉ parse tweet trực tiếp từ timeline item/module, filter theo `user_id`, bỏ pinned khỏi logic early-stop và dedupe theo tweet ID.

---

### 9. Long post bị cắt text

**Vấn đề:** `legacy.full_text` có thể bị truncate.

**Xử lý:** ưu tiên:

```python
tweet['note_tweet']['note_tweet_results']['result']['text']
```

nếu có; fallback về `legacy.full_text`.

---

### 10. `UserTweetsAndReplies` không phù hợp để nhảy thẳng về lịch sử xa

**Vấn đề:** pagination hoạt động nhưng phải kéo từ hiện tại ngược dần, rất tốn request nếu cần dữ liệu năm trước.

**Xử lý:** dùng `SearchTimeline` với query theo khoảng ngày:

```text
from:DaanCrypto since:2025-01-01 until:2025-03-01
```

---

### 11. `until:` của X không đảm bảo boundary chính xác

**Vấn đề:** query `until:2025-03-01` vẫn trả vài tweet ngày 01/03/2025 UTC.

**Xử lý:** luôn filter timestamp lại ở code:

```python
start_dt <= created_at < end_exclusive
```

Với `--end 2025-02-28` thì `end_exclusive = 2025-03-01 00:00 UTC`.

---

### 12. Search pagination dừng ở Page 2 dù vẫn còn dữ liệu

**Vấn đề:** code ban đầu chỉ tìm Bottom cursor trong `instruction['entries']`.

Page 2 lại trả cursor trong `TimelineReplaceEntry` qua `instruction['entry']`.

**Xử lý:** parser phải kiểm tra cả:

```text
instruction.entry
instruction.entries[]
```

Sau khi sửa, pagination chạy liên tục.

---

### 13. Test Jan–Feb 2025 thành công

Kết quả test `DaanCrypto`:

```text
33 pages
656 tweets
NEWEST: 2025-02-28
OLDEST: 2025-01-01
```

Page cuối đã đi sang `2024-12-31`, nên early-stop hoạt động đúng.

---

### 14. Đã thêm exporter thật vào repo

Các file chính:

```text
src/exporters/tweet_history.py
src/exporters/csv_writer.py
main.py
```

CLI:

```powershell
python main.py export-tweets `
  --username DaanCrypto `
  --start 2025-01-01 `
  --end 2025-02-28
```

Exporter hiện dùng:

```text
SearchTimeline
+ Bottom cursor
+ author filter
+ UTC date filter
+ dedupe
+ NoteTweet full text
+ CSV utf-8-sig
```

---

### 15. Chạy CLI bị thiếu `PIL`

**Vấn đề:** `main.py` import monitor modules, trong đó `gemini_extractor.py` import `PIL.Image`, nên dù chỉ chạy exporter vẫn cần Pillow trong môi trường hiện tại.

Lỗi:

```text
ModuleNotFoundError: No module named 'PIL'
```

**Xử lý:** cài:

```powershell
pip install Pillow
```

`Pillow` cũng đã có trong `requirements.txt`.

---

## Kết luận

Hướng cuối cùng ổn định hiện tại:

```text
Chrome login
  -> Playwright CDP lấy cookie
  -> TwitterWatcher
  -> SearchTimeline
  -> cursor pagination
  -> filter đúng user + ngày UTC
  -> dedupe
  -> CSV
```

Điểm quan trọng nhất:

1. Không dùng Syndication để lấy full history.
2. Không dùng requests login khi Cloudflare chặn.
3. `GraphqlAPI` cần load `https://x.com/home`.
4. Search cursor có thể nằm ở cả `entry` và `entries`.
5. Không tin hoàn toàn `since/until`; luôn tự filter timestamp.
6. Không recurse quoted tweet như một post độc lập.
7. Long post phải ưu tiên `NoteTweet` text.
