"""
convert_cookies.py — Chuyển đổi cookie từ Extension sang format bot cần.

Cách dùng:
    python src/test/convert_cookies.py <username> [input_file]

Ví dụ:
    python src/test/convert_cookies.py myaccount
    python src/test/convert_cookies.py myaccount exported_cookies.json

Nếu không truyền input_file, script sẽ yêu cầu bạn paste JSON vào terminal.

Output: cookies/<username>.json
"""
import json
import os
import sys


def convert(raw: list | dict) -> dict:
    """
    Chuyển từ List format (Cookie-Editor extension) hoặc Dict phẳng.
    """
    if isinstance(raw, dict):
        # Đã là format phẳng rồi, dùng luôn
        return raw

    if isinstance(raw, list):
        result = {}
        for item in raw:
            if isinstance(item, dict) and 'name' in item and 'value' in item:
                result[item['name']] = item['value']
        return result

    raise ValueError('Không nhận ra định dạng JSON. Phải là List hoặc Dict.')


def check_required(cookies: dict) -> None:
    missing = [f for f in ('auth_token', 'ct0') if not cookies.get(f)]
    if missing:
        print('[!] CẢNH BÁO: Thiếu các field quan trọng: {}'.format(', '.join(missing)))
        print('    Bot vẫn sẽ tạo file nhưng có thể không xác thực được.')
    else:
        print('[✓] Đủ auth_token và ct0.')


def main():
    if len(sys.argv) < 2:
        print('Cách dùng: python src/test/convert_cookies.py <username> [input_file]')
        sys.exit(1)

    username   = sys.argv[1]
    input_file = sys.argv[2] if len(sys.argv) >= 3 else None

    # --- Đọc input ---
    if input_file:
        with open(input_file, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        print('[✓] Đọc từ file: {}'.format(input_file))
    else:
        print('Paste nội dung JSON cookie vào đây, rồi nhấn Enter 2 lần:')
        lines = []
        while True:
            line = input()
            if line == '':
                if lines:
                    break
            else:
                lines.append(line)
        raw = json.loads('\n'.join(lines))

    # --- Convert ---
    cookies = convert(raw)
    print('[✓] Chuyển đổi xong: {} cookie fields.'.format(len(cookies)))

    # --- Kiểm tra field bắt buộc ---
    check_required(cookies)

    # --- Lưu file ---
    output_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'cookies')
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, '{}.json'.format(username))

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(cookies, f, indent=2, ensure_ascii=False)

    print('[✓] Đã lưu: {}'.format(os.path.abspath(output_path)))
    print()
    print('Bước tiếp theo:')
    print('  1. Thêm username "{}" vào twitter_accounts trong config/config.json'.format(username))
    print('  2. Chạy: python main.py check-tokens')


if __name__ == '__main__':
    main()
