# Hướng Dẫn Xử Lý Lỗi Crontab & Quyền Thực Thi Git (Windows sang Linux)

Tài liệu này tổng hợp nguyên nhân và các giải pháp triệt để cho vấn đề Cronjob không hoạt động trên VPS sau khi cập nhật code từ máy tính cá nhân chạy Windows.

---

## 1. Mô Tả Vấn Đề
- Cronjob đã được cài đặt đúng cú pháp nhưng script không được kích hoạt.
- Lệnh chạy thử trực tiếp trên VPS báo lỗi: `bash: ./cronjob.sh: Permission denied`.
- Dù trước đó hệ thống vẫn chạy bình thường, lỗi chỉ xuất hiện sau một lần `git commit` và `git pull`.

## 2. Nguyên Nhân Gốc Rễ
Lỗi này bắt nguồn từ **sự khác biệt về hệ thống tệp tin** giữa môi trường phát triển (Windows - NTFS) và môi trường triển khai (Linux - POSIX).

1. **Sự can thiệp của Git trên Windows:** Hệ điều hành Windows không có khái niệm cờ quyền "Thực thi" (`+x` hay `chmod 755`) giống như Linux. Khi bạn chỉnh sửa một file `.sh` và commit thông qua Git trên Windows, Git có thể tự động hạ quyền của file đó xuống dạng `100644` (chỉ có quyền Đọc/Ghi).
2. **Quá trình đồng bộ lên VPS:** Khi VPS (chạy Linux) thực hiện lệnh `git pull`, nó kéo file `.sh` đã bị mất quyền thực thi về máy.
3. **Crontab bị từ chối:** Khi đến lịch hẹn, Cron cố gắng gọi file `.sh` nhưng hệ điều hành chặn lại vì file không có quyền thực thi, sinh ra lỗi `Permission denied`.
4. **Lỗi bị che giấu:** Do đuôi lệnh trong crontab có chứa `> /dev/null 2>&1` (ép tất cả kết quả và lỗi ném vào khoảng không), lỗi Permission bị giấu đi, khiến người quản trị không biết tại sao bot không chạy.

---

## 3. Các Giải Pháp Khắc Phục Triệt Để

Bạn có thể áp dụng 1 trong các cách sau (hoặc kết hợp) để tránh lặp lại lỗi này.

### Giải pháp 1: Ép Git ghi nhớ quyền thực thi (Khuyên dùng)
Trị tận gốc vấn đề trên máy tính Windows để Git luôn ép VPS cấp quyền `+x` khi kéo code về.

Tại máy tính Windows, mở Terminal ở thư mục dự án và chạy lệnh sau để thay đổi index của Git:
```bash
git update-index --chmod=+x cronjob.sh
```
Sau đó, bạn thực hiện `git commit` và `git push` như bình thường. Các lần chỉnh sửa sau trên Windows sẽ không làm mất quyền này nữa.

### Giải pháp 2: Gọi thông qua trình thông dịch `bash` (Lách luật)
Thay vì để hệ điều hành tự quyết định cách chạy file (đòi hỏi quyền thực thi), bạn chỉ định đích danh chương trình `bash` đứng ra đọc file. Cách này đảm bảo script vẫn chạy dù nó không có quyền `+x`.

Mở cấu hình cron trên VPS bằng lệnh `crontab -e` và thêm chữ `bash` vào trước đường dẫn:
```bash
# Thay vì:
0 * * * * /home/ubuntu/x-twitter-monitor/cronjob.sh >/dev/null 2>&1

# Hãy đổi thành:
0 * * * * bash /home/ubuntu/x-twitter-monitor/cronjob.sh >/dev/null 2>&1
```

### Giải pháp 3: Lưu lại Log lỗi của Cronjob để dễ chẩn đoán
Đừng dùng `> /dev/null 2>&1` nếu script của bạn có khả năng lỗi ở cấp độ hệ thống. Hãy ghi log ra một file riêng biệt.

Mở `crontab -e` và sửa cấu hình thành:
```bash
0 * * * * bash /home/ubuntu/x-twitter-monitor/cronjob.sh >> /home/ubuntu/x-twitter-monitor/log/cron_os.log 2>&1
```
*Lợi ích:* Bất cứ khi nào Cron gặp sự cố (sai đường dẫn, thiếu module Python, lỗi quyền truy cập...), nó sẽ được ghi lại chi tiết bằng tiếng Anh trong file `cron_os.log`. Bạn chỉ cần mở file này ra là bắt được bệnh ngay.


### khôi phục nhanh quyền x cho cronjob
Bạn chỉ cần chạy **1 lệnh duy nhất** trên VPS là xong. Lệnh này sẽ tìm tất cả file trong thư mục của bạn có đuôi `.sh` và cấp cho nó quyền thực thi (`+x`)

```bash
chmod +x /home/ubuntu/x-twitter-monitor/cronjob.sh
```


### Cách 1: Chạy lệnh kiểm tra từng bước (Giống như bạn đang ngồi trước máy)
Bạn copy và paste lần lượt các lệnh dưới đây vào cửa sổ SSH để kiểm tra từ gốc đến ngọn:

1.  **Kiểm tra quyền thực thi file:**
    Xem hệ thống có cho phép chạy file này không.
    ```bash
    ls -l /home/ubuntu/x-twitter-monitor/cronjob.sh
    ```
    *Nếu kết quả hiển thị ký tự `x` (ví dụ: `-rwxr--r--`), nghĩa là quyền đã có. Nếu không có `x`, bạn sẽ thấy lỗi như ban nãy.*

2.  **Chạy thử thủ công bằng Bash (Lách lỗi):**
    Để chắc chắn lỗi không phải do file bị mất quyền, hãy thử gọi nó bằng trình thông dịch `bash`.
    ```bash
    bash /home/ubuntu/x-twitter-monitor/cronjob.sh
    ```
    *Nếu lệnh này chạy thành công và hiển thị đúng dòng chữ “Cronjob is running”, tức là code của bạn hoàn hảo. Vấn đề chỉ nằm ở cách Cron gọi file.*

3.  **Kiểm tra lỗi ném ra màn hình (Debug):**
    Bây giờ hãy sửa lại dòng lệnh trong Cron (`crontab -e`) để nó không giấu lỗi đi nữa. Hãy dùng lệnh sau thay cho lệnh cũ của bạn:
    ```bash
    0 * * * * /home/ubuntu/x-twitter-monitor/cronjob.sh >> /home/ubuntu/x-twitter-monitor/cron_log.txt 2>&1
    ```
    *Sau khi lưu xong, bạn chỉ cần chờ đúng 1 phút (ví dụ 15:26), sau đó kiểm tra file log bằng lệnh: `cat /home/ubuntu/x-twitter-monitor/cron_log.txt`.*
    *Trong file log đó sẽ ghi lại chính xác lỗi tiếng Anh là gì (ví dụ: missing module Python, hay lỗi truy cập database).* 