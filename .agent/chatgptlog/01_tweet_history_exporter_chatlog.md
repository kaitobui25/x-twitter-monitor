# 01 — Tweet History Exporter Chat Log

## Mục tiêu

Xây chức năng lấy toàn bộ bài đăng lịch sử của một tài khoản X theo khoảng ngày, xuất CSV, không tải media.

Ví dụ mục tiêu CLI:

```bash
python main.py export-tweets --username DaanCrypto --start 2025-01-01 --end 2025-02-28
```

## Các vấn đề chính đã gặp và cách giải quyết

### 1. Syndication timeline không phù hợp

- Endpoint syndication trả dữ liệu nhưng mang tính curated/mixed.
- Không đảm bảo đầy đủ và đúng thứ tự thời gian.
- Không có cursor phù hợp để lấy toàn bộ lịch sử.

**Kết luận:** bỏ hướng syndication.

### 2. Legacy Search API bị 403

- Các endpoint search cũ trả `403`.

**Kết luận:** chuyển sang internal GraphQL của X.

### 3. GraphqlAPI lỗi khi khởi tạo `XClientTransaction`

Lỗi:

```text
AttributeError: 'NoneType' object has no attribute 'group'
```

Nguyên nhân:

- Code lấy HTML từ `https://x.com`.
- Trang này không chứa ondemand JS cần thiết.
- `https://x.com/home` có dữ liệu cần để tạo transaction ID.

Fix:

```python
home_page = session.get('https://x.com/home')
```

Sau đó `GraphqlAPI.init()` hoạt động.

### 4. Login bằng requests bị Cloudflare chặn

Flow login cũ:

- guest activate: `200`
- onboarding task: `403 Cloudflare`

Đây không phải lỗi password mà là requests login bị Cloudflare chặn.

**Giải pháp:** dùng Playwright + Chrome DevTools Protocol (CDP) để tận dụng browser thật.

### 5. Kết nối Chrome bằng Playwright/CDP

Chrome được mở với:

```powershell
chrome.exe --remote-debugging-port=9222 --user-data-dir="...\.chrome-debug"
```

Test kết quả:

```text
CDP CONNECT OK
NEW TAB OK
```

Sau đó lấy cookie trực tiếp từ browser context, không cần F12/manual copy.

Cookie cần thiết:

- `auth_token`
- `ct0`

Không ghi giá trị secret vào log.

### 6. Fresh cookie + GraphQL hoạt động

Sau khi lấy cookie mới:

```text
GRAPHQL OK
REST_ID: 918138253617790976
```

Phát hiện schema user mới:

```python
result["core"]["screen_name"]
result["core"]["name"]
```

thay vì lấy từ `legacy`.

### 7. `UserTweetsAndReplies` hoạt động nhưng không tối ưu cho lịch sử xa

Đã test:

- Page 1 lấy được tweet + reply.
- Bottom cursor hoạt động.
- Conversation module có nhiều tweet.
- Pinned tweet xuất hiện lại trên các page.

Lưu ý parser:

- Không recurse toàn bộ JSON để tìm `Tweet`, vì sẽ lẫn quoted tweet của người khác.
- Chỉ đọc tweet nằm trực tiếp trong timeline item/module.
- Filter author bằng user ID.
- Bỏ pinned tweet khi quyết định early stop.
- NoteTweet phải ưu tiên:

```python
tweet["note_tweet"]["note_tweet_results"]["result"]["text"]
```

### 8. Early-stop không được dựa vào tweet đầu tiên

Trong conversation module, tweet có thể không hoàn toàn sort theo timestamp.

**Kết luận:** xử lý toàn page rồi mới dùng min/max timestamp để quyết định dừng.

### 9. SearchTimeline phù hợp hơn cho lịch sử cũ

Test query:

```text
from:DaanCrypto since:2025-01-01 until:2025-03-01
```

`SearchTimeline` trả dữ liệu lịch sử 2025 và có Bottom cursor.

Quan trọng:

- X có thể trả vài tweet ngoài biên ngày query.
- Vì vậy exporter phải tự lọc bằng UTC:

```python
START <= created_at < END_EXCLUSIVE
```

Không được tin hoàn toàn vào `since/until` của X.

### 10. Pagination ban đầu dừng sai ở Page 2

Kết quả ban đầu:

```text
PAGE 1: 17
PAGE 2: 20
STOP: no cursor
TOTAL: 37
```

Nguyên nhân:

- Page 1 Bottom cursor nằm trong `TimelineAddEntries.entries`.
- Page 2 Bottom cursor lại nằm trong `TimelineReplaceEntry.entry`.
- Code cũ chỉ đọc `entries[]`.

Fix:

```python
if isinstance(instruction.get("entry"), dict):
    candidates.append(instruction["entry"])

candidates.extend(instruction.get("entries", []))
```

Sau fix, pagination chạy xuyên suốt.

### 11. Test Jan–Feb 2025 thành công

Kết quả:

```text
PAGE 1 ...
...
PAGE 33: added=19 total=656 newest=2025-01-02 oldest=2024-12-31
STOP: reached before 2025-01-01

TOTAL JAN-FEB: 656
NEWEST: 2025-02-28 12:06:12+00:00
OLDEST: 2025-01-01 08:02:00+00:00
```

=> `SearchTimeline + Bottom cursor + UTC filter + dedupe` hoạt động tốt.

## Exporter đã triển khai

Đã thêm luồng export thật:

- `SearchTimeline`
- pagination bằng Bottom cursor
- xử lý cả `TimelineAddEntries` và `TimelineReplaceEntry`
- filter author ID
- filter ngày theo UTC
- dedupe theo tweet ID
- ưu tiên NoteTweet full text
- không recurse quoted tweet
- phân loại `tweet / reply / quote / retweet`
- xuất CSV

Đường dẫn output mặc định dạng:

```text
exports/DaanCrypto/DaanCrypto_2025-01-01_2025-02-28.csv
```

## Lỗi dependency khi chạy CLI

Lỗi:

```text
ModuleNotFoundError: No module named 'PIL'
```

Fix:

```powershell
pip install Pillow
```

## Phân tích CSV sau export

CSV mới có:

- đúng khoảng ngày
- text dài đầy đủ
- quote metadata hoạt động
- dữ liệu phù hợp để phân tích nội dung

Phát hiện lỗi:

- Một số reply bị gắn `post_type=tweet`.

Ví dụ:

```text
@outpxce Can't wait for the ...
```

có `conversation_id != tweet_id` nhưng thiếu `in_reply_to_*` trong response.

## Fix classifier reply

Classifier mới:

1. Nếu có `in_reply_to_status_id` hoặc `in_reply_to_user_id` => `reply`.
2. Nếu SearchTimeline bỏ các field trên nhưng:

```python
conversation_id != tweet_id
```

=> vẫn là `reply`.
3. Không dùng việc text bắt đầu bằng `@` để đoán reply.

Commit fix:

```text
09422214b4621f194c93cbe76c2896d3c617a77b
fix: classify replies using conversation metadata
```

## Test classifier cuối cùng

PowerShell unit-style test:

```text
OK: normal tweet -> tweet
OK: reply with in_reply_to -> reply
OK: reply missing in_reply_to -> reply
OK: quote -> quote
RESULT: PASS
```

## Trạng thái cuối phiên

Đã xác nhận:

- GraphQL auth hoạt động với fresh browser cookie.
- Historical SearchTimeline hoạt động.
- Pagination nhiều page hoạt động.
- Jan–Feb 2025 lấy được 656 tweet/reply/quote hợp lệ.
- CSV export hoạt động.
- Full NoteTweet text hoạt động.
- Reply classifier đã được sửa và test `PASS`.

Bước tiếp theo ở phiên sau nếu cần: test classifier mới trên 1 page dữ liệu thật rồi export lại CSV để kiểm tra thống kê `tweet / reply / quote` sau fix.
