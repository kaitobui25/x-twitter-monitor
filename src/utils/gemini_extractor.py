"""
Gemini chart extractor.

Supports:
- Named key pool (key1, key2, ...) from config
- Stateful round-robin rotation — next key is always chosen sequentially
- parse_json_response: robust JSON extraction from LLM output
"""
import io
import json
import logging

from google import genai
from PIL import Image

logger = logging.getLogger('gemini-extractor')

# ---------------------------------------------------------------------------
# Round-robin key state (module-level singleton)
# ---------------------------------------------------------------------------

_key_names: list[str] = []   # e.g. ["key1", "key2"]
_key_values: list[str] = []  # actual API key strings
_rr_index: int = 0           # points to the NEXT key to use


def init_key_pool(api_keys_dict: dict) -> None:
    """
    Load the named key pool from config.
    api_keys_dict example: {"key1": "AIza...", "key2": "AIza..."}
    Call this once at startup.
    """
    global _key_names, _key_values, _rr_index
    _key_names  = sorted(api_keys_dict.keys())   # deterministic order: key1, key2...
    _key_values = [api_keys_dict[k] for k in _key_names]
    _rr_index   = 0
    logger.info('Gemini key pool loaded: {} keys ({})'.format(
        len(_key_names), ', '.join(_key_names)))


def _next_key() -> tuple[str, str]:
    """Return (key_name, api_key_value) using round-robin and advance the pointer."""
    global _rr_index
    if not _key_values:
        raise RuntimeError('Gemini key pool is empty. Call init_key_pool() first.')
    idx   = _rr_index % len(_key_values)
    name  = _key_names[idx]
    value = _key_values[idx]
    _rr_index += 1
    logger.info('Using Gemini key: {}'.format(name))
    return name, value


# ---------------------------------------------------------------------------
# JSON parser — robust against markdown fences
# ---------------------------------------------------------------------------

def _parse_json_response(text: str) -> str:
    """
    Strip markdown fences from LLM response and return the raw JSON string.
    Handles: ```json ... ```,  ``` ... ```,  or plain JSON.
    """
    text = text.strip()
    if '```' in text:
        # Take the content inside the FIRST code fence pair
        parts = text.split('```')
        # parts[0] = before first ```, parts[1] = fence content, parts[2] = after ```
        if len(parts) >= 3:
            fence_content = parts[1]
            # Remove optional language tag on first line (e.g. "json\n")
            lines = fence_content.splitlines()
            if lines and lines[0].strip().isalpha():
                fence_content = '\n'.join(lines[1:])
            return fence_content.strip()
    return text


# ---------------------------------------------------------------------------
# Main extraction function
# ---------------------------------------------------------------------------

_PROMPT = """
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


def extract_chart(image_path: str, json_path: str) -> bool:
    """
    Analyse a chart image with Gemini (round-robin key) and write JSON to json_path.

    Returns True on success, False on failure.
    Uses the module-level round-robin key pool — call init_key_pool() at startup.
    """
    try:
        key_name, api_key = _next_key()
    except RuntimeError as e:
        logger.error(str(e))
        return False

    try:
        image         = Image.open(image_path).convert('RGB')
        img_byte_arr  = io.BytesIO()
        image.save(img_byte_arr, format='JPEG')
        img_bytes     = img_byte_arr.getvalue()

        client   = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model='gemini-3.1-flash-lite-preview',
            contents=[
                {
                    'role': 'user',
                    'parts': [
                        {'text': _PROMPT},
                        {
                            'inline_data': {
                                'mime_type': 'image/jpeg',
                                'data': img_bytes,
                            }
                        },
                    ],
                }
            ],
        )

        raw_json = _parse_json_response(response.text)

        # Validate that it is parseable JSON before writing
        parsed = json.loads(raw_json)

        # Attach metadata
        parsed['_meta'] = {
            'source_image': image_path,
            'gemini_key_used': key_name,
        }

        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(parsed, f, ensure_ascii=False, indent=2)

        logger.info('Chart extracted → {} (key={})'.format(json_path, key_name))
        return True

    except json.JSONDecodeError as e:
        logger.error('Gemini returned invalid JSON for {}: {}'.format(image_path, e))
        # Write raw text anyway so user can inspect it
        with open(json_path + '.raw', 'w', encoding='utf-8') as f:
            f.write(response.text if 'response' in dir() else '')
        return False
    except Exception as e:
        logger.error('Gemini extraction failed for {}: {}'.format(image_path, e))
        return False
