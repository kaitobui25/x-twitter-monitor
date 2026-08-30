# 01 — Plan: TweetHistoryExporter

## 1. Mục tiêu

Build một chức năng độc lập để export lịch sử post/tweet của một tài khoản X.com ra CSV theo khoảng ngày.

Input tối thiểu:

```bash
python main.py export-tweets \
  --username BangXBT \
  --start 2026-01-01 \
  --end 2026-03-31
```

Yêu cầu UX:

- Người dùng nhập username không cần ký tự `@`.
- Nếu vô tình nhập `@BangXBT` thì chương trình vẫn chấp nhận bằng cách normalize `lstrip('@')`.
- `start` và `end` dùng format `YYYY-MM-DD`.
- `end` được hiểu là inclusive đối với người dùng.
- Không download ảnh/video/media.
- Không gọi Gemini.
- Không gửi Telegram/Discord/CQHttp.
- Không dùng StateManager của monitor runtime.
- Không chạy scheduler.
- Output là CSV chứa dữ liệu text/post thô ở mức cần thiết cho phân tích tiếp theo.

---

## 2. Quyết định kiến trúc

Chọn **Phương án 2: TweetHistoryExporter riêng, reuse TwitterWatcher**.

Không thêm historical crawling vào `TweetMonitor`.

Lý do:

- `TweetMonitor` hiện chịu trách nhiệm realtime monitoring, state, notification, media và Gemini.
- Historical export là một finite job: `input -> crawl -> filter -> CSV -> exit`.
- Tách riêng giúp tránh coupling với scheduler/notifier/state/Gemini.
- Tái sử dụng `TwitterWatcher` để giữ nguyên auth cookie, token rotation, 401/429 handling và GraphQL request logic hiện có.

Kiến trúc mục tiêu:

```text
main.py
   |
   | export-tweets command
   v
TweetHistoryExporter
   |
   | resolve username -> user_id
   | paginate UserTweetsAndReplies
   | filter by date
   v
TweetRecord
   |
   v
CsvWriter
   |
   v
exports/<username>/<username>_<start>_<end>.csv
```

Không đi qua:

```text
TweetMonitor
MonitorManager
StateManager
TelegramNotifier
DiscordNotifier
CqhttpNotifier
Gemini extractor
APScheduler
```

---

## 3. File sẽ thêm / sửa

### File mới

```text
src/exporters/__init__.py
src/exporters/tweet_history.py
src/exporters/csv_writer.py
```

Có thể thêm model riêng nếu implementation bắt đầu phình to:

```text
src/models/tweet_record.py
```

Nhưng phase đầu **không bắt buộc**. Có thể dùng `dict` có schema cố định để giữ implementation nhỏ.

### File sửa

```text
main.py
src/utils/parser.py
```

### Không sửa nếu không cần

```text
src/monitors/tweet.py
src/core/watcher.py
src/core/graphql.py
src/utils/state.py
src/notifiers/*
src/utils/gemini_extractor.py
```

Mục tiêu là feature mới có blast radius nhỏ nhất có thể.

---

## 4. CLI contract

Thêm Click command mới vào `main.py`:

```bash
python main.py export-tweets \
  --username BangXBT \
  --start 2026-01-01 \
  --end 2026-03-31
```

Options đề xuất:

```text
--username   required
--start      required, YYYY-MM-DD
--end        required, YYYY-MM-DD
--output     optional
--config     default config/config.json
--cookies    default cookies/
```

Ví dụ custom output:

```bash
python main.py export-tweets \
  --username BangXBT \
  --start 2026-01-01 \
  --end 2026-03-31 \
  --output /tmp/bangxbt.csv
```

Nếu không truyền `--output`:

```text
exports/BangXBT/BangXBT_2026-01-01_2026-03-31.csv
```

### Normalize username

Ngay đầu command/service:

```python
username = username.strip().lstrip('@')
```

Validation:

- username không được rỗng sau normalize.
- start/end phải parse được.
- `start <= end`.
- lỗi validation phải fail fast trước khi gọi X API.

---

## 5. Date semantics

CLI cho người dùng chọn ngày, không chọn timestamp.

Quy ước nội bộ:

```text
start = YYYY-MM-DD 00:00:00 UTC
end_exclusive = (end + 1 day) 00:00:00 UTC
```

Filter:

```python
start_dt <= created_at < end_exclusive
```

Ví dụ:

```text
--start 2026-03-01
--end   2026-03-10
```

sẽ lấy toàn bộ tweet trong:

```text
2026-03-01 00:00:00 UTC
<= created_at <
2026-03-11 00:00:00 UTC
```

Lý do dùng upper bound exclusive: tránh bỏ sót tweet trong ngày `end`.

---

## 6. Historical fetch strategy

### Không reuse `TweetMonitor._get_tweet_list()` trực tiếp

Không import private helper từ monitor.

`TweetHistoryExporter` gọi trực tiếp:

```python
watcher.query('UserTweetsAndReplies', params)
```

và reuse parser pure functions.

### Resolve user ID

```python
user_id = watcher.get_id_by_username(username)
```

Nếu không tìm thấy user:

```text
ExportError: Cannot find X.com user: <username>
```

### Pagination

Không giả định `count=1000` sẽ trả 1000 tweet trong một response.

Phải dùng bottom cursor:

```text
request page 1
   |
   +-- parse tweet_results
   +-- parse cursor-bottom
   v
request page 2(cursor)
   |
   +-- ...
```

Pseudo-code:

```python
cursor = None
seen_cursors = set()

while True:
    params = {
        'userId': user_id,
        'includePromotedContent': False,
        'withVoice': False,
        'count': PAGE_SIZE,
    }

    if cursor:
        params['cursor'] = cursor

    response = watcher.query('UserTweetsAndReplies', params)
    if response is None:
        raise ExportError('Failed to fetch timeline page')

    tweets = extract_tweets(response)

    process current page

    oldest_created_at = find oldest valid tweet timestamp in page
    if oldest_created_at and oldest_created_at < start_dt:
        break

    next_cursor = get_cursor(response)

    if not next_cursor:
        break

    if next_cursor == cursor or next_cursor in seen_cursors:
        break

    seen_cursors.add(next_cursor)
    cursor = next_cursor
```

### Early stop

Đây là optimization bắt buộc.

Khi tweet cũ nhất của page đã cũ hơn `start_dt`, không crawl tiếp timeline.

Không làm:

```text
crawl toàn bộ account -> filter ngày sau
```

Làm:

```text
crawl newest -> older -> stop ngay khi vượt start date
```

---

## 7. Scope của “all post”

Phase 1 dùng endpoint hiện tại của repo:

```text
UserTweetsAndReplies
```

Do đó output có thể chứa:

- tweet gốc;
- reply;
- retweet/repost nếu endpoint trả về;
- quote tweet nếu endpoint trả về.

Phải chỉ giữ item thực sự thuộc target user, tránh timeline instruction/embedded tweet của user khác.

Helper tương đương logic hiện có:

```python
def tweet_belongs_to_user(tweet: dict, user_id: str) -> bool:
    ...
```

Nên đưa helper này vào `src/utils/parser.py` với tên public, không import private function từ `src/monitors/tweet.py`.

### Không promise tuyệt đối rằng X trả “toàn bộ lịch sử account”

Feature sẽ crawl toàn bộ pages mà endpoint cho phép trong date range.

Nếu internal X API giới hạn lịch sử/pagination hoặc thay đổi behavior, exporter phải:

- dừng sạch;
- giữ CSV đã lấy được nếu implementation dùng streaming writer;
- log số page/record đã lấy;
- không tự suy đoán rằng dữ liệu là complete nếu API không cho cursor tiếp.

---

## 8. Không gọi TweetDetail cho từng tweet

Requirement hiện tại không cần media/detail enrichment.

Do đó **không** làm:

```text
UserTweetsAndReplies
  -> TweetDetail(tweet 1)
  -> TweetDetail(tweet 2)
  -> ...
```

Lý do:

- tăng request count rất lớn;
- tăng nguy cơ 429;
- chậm;
- không cần cho CSV text-only.

Mọi field phase 1 nên lấy trực tiếp từ timeline payload.

Nếu một field không tồn tại trong timeline response, để `null/empty` thay vì gọi `TweetDetail` chỉ để enrich.

---

## 9. Parser refactor

Bổ sung các pure helpers vào `src/utils/parser.py`.

Đề xuất:

```python
parse_tweet_id(tweet)
parse_text_from_tweet(tweet)           # đã có
parse_create_time_from_tweet(tweet)    # đã có
parse_tweet_author_id(tweet)
tweet_belongs_to_user(tweet, user_id)
parse_conversation_id(tweet)
parse_in_reply_to_status_id(tweet)
parse_in_reply_to_user_id(tweet)
parse_quoted_tweet_id(tweet)
parse_retweeted_tweet_id(tweet)
parse_tweet_type(tweet)
get_cursor(obj)                        # đã có
```

Nguyên tắc:

- pure functions;
- không log;
- không network;
- không state mutation;
- trả empty/None khi field không có;
- không throw nếu payload thiếu optional fields.

Nếu refactor helper đang có trong `TweetMonitor`, sửa monitor để reuse parser public helper nếu thay đổi nhỏ và an toàn.

---

## 10. CSV schema phase 1

Đề xuất schema:

```text
tweet_id
username
created_at
text
url
post_type
conversation_id
in_reply_to_status_id
in_reply_to_user_id
quoted_tweet_id
retweeted_tweet_id
```

Ý nghĩa:

### `tweet_id`

ID tweet/post.

### `username`

Username target đã normalize.

### `created_at`

ISO-8601 UTC, ví dụ:

```text
2026-03-10T12:34:56+00:00
```

### `text`

`full_text`, convert HTML source nếu cần theo parser hiện tại.

Không thêm media URL.

### `url`

```text
https://x.com/<username>/status/<tweet_id>
```

### `post_type`

Giá trị phase 1:

```text
tweet
reply
quote
retweet
```

Priority classification nếu payload có nhiều marker:

```text
retweet > quote > reply > tweet
```

Nếu payload thực tế cho thấy cần order khác, điều chỉnh sau khi inspect fixture/sample response.

### Relationship IDs

Cho phép downstream phân tích thread/reply/quote mà không cần fetch lại X.

---

## 11. CSV encoding và escaping

Dùng stdlib `csv`, không thêm pandas chỉ để export.

Đề xuất:

```python
open(path, 'w', encoding='utf-8-sig', newline='')
```

Lý do `utf-8-sig`:

- mở tốt trong Excel;
- giữ tiếng Việt / Unicode / emoji.

Dùng `csv.DictWriter` để tự escape:

- dấu phẩy;
- newline trong tweet;
- quote `"`.

Không tự nối string CSV thủ công.

---

## 12. CsvWriter design

`src/exporters/csv_writer.py`

API tối thiểu:

```python
class CsvWriter:
    FIELDNAMES = [...]

    @classmethod
    def write(cls, records, output_path: str) -> int:
        ...
```

Nếu muốn memory-friendly hơn ngay phase 1:

```python
class CsvWriter:
    def __enter__(...): ...
    def write_row(self, record): ...
    def __exit__(...): ...
```

### Khuyến nghị

Ưu tiên **streaming write theo page** thay vì giữ toàn bộ history trong RAM.

Luồng:

```text
page 1 -> filter -> rows -> write
page 2 -> filter -> rows -> write
...
```

Ưu điểm:

- account lớn không tăng RAM tuyến tính;
- nếu process fail giữa chừng, có thể giữ partial file để inspect;
- dễ thêm progress counter.

Nhược điểm:

- dedupe/sort toàn cục khó hơn.

Giải pháp: giữ `seen_tweet_ids: set[str]` để dedupe và endpoint mặc định trả newest -> oldest. Nếu muốn CSV chronological ascending thì có 2 lựa chọn:

1. giữ records trong RAM rồi sort;
2. write newest -> oldest và document order.

**Phase 1 khuyến nghị write newest -> oldest** để giữ memory footprint nhỏ.

Nếu yêu cầu business cần oldest -> newest thì mới đổi strategy.

---

## 13. TweetHistoryExporter API

`src/exporters/tweet_history.py`

Đề xuất:

```python
class TweetHistoryExporter:
    def __init__(self, watcher: TwitterWatcher):
        self.watcher = watcher

    def export(
        self,
        username: str,
        start_dt: datetime,
        end_exclusive: datetime,
        output_path: str,
    ) -> ExportResult:
        ...
```

Nếu chưa cần dataclass:

```python
return {
    'username': username,
    'output_path': output_path,
    'pages_fetched': pages_fetched,
    'rows_written': rows_written,
    'oldest_seen': oldest_seen,
    'newest_seen': newest_seen,
}
```

Nếu dùng dataclass:

```python
@dataclass
class ExportResult:
    username: str
    output_path: str
    pages_fetched: int
    rows_written: int
    oldest_seen: datetime | None
    newest_seen: datetime | None
```

Dataclass là lựa chọn tốt nếu result được dùng ở nhiều nơi; không bắt buộc cho phase 1.

---

## 14. Dedupe

Timeline response của X có thể chứa duplicated tweet instructions / embedded results.

Bắt buộc có:

```python
seen_tweet_ids: set[str] = set()
```

Trước khi write:

```python
if tweet_id in seen_tweet_ids:
    continue
seen_tweet_ids.add(tweet_id)
```

Không dedupe bằng text vì hai tweet khác nhau có thể cùng nội dung.

---

## 15. Filter chính xác target author

Timeline có thể chứa quoted/retweeted/embedded tweet của user khác.

CSV chỉ có một row cho post của target.

Không tạo row riêng cho quoted tweet embedded.

Điều kiện:

```python
tweet_belongs_to_user(tweet, user_id)
```

Sau đó relationship fields có thể chứa ID quote/retweet nếu parse được.

---

## 16. Error handling

Tạo exception riêng nếu hữu ích:

```python
class TweetHistoryExportError(RuntimeError):
    pass
```

Các case:

### Invalid input

Fail fast:

```text
Invalid --start, expected YYYY-MM-DD
Invalid --end, expected YYYY-MM-DD
start date must be <= end date
username must not be empty
```

### User không tồn tại

```text
Cannot find X.com user: <username>
```

### Token/cookie lỗi

Để `TwitterWatcher` thực hiện rotation/error handling hiện tại.

Nếu tất cả token fail và query trả `None`:

```text
Failed to fetch timeline page after all configured X auth accounts were exhausted.
```

### Cursor loop

Nếu X trả cursor lặp:

- log warning;
- stop export;
- không infinite loop.

### Empty page

Nếu page không có tweet nhưng có cursor:

- cho phép tiếp tục tối đa một số page hợp lý hoặc dựa vào cursor progression;
- tránh coi một page rỗng đơn lẻ là EOF tuyệt đối nếu API format có instruction pages.

Phase 1 có thể đơn giản:

- nếu response hợp lệ và cursor mới tồn tại -> continue;
- nếu cursor không đổi/không có -> stop.

---

## 17. Retry strategy

Không duplicate retry/token logic ở exporter nếu `TwitterWatcher` đã xử lý.

Exporter không nên tự:

- đọc cookies;
- build auth headers;
- rotate token;
- xử lý 401/429.

Exporter chỉ xử lý lỗi semantic của export/pagination.

Nếu sau này cần retry page-level riêng, thêm một helper bounded retry, không `while True` vô hạn.

---

## 18. Logging / progress

Không cần notifier.

CLI output đề xuất:

```text
[EXPORT] User: BangXBT
[EXPORT] Range: 2026-01-01 -> 2026-03-31
[EXPORT] Page 1: 18 matching rows, total=18
[EXPORT] Page 2: 14 matching rows, total=32
...
[EXPORT] Reached start date, stopping pagination.
[OK] Exported 426 rows -> exports/BangXBT/BangXBT_2026-01-01_2026-03-31.csv
```

Không print raw API response.

Nếu repo logger hiện tại thuận tiện, có thể tạo logger `tweet-export`; nhưng feature CLI one-shot có thể dùng `click.echo()` cho progress và logger cho debug/error.

---

## 19. Config reuse

Không bắt exporter phụ thuộc vào `telegram.bot_token` nếu không cần.

Hiện config loader của `main.py` phục vụ monitor và có validation Telegram/targets.

Đây là điểm cần xử lý cẩn thận.

### Khuyến nghị

Tách loader tối thiểu cho Twitter auth hoặc thêm helper config-neutral:

```python
def _load_raw_config(path: str) -> dict:
    ...
```

Sau đó:

```text
run command
  -> monitor-specific validation

export-tweets command
  -> chỉ validate twitter_accounts + cookies
```

Không nên bắt người dùng phải cấu hình Telegram chỉ để export CSV.

Refactor nhỏ đề xuất:

```python
def _read_config(path: str) -> dict:
    ...

def _validate_monitor_config(cfg: dict) -> None:
    ...

def _build_twitter_auth_usernames(cfg: dict) -> list[str]:
    ...
```

Giữ backward compatibility cho `run` và `check-tokens`.

Nếu muốn giảm scope phase 1, có thể tạm reuse config hiện tại nhưng cần ghi TODO vì đây là coupling không đẹp.

**Ưu tiên clean implementation: tách raw load + per-command validation.**

---

## 20. Output directory

Default:

```text
exports/<username>/
```

Ví dụ:

```text
exports/BangXBT/BangXBT_2026-01-01_2026-03-31.csv
```

Thêm vào `.gitignore`:

```text
exports/
```

Lý do:

- tránh commit dataset lớn;
- tránh commit dữ liệu scraped ngoài ý muốn.

---

## 21. Tests

Repo hiện chưa có test suite mạnh cho feature này, nên ưu tiên unit tests cho pure logic.

Đề xuất thêm:

```text
tests/test_tweet_history_exporter.py
tests/test_tweet_export_parser.py
tests/test_csv_writer.py
```

Nếu muốn giữ convention hiện tại có `src/test/`, có thể đặt tại đó, nhưng về dài hạn nên dùng root `tests/`.

### Test 1 — username normalize

Input:

```text
@BangXBT
```

Expected:

```text
BangXBT
```

### Test 2 — inclusive end day

Range:

```text
2026-03-01 -> 2026-03-10
```

Tweet:

```text
2026-03-10 23:59:59 UTC
```

Expected: included.

Tweet:

```text
2026-03-11 00:00:00 UTC
```

Expected: excluded.

### Test 3 — target author filter

Page chứa:

- target tweet;
- quoted embedded tweet của user khác.

Expected: chỉ target tweet thành CSV row.

### Test 4 — cursor pagination

Mock:

```text
page1 -> cursor A
page2 -> cursor B
page3 -> no cursor
```

Expected: 3 pages fetched.

### Test 5 — cursor loop guard

Mock:

```text
page1 -> cursor A
page2 -> cursor A
```

Expected: stop, không loop vô hạn.

### Test 6 — early stop

Start:

```text
2026-03-01
```

Page 3 oldest tweet:

```text
2026-02-28
```

Expected: không request page 4.

### Test 7 — dedupe

Hai instruction cùng tweet ID.

Expected: 1 CSV row.

### Test 8 — escaping

Text:

```text
hello, "BTC"
next line
```

Expected: CSV đọc lại bằng `csv.DictReader` trả đúng nguyên text.

### Test 9 — no media side effects

Exporter không gọi:

- `parse_media_from_tweet`;
- HTTP download ảnh;
- Gemini.

### Test 10 — empty date range result

Không có tweet match.

Expected:

- CSV vẫn có header;
- rows_written = 0;
- exit success.

---

## 22. Manual verification

Sau unit test, chạy thử một account có ít tweet:

```bash
python main.py export-tweets \
  --username <test_user> \
  --start 2026-08-01 \
  --end 2026-08-03
```

Kiểm tra:

1. CSV tồn tại.
2. Header đúng schema.
3. Không có duplicate tweet_id.
4. Tweet nằm đúng date range.
5. URL mở đúng tweet.
6. Không có file ảnh mới trong `follower/`.
7. Không có Gemini request.
8. Không có Telegram message.
9. Không ghi `state/state.json`.

Sau đó test username có `@`:

```bash
python main.py export-tweets \
  --username @<test_user> \
  --start 2026-08-01 \
  --end 2026-08-03
```

Output phải tương đương username không có `@`.

---

## 23. Acceptance criteria

Feature hoàn thành khi tất cả điều kiện sau đạt:

- [ ] Có CLI command `export-tweets`.
- [ ] Chấp nhận username không có `@`.
- [ ] Chấp nhận username có `@` và normalize chính xác.
- [ ] Validate `YYYY-MM-DD`.
- [ ] `end` inclusive.
- [ ] Resolve username -> user_id bằng `TwitterWatcher`.
- [ ] Dùng `UserTweetsAndReplies`.
- [ ] Có bottom-cursor pagination.
- [ ] Có guard cursor loop.
- [ ] Có early-stop khi vượt `start`.
- [ ] Chỉ lấy post thuộc target user.
- [ ] Dedupe bằng tweet ID.
- [ ] Không gọi `TweetDetail` cho từng tweet trong phase 1.
- [ ] Không lấy/download media.
- [ ] Không gọi Gemini.
- [ ] Không gửi notifier.
- [ ] Không mutate monitor state.
- [ ] CSV UTF-8 compatible với Unicode/emoji.
- [ ] CSV có header khi 0 rows.
- [ ] Default output nằm trong `exports/<username>/`.
- [ ] `exports/` được gitignore.
- [ ] Có progress summary: pages fetched + rows written + output path.
- [ ] Existing `run`, `check-tokens`, `login` không bị regress.

---

## 24. Implementation order

### Step 1 — Parser helpers

Sửa `src/utils/parser.py`:

- author ID;
- tweet ID;
- belongs-to-user;
- relationship IDs;
- post type.

Unit test pure parser trước.

### Step 2 — CsvWriter

Tạo:

```text
src/exporters/__init__.py
src/exporters/csv_writer.py
```

Test Unicode/newline/quotes/empty output.

### Step 3 — TweetHistoryExporter

Tạo:

```text
src/exporters/tweet_history.py
```

Implement:

- user resolution;
- page request;
- cursor pagination;
- date filtering;
- dedupe;
- early stop;
- row mapping;
- result stats.

Mock `TwitterWatcher` trong tests; không hit X API trong unit tests.

### Step 4 — Config separation

Refactor config loading trong `main.py` để exporter không phụ thuộc Telegram/monitor targets.

Đảm bảo `run` behavior cũ không đổi.

### Step 5 — CLI

Thêm command `export-tweets` vào `main.py`.

Wire:

```text
config
-> auth usernames
-> cookies_dir
-> TwitterWatcher
-> TweetHistoryExporter
```

### Step 6 — `.gitignore`

Thêm:

```text
exports/
```

### Step 7 — Manual smoke test

Test account thật với range 1-3 ngày trước, sau đó range dài hơn.

---

## 25. Những thứ cố tình chưa làm trong phase 1

Không build sớm các feature sau:

- media download;
- image URL columns;
- Gemini;
- CSV + JSONL đồng thời;
- SQLite/Postgres;
- resume checkpoint;
- parallel page fetch;
- async crawler;
- historical likes/following;
- browser scraping fallback;
- automatic retry vô hạn;
- TweetDetail enrichment cho mọi record.

Lý do: giữ feature nhỏ, deterministic, dễ test và ít ảnh hưởng monitor đang chạy.

---

## 26. Phase 2 có thể mở rộng sau

Khi phase 1 ổn định, architecture này có thể thêm mà không sửa core crawler nhiều:

```text
--format csv|jsonl
--include-replies / --exclude-replies
--include-retweets / --exclude-retweets
--max-pages N
--resume
--output-order asc|desc
--raw-json
```

Có thể tách tiếp:

```text
TweetHistoryFetcher
    |
    +-> CsvWriter
    +-> JsonlWriter
    +-> DatabaseWriter
```

Chỉ làm khi có requirement thật, tránh over-engineering phase 1.

---

## 27. Rủi ro chính

### Rủi ro 1 — X internal API thay đổi

Repo đang phụ thuộc internal GraphQL endpoint/transaction metadata.

Mitigation:

- tất cả request tiếp tục đi qua `TwitterWatcher` + `GraphqlAPI`;
- exporter không hard-code auth/header riêng.

### Rủi ro 2 — timeline không cung cấp history vô hạn

Mitigation:

- wording CLI/docs là crawl tất cả pages X trả được trong range;
- report pages/rows;
- không claim completeness khi endpoint hết cursor bất thường.

### Rủi ro 3 — duplicate/embedded tweet

Mitigation:

- filter author ID;
- dedupe tweet ID.

### Rủi ro 4 — account rất lớn

Mitigation:

- early stop theo start date;
- streaming CSV;
- không TweetDetail N+1.

### Rủi ro 5 — config coupling

Mitigation:

- tách raw config load và per-command validation.

---

## 28. Definition of done

Feature được coi là done khi có thể chạy:

```bash
python main.py export-tweets \
  --username BangXBT \
  --start 2026-01-01 \
  --end 2026-01-31
```

và nhận được:

```text
exports/BangXBT/BangXBT_2026-01-01_2026-01-31.csv
```

với các tính chất:

- chỉ chứa post của `BangXBT` trong range;
- không media processing;
- không Gemini;
- không notifier;
- không state mutation;
- crawl nhiều page bằng cursor;
- dừng sớm khi vượt start date;
- không duplicate tweet ID;
- code historical export độc lập với realtime monitor.
