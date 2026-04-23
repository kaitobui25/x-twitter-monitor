

File `gemini_extractor.py` (chứa hàm `extract_chart`) **KHÔNG** tự động chạy độc lập, mà nó là một "công cụ" được gọi bởi thành phần theo dõi Tweet (`TweetMonitor`).

Dưới đây là sơ đồ luồng chạy chính xác giải thích **khi nào code này được chạy**:

### Luồng thực thi chi tiết (Từng bước một):

**Bước 1: Kích hoạt quét (Trigger)**
- Tùy thuộc vào cấu hình của bạn, hệ thống được đánh thức bởi **Cron job** (chạy lệnh `--once` mỗi tiếng) HOẶC bởi **tiến trình ngầm** (cứ 15 phút quét 1 lần).
- Hàm `TweetMonitor.watch()` sẽ được chạy.

**Bước 2: Tìm kiếm Tweet mới**
- Hệ thống gọi API nội bộ của X.com để lấy danh sách tweet của BangXBT.
- Nó so sánh ID của các tweet này với `last_tweet_id` được lưu trong file `state.json`. Nếu ID lớn hơn, nó xác định đó là **Tweet mới**.

**Bước 3: Lọc dữ liệu Tweet (Gồm cả việc tìm ảnh)**
- Nếu có tweet mới, nó lặp qua từng tweet (bắt đầu từ tweet cũ nhất trong số các tweet mới để không lộn thứ tự).
- Tại dòng **203/205** của `tweet.py`, nó dùng hàm `parse_media_from_tweet()` để bóc tách xem trong dòng tweet đó **có đính kèm hình ảnh nào không**. Ảnh được lưu vào danh sách biến `photos`.

**Bước 4: Xử lý và gửi thông báo Telegram**
- Hệ thống gửi tin nhắn thông báo (kèm text và link ảnh) về Telegram của bạn.

**Bước 5: Gọi hàm xử lý hình ảnh**
- Ngay sau khi gửi Telegram xong, tại dòng **220** của `tweet.py`, nó gọi hàm `self._process_images(photos)`.
- **Lưu ý quan trọng:** Nếu bài đăng chỉ có chữ (không có hình ảnh), biến `photos` sẽ rỗng, hàm này kết thúc ngay lập tức và Gemini AI sẽ **không** được gọi.

**Bước 6: Tải ảnh và kích hoạt `gemini_extractor.py`**
Bên trong hàm `_process_images()` (từ dòng 103), nếu có hình ảnh, nó làm các bước sau:
1. Tải ảnh từ Twitter về máy, lưu vào thư mục `follower/BangXBT/img/`.
2. Kiểm tra xem bạn có cài đặt `gemini_api_keys` trong `config.json` hay không.
3. Nếu đây không phải là bức ảnh đầu tiên được gọi trong lần chạy này, nó sẽ tự động chèn khoảng nghỉ (delay) 2 phút.
4. **CHÍNH LÚC NÀY (Dòng 165 trong `tweet.py`)**, lệnh `extract_chart(img_path, json_path)` được kích hoạt. Lệnh này sẽ chạy toàn bộ code bên trong file `gemini_extractor.py` của bạn để đẩy ảnh lên Google, lấy kết quả JSON và lưu vào máy.

### Tóm lại
Code `gemini_extractor.py` CHỈ được chạy khi và chỉ khi thỏa mãn **ĐỒNG THỜI 3 ĐIỀU KIỆN**:
1. Có một Tweet hoàn toàn mới từ đối tượng theo dõi (VD: BangXBT).
2. Tweet đó **BẮT BUỘC phải chứa hình ảnh**.
3. Ảnh đã được tải về VPS thành công và `config.json` có chứa Gemini API Key hợp lệ.