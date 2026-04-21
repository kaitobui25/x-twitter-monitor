#!/bin/bash

# =========================================================================
# HƯỚNG DẪN THIẾT LẬP CRONJOB TRÊN LINUX (UBUNTU/CENTOS...)
# =========================================================================
# File này giúp chạy bot ổn định trong môi trường cron (thường bị thiếu PATH).
#
# BƯỚC 1: Cấp quyền thực thi cho file này (chỉ cần làm 1 lần)
#   chmod +x cronjob.sh
#
# BƯỚC 2: Mở trình cài đặt cron
#   crontab -e
#
# BƯỚC 3: Dán 1 trong các dòng sau vào cuối file crontab (Nhớ sửa lại đường dẫn)
#
# Chạy mỗi 1 giờ (vào phút số 0):
#   0 * * * * /đường/dẫn/đến/x-twitter-monitor/cronjob.sh >/dev/null 2>&1
#
# Chạy mỗi 30 phút (phút 0 và phút 30):
#   0,30 * * * * /đường/dẫn/đến/x-twitter-monitor/cronjob.sh >/dev/null 2>&1
#
# Chạy mỗi 15 phút:
#   */15 * * * * /đường/dẫn/đến/x-twitter-monitor/cronjob.sh >/dev/null 2>&1
#
# Ví dụ thực tế (nếu bạn để code ở /root/x-twitter-monitor):
#   0 * * * * /root/x-twitter-monitor/cronjob.sh >/dev/null 2>&1
# =========================================================================

# 1. Tự động lấy đường dẫn của thư mục chứa script này
PROJECT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$PROJECT_DIR" || exit 1

# 2. Tìm python3
PYTHON_BIN=$(command -v python3)
if [ -z "$PYTHON_BIN" ]; then
    echo "[Lỗi] Không tìm thấy python3 trên hệ thống!"
    exit 1
fi

# 3. Thực thi bot với cờ --once
echo "[$(date)] Bắt đầu chạy X-Twitter Monitor..."
"$PYTHON_BIN" main.py run --once
echo "[$(date)] Hoàn tất."
