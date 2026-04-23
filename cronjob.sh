#!/bin/bash

# Define the project directory
PROJECT_DIR="/home/ubuntu/x-twitter-monitor"
cd "$PROJECT_DIR" || exit 1

# Explicitly use the venv python
PYTHON_BIN="$PROJECT_DIR/venv/bin/python3"

# Thực thi bot với cờ --once
echo "[Thu Apr 23 09:12:12 JST 2026] Bắt đầu chạy X-Twitter Monitor..."
"$PYTHON_BIN" main.py run --once
echo "[Thu Apr 23 09:12:12 JST 2026] Hoàn tất."
