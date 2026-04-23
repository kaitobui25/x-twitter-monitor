# Twitter (X.com) Monitor 🦅

A lightweight, robust, and headless Twitter (X.com) monitoring bot built with Python. This tool continuously tracks specific X accounts and sends real-time notifications to Telegram, Discord, or CQHttp whenever the target user posts a new tweet, updates their profile, follows someone new, or likes a post.

No browser emulation (like Selenium) is required. It queries the internal X GraphQL API directly, making it extremely fast and memory efficient (capable of running on 512MB RAM Linux VPS).

> **Python 3.12+ compatible.** Telegram notifications are sent via direct HTTP calls to the Bot API (using `httpx`) — no `python-telegram-bot` SDK required, eliminating the historical `APScheduler` version conflict.

## 🌟 Key Features

*   **Multi-Target Monitoring**: Theo dõi không giới hạn số lượng tài khoản cùng lúc.
*   **🧠 AI Chart Extraction (MỚI)**: Tự động tải ảnh biểu đồ giao dịch từ Tweet và sử dụng **Gemini AI** để nhận diện, bóc tách cấu trúc Setup (Entry, Stoploss, Take Profit). Kết quả trả về file JSON chuẩn.
*   **📂 Quản lý dữ liệu thông minh theo ngày**: Ảnh và dữ liệu phân tích JSON được lưu tự động vào từng thư mục theo đối tượng và tách riêng theo ngày, đánh số thứ tự tuần tự không ghi đè (VD: `follower/BangXBT/img/2026-04-24/2026-04-24-001.jpg`).
*   **⏱️ Anti-Rate Limit & Round-Robin API**: 
    - Cho phép nạp Pool chứa nhiều Gemini API Keys (`key1`, `key2`...). 
    - Bot tự động xoay vòng key và bắt buộc áp dụng khoảng **chờ 2 phút (Global Delay)** giữa mỗi lần gửi ảnh lên AI (bất kể ảnh ở tweet nào). Chống triệt để việc bị khoá tài khoản do spam API.
*   **Comprehensive Tracking**:
    *   **Tweets**: Phát hiện tweet mới, retweet, quote (kèm chức năng trích xuất hình ảnh/video).
    *   **Profile**: Báo cáo sự thay đổi Tên, Tiểu sử, Avatar, Banner...
    *   **Following**: Notifies when the target follows or unfollows other users.
    *   **Likes**: Detects new likes from the target user.
*   **Headless & Lightweight**: Uses raw HTTP requests to simulate X.com GraphQL API calls. No heavy browsers needed.
*   **State Persistence**: Saves tracking state (`state/state.json`) so you can run it via Linux `cron` (e.g., once an hour) without losing tracking history.
*   **Anti-Ban & Token Rotation**: Supports multiple authentication accounts and round-robin token rotation to bypass rate limits.
*   **Sign-out Detection**: Automatically detects if your auth account token expires or gets signed out and sends an emergency alert to your Telegram.
*   **Centralized Configuration**: Everything is managed cleanly in a single `config/config.json` file.
*   **Rotating Logs**: Logs are safely rotated (max 10MB, 5 backups) preventing disk space issues.

---

## 🛠️ Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/kaitobui25/x-twitter-monitor.git
    cd x-twitter-monitor
    ```

2.  **Install dependencies:**
    (Requires Python 3.12+)
    ```bash
    pip install -r requirements.txt
    ```

    Key dependencies: `httpx`, `APScheduler>=3.10`, `XClientTransaction`, `requests`, `beautifulsoup4`.

3.  **Generate X.com Authentication Cookie:**
    You need a dummy/secondary X.com account to query the API.
    ```bash
    python main.py login --username YOUR_X_USERNAME --password YOUR_X_PASSWORD
    ```
    *Note: If your account has 2FA, the CLI will prompt you to re-run the command with the `--confirmation_code` flag.*

4.  **Configure the Bot:**
    Copy the configuration file or modify the default one located at `config/config.json`. 
    See the [CONFIG_GUIDE.md](CONFIG_GUIDE.md) (Vietnamese) for detailed setup instructions regarding Telegram Bots, Targets, and Intervals.

---

## 🚀 Usage

The project features a clean CLI interface. 

### 1. Run Continuously (Daemon Mode)
This runs the bot in the foreground. It will execute scans based on the `scan_interval_seconds` defined in your config.
```bash
python main.py run
```

### 2. Run Once (Cronjob Mode)
Chế độ này tối ưu nhất để chạy bot định kỳ qua `cron` trên Linux nhằm tiết kiệm tài nguyên CPU/RAM. Bot sẽ quét tất cả các mục tiêu chính xác 1 lần, lưu trạng thái và tự động thoát.

Nên sử dụng file `cronjob.sh` (đã được cấu hình để tự động nhận diện Virtual Environment):
1. **Cấp quyền thực thi:**
   ```bash
   chmod +x cronjob.sh
   ```
2. **Cấu hình Crontab:**
   ```bash
   crontab -e
   ```
3. **Thêm dòng sau vào cuối file crontab (ví dụ chạy mỗi 15 phút):**
   ```bash
   */15 * * * * /home/ubuntu/x-twitter-monitor/cronjob.sh >/dev/null 2>&1
   ```

### 3. Check Token Health
Verify if your X.com authentication cookies are still valid and active:
```bash
python main.py check-tokens
```

---

## 📂 Directory Structure

```text
twitter-monitor/
├── config/
│   └── config.json          # Main configuration file
├── cookies/
│   └── <username>.json      # Saved X.com auth sessions
├── follower/                # Thư mục chứa dữ liệu tự động tải về từ Tweet
│   └── <username>/          # Dữ liệu phân loại theo từng tài khoản theo dõi
│       ├── img/             # Ảnh gốc (phân tách theo thư mục ngày YYYY-MM-DD)
│       └── json/            # Dữ liệu JSON Gemini phân tích (phân tách theo thư mục ngày YYYY-MM-DD)
├── log/                     
│   ├── main.log             # System-wide warnings/errors
│   └── monitors/            # Individual tracking logs per target
├── src/
│   ├── core/                # GraphQL API, Watcher, Login flow
│   ├── monitors/            # Tweet, Profile, Like, Following monitors
│   ├── notifiers/           # Telegram, Discord, CQHttp integrations
│   └── utils/               # Parsers, State manager, Logger, Gemini Extractor
├── state/
│   └── state.json           # Persisted memory for run-once mode
├── main.py                  # CLI Entry point
└── CONFIG_GUIDE.md          # Detailed configuration documentation
```

---


