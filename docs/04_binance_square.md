# Binance Square Integration Guide

## 1. Overview
The Twitter Monitor system has been successfully refactored to support multi-platform monitoring. It now officially supports monitoring **Binance Square** profiles alongside X (Twitter) accounts. 

The Binance Square integration allows the system to:
- Automatically check specified Binance Square profiles (e.g., `gem10x`) at regular intervals.
- Download the text and images of any new posts.
- Route images containing technical analysis charts through the existing **Gemini AI Extraction Pipeline** to automatically extract `Entry`, `Stoploss`, and `TakeProfit` levels.
- Push the results and the post URL to Telegram/Discord via the unified notification system.

## 2. Technical Architecture

### 2.1 Overcoming the AWS WAF Challenge
Binance protects its Square platform with an aggressive AWS WAF (Web Application Firewall) backed by CloudFront. Standard scraping tools (like `requests` or `curl-cffi`) receive an HTTP 202 response and a JavaScript challenge (`gokuProps`) instead of the actual data.

To bypass this reliably, the system uses **Playwright** (Headless Chromium) in a `Discover-and-Reuse` pattern:
1. **Discovery Phase**: On the very first run, `BinanceWatcher` launches a hidden Chromium instance, navigates to the target profile, and solves the JS challenge. It listens to the network traffic to capture the actual underlying `bapi` data endpoints, the target user's internal UUID (`targetSquareUid`), and all required HTTP headers (including anti-bot cookies).
2. **Reuse Phase**: Once the endpoint and headers are captured, the browser is closed. All subsequent polls are executed using standard, lightweight Python `requests` directly against the captured API. This ensures low memory usage on the VPS while completely bypassing the WAF.

### 2.2 Class Hierarchy
The codebase follows an Open/Closed principle architecture:
- `MonitorBase`: The core, platform-agnostic base class handling state persistence, notification routing, and logging.
- `TwitterMonitorBase`: Inherits from `MonitorBase` and injects Twitter-specific auth logic (used by Tweet, Profile, Like, and Following monitors).
- `BinanceSquareMonitor`: Inherits directly from `MonitorBase`. It fetches data via `BinanceWatcher` and processes images through `extract_chart()`.

## 3. Configuration

To monitor a new Binance Square account, add it to the `binance_targets` array in `config/config.json`. You do **not** need Twitter cookies to run Binance monitors.

```json
{
    "binance_targets": [
        {
            "handle": "gem10x",
            "title": "Gem10x",
            "notify_telegram_chat_ids": [123456789]
        }
    ]
}
```

## 4. Dependencies
Deploying this feature to a new server requires Playwright. Run the following commands during server setup:
```bash
pip install -r requirements.txt
python -m playwright install chromium
```
*(Note: Ensure your VPS has at least 1GB of RAM to comfortably handle the initial Chromium launch during the Discovery phase).*


# Báo Cáo Hành Trình Kỹ Thuật: Tích Hợp Binance Square & Tái Cấu Trúc Hệ Thống

Tài liệu này ghi lại toàn bộ quá trình tư duy (Chain of Thought), phương pháp kiểm chứng kỹ thuật, và các bài học từ những thất bại trong quá trình mở rộng `twitter-monitor` thành một framework đa nền tảng.

---

## 1. Tư Duy Từ Kế Hoạch Đến Hiện Thực Hóa Bằng Code

### Vấn đề cốt lõi ban đầu
Khi nhận yêu cầu tích hợp Binance Square, tôi nhận thấy hệ thống cũ đang bị **"ràng buộc cứng" (tightly coupled)**. Lớp `MonitorBase` (trái tim của hệ thống) lại chứa các logic chuyên biệt của Twitter (như `TwitterWatcher`, `cookies`, hàm kiểm tra `on_signout`). 

Nếu nhét thẳng Binance vào kiến trúc này, code sẽ trở thành một mớ hỗn độn (spaghetti code), và người dùng sẽ bị ép phải có cookie Twitter cấu hình sẵn thì mới chạy được bot Binance.

### Cách giải quyết (Tái cấu trúc Phase 1)
Tôi quyết định áp dụng nguyên tắc **Open/Closed Principle (Mở để mở rộng, Đóng để sửa đổi)**:
1. **Trừu tượng hóa**: Rút cạn các logic liên quan đến Twitter ra khỏi `MonitorBase`. Biến nó thành một class thuần túy làm nhiệm vụ: Lưu state, Ghi log, và Gửi thông báo (Telegram/Discord).
2. **Kế thừa**: Tạo ra `TwitterMonitorBase` chứa logic Twitter cũ. Đổi tất cả các monitor hiện tại (Tweet, Like, Profile, Following) sang kế thừa class mới này.
3. **Mở rộng**: Tạo `BinanceSquareMonitor` kế thừa trực tiếp từ `MonitorBase` độc lập hoàn toàn với nhánh Twitter.

*Kết quả:* Hệ thống cũ không bị gãy một dòng code nào, trong khi hệ thống mới có không gian sạch sẽ để phát triển.

---

## 2. Quá Trình Kiểm Chứng Để Chọn Hướng Đi Tốt Nhất

Làm sao để lấy được bài viết của `@gem10x`? Đây là bài toán khó nhất của dự án do các lớp bảo mật của Binance.

### Bước 1: Thử nghiệm API cơ bản (Requests thuần)
Tôi viết script `probe_binance.py` gửi GET/POST request thẳng đến trang profile.
👉 **Kết quả:** Thất bại. Trả về HTTP 202 với nội dung HTML chứa đoạn script `gokuProps`. Tôi lập tức nhận diện đây là **AWS WAF (Web Application Firewall)** kết hợp với CloudFront. Hệ thống yêu cầu phải chạy JavaScript để giải mã challenge.

### Bước 2: Thử nghiệm giả mạo vân tay trình duyệt (TLS Fingerprinting)
Thay vì dùng trình duyệt nặng nề, tôi thử dùng thư viện `curl_cffi` (chuyên dùng để giả lập vân tay mã hóa giống hệt Chrome 124) trong script `probe_cffi.py`.
👉 **Kết quả:** Vẫn thất bại. WAF của Binance không chỉ check vân tay mạng mà bắt buộc phải thực thi JS thực sự.

### Bước 3: Lựa chọn Playwright & Tối ưu hóa "Discover-and-Reuse"
Xác định bắt buộc phải dùng trình duyệt thực, tôi chọn **Playwright** (Chromium headless). Tuy nhiên, tôi biết việc mở Chromium mỗi phút một lần sẽ làm **sập RAM của VPS**. 

Do đó, tôi nghĩ ra mô hình **Discover-and-Reuse** (Khám phá và Tái sử dụng):
- Chỉ mở Playwright ở lần chạy **đầu tiên** để vượt WAF.
- Dùng tính năng *network interception* của Playwright để "nghe lén" browser xem nó thực sự gọi API nào.
- Trích xuất API đó, kèm theo Cookie/Headers đã được WAF cấp phép.
- Đóng browser. Các chu kỳ quét sau đó chỉ việc dùng thư viện `requests` siêu nhẹ để bắn vào endpoint đã thu thập.

---

## 3. Những Thất Bại & Khó Khăn Đã Vượt Qua

### Khó khăn 1: Điểm mù API (Endpoint phi logic)
Khi dùng Playwright để bắt gói tin, tôi kỳ vọng Binance sẽ dùng API dạng `POST /get-posts` với payload `{"handle": "gem10x"}`. 
👉 **Thực tế:** Binance dùng một API tên là `queryUserProfilePageContentsWithFilter` thông qua phương thức `GET`, và nó **không hề dùng tên handle**. Nó dùng một mã UUID nội bộ (`targetSquareUid=sHENlM7jwSsIgnTNXWo9tw`). 
👉 **Cách khắc phục:** Cấu hình lại script dò tìm của Playwright để bóc tách chính xác tham số `targetSquareUid` từ URL khi browser load trang thành công.

### Khó khăn 2: Lỗi mã hóa trên Windows Terminal (UnicodeEncodeError)
Khi in kết quả JSON bóc tách được ra Terminal để phân tích, script liên tục crash vì ký tự tiếng Việt hoặc Emoji không tương thích với bảng mã `cp1252` của Windows.
👉 **Cách khắc phục:** Chuyển hướng lưu toàn bộ JSON bắt được vào một file vật lý (`probe_results.json`) để đọc sau, tránh phụ thuộc vào Terminal.

### Khó khăn 3: Vòng lặp tử thần (Deadlock) trong Asyncio
Đây là lỗi kỹ thuật sâu nhất gặp phải:
- Playwright yêu cầu chạy bất đồng bộ (`async`). Nhưng `MonitorBase` và `scheduler` lại là code đồng bộ (`sync`).
- Tôi viết hàm `_run_async` đẩy Playwright sang một background thread, rồi block thread chính chờ kết quả.
- 👉 **Thất bại:** Khi chạy end-to-end, script treo cứng ngắc và bị văng `TimeoutError` sau đúng 120 giây.
- 👉 **Nguyên nhân cốt lõi:** Hàm `_discover_api` (đang chạy trong background thread) lại gọi tiếp hàm `_get_browser()`, mà hàm này lại gọi `_run_async` một lần nữa. Hậu quả là background thread tự block chính nó để chờ một kết quả mà nó chưa bao giờ có cơ hội xử lý (Deadlock).
- 👉 **Cách khắc phục:** Cấu trúc lại `_get_browser()` thành thuần `async` sử dụng `asyncio.Lock()`, loại bỏ hoàn toàn việc gọi lồng chéo (nested blocking). Hệ thống sau đó chạy vèo vèo hoàn thành trong 45 giây.

### Khó khăn 4: AI "Mù" (Lỗi quên khởi tạo cấu hình)
Lúc test tích hợp file ảnh với thuật toán tách biểu đồ (Gemini pipeline), AI trả về `False` cho toàn bộ 20 bức ảnh.
- 👉 **Nguyên nhân:** Script test độc lập của tôi đã quên gọi hàm `init_key_pool(gemini_api_keys)` khiến module AI không có khóa để gọi Google API. Nó xử lý lỗi im lặng (fail-safe) trả về False.
- 👉 **Cách khắc phục:** Bổ sung khởi tạo. Kết quả phân tích sau đó đạt mức hoàn hảo: Trích xuất thành công 13 chart, tự động vứt bỏ 7 ảnh rác (meme/pnl).

---

## 4. Bài Học Tổng Kết

Qua tác vụ này, tôi nhận thấy:
1. **Kiên nhẫn dò đường (Probing):** Không bao giờ giả định về API của các sàn lớn. Hãy luôn viết script thăm dò từng lớp bảo vệ (Requests -> CFFI -> Playwright) trước khi code hệ thống chính.
2. **Kiến trúc quyết định khả năng mở rộng:** Việc bỏ ra chút thời gian refactor `MonitorBase` ở Phase 1 là cực kỳ xứng đáng. Nó giúp việc thêm Binance sau này không đụng chạm rủi ro tới code đang chạy live.
3. **Xử lý Thread/Async trong Python:** Rất dễ dính Deadlock khi kết hợp thư viện đồng bộ (như APScheduler/Requests) với bất đồng bộ (Playwright). Phải tách bạch thật rõ ranh giới giữa 2 luồng này.
