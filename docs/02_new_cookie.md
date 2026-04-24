

Vì bạn đã chủ động cập nhật file cookie lên VPS, bạn chỉ cần thực hiện các bước sau để bot nhận diện cấu hình mới. Tôi sẽ chỉ đưa hướng dẫn lệnh, bạn tự chạy trên VPS nhé:

**Bước 1: Kiểm tra xem cookie mới đã hợp lệ chưa**
Mở terminal trên VPS và chạy lệnh kiểm tra token:
```bash
cd ~/x-twitter-monitor
./venv/bin/python3 main.py check-tokens
```
*(Nếu terminal báo "Valid/Success" thì tức là file cookie bạn vừa tạo hoạt động tốt).*

**Bước 2: Tắt tiến trình cũ đang bị kẹt cookie cũ**
Bot đọc file cookie vào bộ nhớ ngay lúc mới bật, do đó bạn phải ép tắt tiến trình cũ thì nó mới chịu tải lại file mới. Theo kiểm tra của tôi, bạn đang có 1 tiến trình chạy ngầm lệnh `main.py run` (PID: `259927`).
```bash
# Tìm lại chính xác ID của tiến trình (PID)
ps aux | grep "main.py run"

# Kill tiến trình đó (Thay số 259927 bằng PID thực tế nếu nó đã thay đổi)
kill -9 259927
```

**Bước 3: Khởi động lại Bot**
Tùy vào cách bạn đang thiết lập trên VPS:
*   **Nếu bạn vẫn đang chạy ngầm liên tục:** Hãy bật lại bằng lệnh bạn thường dùng (ví dụ dùng `tmux`, `screen` hoặc `nohup ./venv/bin/python3 main.py run &`).
*   **Nếu bạn đã chuyển sang dùng Cron job (chạy qua `cronjob.sh --once`):** Bạn **không cần** bật lại lệnh chạy ngầm nữa. Cứ để mặc đó, tới lịch hẹn Cron sẽ tự động kích hoạt tiến trình mới và đọc cookie mới.



Trên VPS có nhiều project (ví dụ `My-Home-Hunter` hoặc các tool khác) cũng có thể dùng chung cấu trúc file `main.py`, nếu kill nhầm sẽ gây lỗi cho hệ thống khác. 

Dưới đây là hướng dẫn chuẩn xác từng bước để bạn tự thao tác:

**Bước 1: Xác định chính xác PID của `x-twitter-monitor`**
Bạn hãy copy và chạy dòng lệnh sau trên terminal của VPS (lệnh này sẽ quét toàn bộ các tiến trình đang chạy `main.py` và in ra thư mục gốc của nó):

```bash
for pid in $(pgrep -f "main.py run"); do echo "PID $pid đang chạy ở thư mục: $(sudo readlink /proc/$pid/cwd)"; done
```

Kết quả trả về sẽ giúp bạn xác nhận chính xác. Ví dụ:
`PID 259927 đang chạy ở thư mục: /home/ubuntu/x-twitter-monitor`

**Bước 2: Tắt tiến trình cũ**
Khi đã đối chiếu được đúng số PID thuộc về thư mục `x-twitter-monitor`, bạn tiến hành kill nó (giả sử PID đúng là `259927`):

```bash
kill -9 259927
```

**Bước 3: Khởi động lại Bot**
Dựa vào việc bạn đang chạy lệnh `main.py run` (không có cờ `--once`), điều này chứng tỏ bạn đang cho bot chạy ngầm liên tục (scan 15 phút/lần) chứ không phải chạy qua Cron. 

Bạn hãy cd vào thư mục project và chạy lại bot ngầm (dùng `nohup`, `screen` hoặc `tmux` - tùy thuộc thói quen trước đây của bạn). 

Ví dụ nếu dùng `nohup`:
```bash
cd ~/x-twitter-monitor
nohup ./venv/bin/python3 main.py run > bot_output.log 2>&1 &
```
*(Nếu bạn trước đây dùng tmux hay screen, hãy mở session đó lên và gõ lại lệnh chạy).*