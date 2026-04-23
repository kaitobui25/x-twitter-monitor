# Twitter Monitor — Hướng dẫn cấu hình

Toàn bộ cài đặt nằm trong **một file duy nhất**: `config/config.json`

---

## Cấu trúc `config.json`

```json
{
  "twitter_accounts": [...],   // Tài khoản X.com dùng để xác thực
  "telegram": {...},           // Bot Telegram & chat ID của bạn
  "schedule": {...},           // Khoảng thời gian giữa 2 lần quét
  "targets": [...],            // Danh sách đối tượng cần theo dõi
  "advanced": {...}            // Cài đặt nâng cao (ít khi cần thay đổi)
}
```

---

## 1. Thay tài khoản X.com (auth account)

Tài khoản này dùng để **xác thực với X API** (không nhất thiết phải là tài khoản theo dõi).

```json
"twitter_accounts": [
    { "username": "ten_tai_khoan_cua_ban" }
]
```

Sau đó chạy lệnh login để tạo cookie:
```bash
python main.py login --username ten_tai_khoan_cua_ban --password mat_khau_cua_ban
```

Có thể thêm **nhiều tài khoản** để tránh rate limit:
```json
"twitter_accounts": [
    { "username": "account1" },
    { "username": "account2" }
]
```

---

## 2. Đổi Telegram Bot

```json
"telegram": {
    "bot_token": "123456789:AAFxxx...",
    "maintainer_chat_id": 7480163903
}
```

- `bot_token`: Token lấy từ [@BotFather](https://t.me/BotFather)
- `maintainer_chat_id`: Chat ID của bạn — nhận cảnh báo khi hệ thống gặp sự cố

---

## 3. Thay đổi khoảng thời gian quét

```json
"schedule": {
    "scan_interval_seconds": 900
}
```

| Giá trị | Ý nghĩa     |
|---------|-------------|
| 300     | 5 phút      |
| 600     | 10 phút     |
| 900     | 15 phút ✅  |
| 1800    | 30 phút     |
| 3600    | 1 giờ       |

---

## 4. Thêm/bớt đối tượng theo dõi

Thêm object vào mảng `targets`:

```json
"targets": [
    {
        "username": "BangXBT",
        "title": "BangXBT",
        "notify_telegram_chat_ids": [7480163903],
        "monitor_tweets":   true,
        "monitor_profile":  false,
        "monitor_following": false,
        "monitor_likes":    false
    },
    {
        "username": "elonmusk",
        "title": "Elon Musk",
        "notify_telegram_chat_ids": [7480163903, 987654321],
        "monitor_tweets":   false,
        "monitor_profile":  false,
        "monitor_following": false,
        "monitor_likes":    false
    }
]
```

Mỗi target có thể gửi thông báo đến **nhiều chat ID Telegram khác nhau**.

---

## 5. Cài đặt nâng cao (`advanced`)

| Key                  | Mặc định | Ý nghĩa                                          |
|----------------------|----------|--------------------------------------------------|
| `send_daily_summary` | false    | Gửi tóm tắt hàng ngày lúc 6h sáng               |
| `listen_exit_command`| false    | Cho phép tắt bot bằng lệnh `EXIT` qua Telegram  |
| `confirm_on_start`   | false    | Yêu cầu xác nhận Telegram trước khi chạy        |
| `cookies_dir`        | cookies  | Thư mục chứa cookie files                        |
| `log_dir`            | log      | Thư mục chứa log files                           |

---

## 6. Cấu hình phân tích biểu đồ bằng AI (Gemini)

Hệ thống có tính năng tự động tải ảnh từ tweet và đẩy qua **Gemini AI** để trích xuất tín hiệu giao dịch (thành file JSON).

Thêm mảng cấu hình `gemini_api_keys` vào ngay đầu file `config.json` (chỉ định cấu trúc tên theo `key1`, `key2`,...):

```json
"gemini_api_keys": {
    "key1": "AIzaSyA-xxxxxxxxxxxxxxxxxxxx",
    "key2": "API_KEY_THU_HAI_NEU_CO"
}
```

**📌 Cơ chế hoạt động của Bot AI:**
- **Round-robin**: Nếu bạn cấu hình nhiều key, bot sẽ tự động xoay vòng lần lượt qua từng key mỗi khi phân tích ảnh để chia sẻ tải.
- **Global Delay (Chống Rate Limit Tuyệt Đối)**: Bất kể ảnh thuộc tweet nào hay của đối tượng nào, cứ khi hệ thống cần phân tích từ tấm ảnh thứ 2 trở lên trong 1 phiên chạy, bot sẽ **TỰ ĐỘNG CHỜ NGỦ 2 PHÚT (120 giây)** trước khi gửi. Đảm bảo an toàn tuyệt đối trước giới hạn 429 Too Many Requests của Gemini.
- **Lưu trữ thư mục theo ngày (Tự động)**:
  - Ảnh tải về: `follower/<Tên_Đối_Tượng>/img/YYYY-MM-DD/YYYY-MM-DD-001.jpg`
  - Dữ liệu JSON: `follower/<Tên_Đối_Tượng>/json/YYYY-MM-DD/YYYY-MM-DD-001.json`

---

## Chạy hệ thống

```bash
# Chạy monitor (dùng config.json mặc định)
python main.py run

# Chạy với config file khác
python main.py run --config /path/to/config.json

# Kiểm tra token có hoạt động không
python main.py check-tokens

# Đăng nhập tạo cookie
python main.py login --username ten_tai_khoan --password mat_khau
```
