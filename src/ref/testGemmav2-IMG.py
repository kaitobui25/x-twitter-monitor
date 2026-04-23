from google import genai
from PIL import Image
import io

# Khởi tạo client
client = genai.Client(api_key="AIzaSyA-4f92eyt0C7xRQv9fp1sjR-VG9GqTHU4")

# Load ảnh từ ổ C
image = Image.open(r"D:\Phong\03_Finance\X\twitter-monitor\follower\BangXBT\2026-04-23-004.JFIF").convert("RGB")


# convert image -> bytes
img_byte_arr = io.BytesIO()
image.save(img_byte_arr, format='JPEG')
img_bytes = img_byte_arr.getvalue()


# Prompt test đọc biểu đồ nến
prompt = """
You are a professional trading chart data extractor.

The image may contain TWO DIFFERENT types of trade setups.
You MUST detect the type for EACH setup individually.

=====================================
=== SETUP TYPE DETECTION ============
=====================================

There are 2 possible setup types:

TYPE 1 (EXECUTED TRADE SETUP):
- Red zone = Stop Loss
- Blue zone = Take Profit
- Boundary between them = Entry
- Clearly structured risk/reward box

TYPE 2 (PREDICTION SETUP):
A setup can appear in MULTIPLE forms:

FORM A:
- A rectangular zone (entry area)
- Arrow pointing toward it

FORM B:
- A curved arrow (usually yellow) indicating a pullback/retest area
- NO rectangle is present
- The end of the curved arrow = entry zone

FORM C:
- A zigzag / lightning arrow projecting future price direction
- Used to determine direction (long/short), NOT entry

FORM D:
- A support/resistance line (horizontal or diagonal)
- Combined with curved arrow → defines entry zone

Interpretation rules:
- Entry zone can be:
  - rectangle area (if exists)
  - OR area around the END of curved arrow
  - OR area where curved arrow meets a support/resistance line

- Direction:
  - Upward projection → "long"
  - Downward projection → "short"

Each detected setup must be classified as:
"type": "type1" or "type2"

=====================================
=== EXTRACTION RULES =================
=====================================

FOR TYPE 1:
- entry_price = boundary between red & blue
- sl = end of red zone
- tp = end of blue zone

FOR TYPE 2:
- Identify ALL visual clues:
  - curved arrow (entry zone)
  - zigzag/lightning arrow (direction)
  - support/resistance lines

- entry_zone:
  - If rectangle exists → use it
  - Else:
    - Use the END of curved arrow
    - Expand to a small price range around that point

- entry_price:
  - midpoint of entry_zone

- direction:
  - Based on zigzag/lightning arrow if present
  - Otherwise based on overall arrow direction

=====================================
=== TIME EXTRACTION ==================
=====================================

- Use the bottom time axis
- entry_time = when price first touches entry (type1)
- entry_time = when arrow starts (type2)
- Format: YYYY-MM-DD HH:MM
- If unclear → "uncertain"

=====================================
=== STATUS CLASSIFICATION ============
=====================================

Determine based ONLY on actual price movement (ignore forecast arrows):

"type1":
- done_tp → TP reached
- done_sl → SL reached
- running → entry triggered but TP/SL not hit
- pending → entry not reached

"type2":
- pending → price has NOT reached entry zone
- triggered → price touched entry zone
- invalidated → price moved strongly opposite to arrow direction

=====================================
=== PRICE RULES ======================
=====================================

- Read prices ONLY from right axis
- No guessing → use "uncertain" if needed

=====================================
=== TRADING PAIR EXTRACTION =========
=====================================

- Identify the trading pair from the chart title (top area)
- Examples: BTCUSDT, BTC/USDT, ETHUSDT
- Normalize format to: BASE-QUOTE (e.g., BTC-USDT, ETH-USDT)

- If unclear → return "uncertain"

=====================================
=== STEP-BY-STEP VALIDATION =========
=====================================

For each setup, you MUST follow these steps in order:

1. Identify entry level
2. Check if price has touched entry
   - If NO → status = pending (STOP here)

3. If YES:
   - Check if price reached TP
   - Check if price reached SL

4. Decide status:
   - TP hit → done_tp
   - SL hit → done_sl
   - Neither → running

CRITICAL:
- A wick touching SL/TP counts as hit
- Compare carefully using the price scale
- Do NOT assume SL is hit unless clearly exceeded

=====================================
=== OUTPUT FORMAT ====================
=====================================

Return ONLY JSON:

{
  "pair": "BTC-USDT",
  "total_setups": X,
  "setups": [
    {
      "type": "type1 | type2",
      "direction": "long | short | null",
      "entry_price": ...,
      "entry_zone": {
        "low": ...,
        "high": ...
      },
      "entry_time": "...",
      "sl": ...,
      "tp": ...,
      "status": "pending | running | done_tp | done_sl | triggered | invalidated"
    }
  ]
}
"""

# Gửi request (text + image)
# gemma-4-31b-it  or  gemini-3.1-flash-lite-preview
response = client.models.generate_content(
    model="gemini-3.1-flash-lite-preview",
    contents=[
        {
            "role": "user",
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": "image/jpeg",
                        "data": img_bytes
                    }
                }
            ]
        }
    ]
)

print(response.text)

