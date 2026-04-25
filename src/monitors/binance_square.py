"""
BinanceSquareMonitor — watches for new posts from a Binance Square profile.

Inherits from MonitorBase (platform-agnostic).
Uses BinanceWatcher for data fetching.
Reuses the same Gemini AI image analysis pipeline as TweetMonitor.
"""
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import requests as http_requests

from src.monitors.base       import MonitorBase
from src.core.binance_watcher import BinanceWatcher
from src.utils.state          import StateManager
from src.utils.gemini_extractor import extract_chart

# Ignore posts older than this many hours on first run
_POST_MAX_AGE_HOURS = 48

# Minimum gap between consecutive Gemini calls
_GEMINI_INTER_IMAGE_DELAY_SECONDS = 120  # 2 minutes

# Project root (same as main.py)
_ROOT = sys.path[0]

# Global call counter for Gemini rate-limiting (shared with TweetMonitor)
_global_gemini_calls_count = 0


def _parse_post_id(post: dict) -> Optional[str]:
    """
    Extract a stable, unique ID from a Binance Square post dict.
    Tries multiple known field names since the API may vary.
    """
    for key in ("id", "contentId", "articleId", "postId", "feedId", "code"):
        val = post.get(key)
        if val:
            return str(val)
    return None


def _parse_post_text(post: dict) -> str:
    """Extract the text body of a post."""
    for key in ("bodyTextOnly", "body", "content", "title", "summary", "text"):
        val = post.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return "(no text)"


def _parse_post_images(post: dict) -> List[str]:
    """
    Extract image URLs from a post dict.
    Handles various response structures Binance may use.
    """
    images = []

    # Common patterns
    for key in ("images", "imageList", "imageUrls", "mediaList", "coverImages", "pics"):
        val = post.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str) and item.startswith("http"):
                    images.append(item)
                elif isinstance(item, dict):
                    for img_key in ("url", "imageUrl", "src", "coverUrl"):
                        url = item.get(img_key)
                        if url and isinstance(url, str) and url.startswith("http"):
                            images.append(url)
                            break

    # Single cover image
    if not images:
        for key in ("coverImage", "coverUrl", "thumbnailUrl", "imageUrl"):
            url = post.get(key)
            if url and isinstance(url, str) and url.startswith("http"):
                images.append(url)
                break

    return images


def _parse_post_url(post: dict, handle: str) -> str:
    """Construct the canonical URL of a post."""
    post_id = _parse_post_id(post)
    if post_id:
        return "https://www.binance.com/square/post/{}".format(post_id)
    return "https://www.binance.com/vi/square/profile/{}".format(handle)


def _parse_post_time(post: dict) -> Optional[datetime]:
    """Return post creation time as a UTC-aware datetime, or None."""
    for key in ("createTime", "publishTime", "timestamp", "time", "createdAt"):
        val = post.get(key)
        if val is None:
            continue
        try:
            # Binance typically returns millisecond epoch timestamps
            ts = int(val)
            if ts > 1_000_000_000_000:  # milliseconds
                ts //= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except (ValueError, TypeError):
            pass
    return None


def _next_sequence_number(directory: str, date_str: str, ext: str) -> int:
    """Scan directory for files matching YYYY-MM-DD-NNN.<ext> and return next free seq."""
    existing = set()
    if os.path.isdir(directory):
        for fname in os.listdir(directory):
            if fname.startswith(date_str + "-") and fname.endswith("." + ext):
                try:
                    seq_part = fname[len(date_str) + 1 : -(len(ext) + 1)]
                    existing.add(int(seq_part))
                except ValueError:
                    pass
    n = 1
    while n in existing:
        n += 1
    return n


# ---------------------------------------------------------------------------

class BinanceSquareMonitor(MonitorBase):
    """Monitors a Binance Square profile for new posts."""

    monitor_type = "BinanceSquare"

    def __init__(self, handle: str, title: str, token_config: dict, user_config: dict):
        """
        Parameters
        ----------
        handle : str
            The Binance Square profile handle (e.g. "gem10x").
        title : str
            Display name used in notifications.
        token_config : dict
            Global secrets (gemini_api_keys, telegram_bot_token, etc.).
        user_config : dict
            Per-target notification destinations.
        """
        # MonitorBase uses `identifier` — we use `handle` as the unique identifier.
        super().__init__(self.monitor_type, handle, title, token_config, user_config)

        self.handle  = handle
        self.watcher = BinanceWatcher(handle=handle, max_posts=20)

        # Load last-seen post ID from persistent state
        saved_id = StateManager.get(self.monitor_type, self.handle, "last_post_id")
        if saved_id is not None:
            self.last_post_id = str(saved_id)
            self.logger.info("Loaded state: last_post_id=%s", self.last_post_id)
        else:
            # First run: fetch current posts to establish baseline (no notifications)
            self.logger.info("First run — establishing baseline for @%s...", handle)
            posts = self._get_posts_with_retry()
            if posts:
                ids = [_parse_post_id(p) for p in posts if _parse_post_id(p)]
                self.last_post_id = ids[0] if ids else ""  # most recent first
            else:
                self.last_post_id = ""
            StateManager.set(self.monitor_type, self.handle, "last_post_id", self.last_post_id)
            StateManager.save()
            self.logger.info("Baseline set: last_post_id=%s", self.last_post_id)

        self.logger.info("BinanceSquareMonitor ready for handle='%s'", handle)

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _get_posts_with_retry(self, retries: int = 3) -> Optional[list]:
        for attempt in range(retries):
            posts = self.watcher.get_posts()
            if posts is not None:
                return posts
            if attempt < retries - 1:
                self.logger.warning("get_posts() returned None, retrying in 60s...")
                time.sleep(60)
        return None

    # ------------------------------------------------------------------
    # Image download + Gemini extraction (same logic as TweetMonitor)
    # ------------------------------------------------------------------

    def _process_images(self, images: List[str]) -> None:
        if not images:
            return

        gemini_keys = self.token_config.get("gemini_api_keys", {})
        now      = datetime.now()
        date_str = now.strftime("%Y-%m-%d")

        img_dir  = os.path.join(_ROOT, "follower", self.handle, "img",  date_str)
        json_dir = os.path.join(_ROOT, "follower", self.handle, "json", date_str)
        os.makedirs(img_dir,  exist_ok=True)
        os.makedirs(json_dir, exist_ok=True)

        total = len(images)
        self.logger.info(
            "Processing %d image(s) (Gemini calls: %d).",
            total, total if gemini_keys else 0,
        )

        for idx, image_url in enumerate(images):
            seq       = _next_sequence_number(img_dir, date_str, "jpg")
            file_stem = "{}-{:03d}".format(date_str, seq)
            img_path  = os.path.join(img_dir,  file_stem + ".jpg")
            json_path = os.path.join(json_dir, file_stem + ".json")

            # Download image
            try:
                resp = http_requests.get(image_url, timeout=30)
                resp.raise_for_status()
                with open(img_path, "wb") as f:
                    f.write(resp.content)
                self.logger.info("Image saved: %s", img_path)
            except Exception as e:
                self.logger.error("Failed to download %s: %s", image_url, e)
                continue

            # Gemini chart extraction
            if not gemini_keys:
                self.logger.warning("No Gemini API keys — skipping chart extraction.")
                continue

            global _global_gemini_calls_count
            if _global_gemini_calls_count > 0:
                self.logger.info(
                    "Global Gemini call #%d: waiting %ds before next call...",
                    _global_gemini_calls_count + 1, _GEMINI_INTER_IMAGE_DELAY_SECONDS,
                )
                time.sleep(_GEMINI_INTER_IMAGE_DELAY_SECONDS)

            _global_gemini_calls_count += 1
            ok = extract_chart(img_path, json_path)
            if not ok:
                self.logger.warning("Gemini extraction failed for %s", img_path)

    # ------------------------------------------------------------------
    # Main watch cycle
    # ------------------------------------------------------------------

    def watch(self) -> bool:
        self.logger.info("Checking Binance Square @%s...", self.handle)
        posts = self._get_posts_with_retry()
        if posts is None:
            self.logger.error("Failed to fetch posts after retries.")
            return False

        time_threshold = datetime.now(timezone.utc) - timedelta(hours=_POST_MAX_AGE_HOURS)
        new_posts = []

        for post in posts:
            post_id = _parse_post_id(post)
            if not post_id:
                continue

            # Stop when we reach an already-seen post
            if post_id == self.last_post_id:
                break

            # Skip very old posts (avoids flood on first run after long downtime)
            post_time = _parse_post_time(post)
            if post_time and post_time < time_threshold:
                continue

            new_posts.append(post)

        if not new_posts:
            self.logger.info("No new posts for @%s.", self.handle)
            self.update_last_watch_time()
            return True

        self.logger.info("Found %d new post(s) for @%s.", len(new_posts), self.handle)

        # Update state to the newest post BEFORE processing (safe against partial failures)
        newest_id = _parse_post_id(new_posts[0])
        if newest_id:
            self.last_post_id = newest_id
            StateManager.set(self.monitor_type, self.handle, "last_post_id", self.last_post_id)
            StateManager.save()

        # Process in chronological order (oldest first)
        for post in reversed(new_posts):
            post_id  = _parse_post_id(post)
            text     = _parse_post_text(post)
            images   = _parse_post_images(post)
            post_url = _parse_post_url(post, self.handle)

            message = "{}\nLink: {}".format(text, post_url)
            self.send_message(message, photo_url_list=images or None)
            self.logger.info("New post notified: %s", post_id)

            # Download images & run Gemini
            self._process_images(images)

        self.update_last_watch_time()
        return True

    def status(self) -> str:
        return "last_watch={}, last_post_id={}".format(
            self.get_last_watch_time(), self.last_post_id
        )
