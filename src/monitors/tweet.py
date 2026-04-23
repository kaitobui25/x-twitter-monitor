"""Tweet monitor — watches for new tweets from a target user."""
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import requests as http_requests

from src.monitors.base  import MonitorBase
from src.utils.parser   import (parse_media_from_tweet, parse_text_from_tweet,
                                parse_create_time_from_tweet, find_all, find_one,
                                get_content, convert_html_to_text)
from src.utils.state    import StateManager
from src.utils.gemini_extractor import extract_chart

# Ignore tweets older than this many minutes (avoids flood on startup)
_TWEET_MAX_AGE_MINUTES = 120

# Minimum gap between consecutive Gemini calls when multiple images are present
_GEMINI_INTER_IMAGE_DELAY_SECONDS = 120   # 2 minutes

# Root of the project (same resolution as main.py)
_ROOT = sys.path[0]

# Đếm tổng số lần gọi API trong một phiên chạy để áp dụng delay toàn cục
_global_gemini_calls_count = 0


def _tweet_belongs_to_user(tweet: dict, user_id: str) -> bool:
    user = find_one(tweet, 'user_results')
    return find_one(user, 'rest_id') == user_id


def _next_sequence_number(directory: str, date_str: str, ext: str) -> int:
    """
    Scan `directory` for files matching YYYY-MM-DD-NNN.<ext> and return
    the next free sequence number (1-based).
    """
    existing = set()
    if os.path.isdir(directory):
        for fname in os.listdir(directory):
            # Match e.g. 2026-04-23-003.jpg
            if fname.startswith(date_str + '-') and fname.endswith('.' + ext):
                try:
                    seq_part = fname[len(date_str) + 1 : -(len(ext) + 1)]
                    existing.add(int(seq_part))
                except ValueError:
                    pass
    n = 1
    while n in existing:
        n += 1
    return n


class TweetMonitor(MonitorBase):
    monitor_type = 'Tweet'

    def __init__(self, username, title, token_config, user_config, cookies_dir):
        super().__init__(self.monitor_type, username, title, token_config, user_config, cookies_dir)

        saved_id = StateManager.get(self.monitor_type, self.username, 'last_tweet_id')
        if saved_id is not None:
            self.last_tweet_id = saved_id
            self.logger.info('Loaded state: last_tweet_id={}'.format(self.last_tweet_id))
        else:
            tweet_list = self._get_tweet_list()
            while tweet_list is None:
                time.sleep(60)
                tweet_list = self._get_tweet_list()

            self.last_tweet_id = max(
                (int(find_one(t, 'rest_id')) for t in tweet_list if _tweet_belongs_to_user(t, self.user_id)),
                default=-1,
            )
            StateManager.set(self.monitor_type, self.username, 'last_tweet_id', self.last_tweet_id)

        self.logger.info('TweetMonitor ready. user_id={}, last_tweet_id={}'.format(
            self.user_id, self.last_tweet_id))

    def _get_tweet_list(self):
        resp = self.twitter_watcher.query(
            'UserTweetsAndReplies',
            {'userId': self.user_id, 'includePromotedContent': True, 'withVoice': True, 'count': 1000},
        )
        return find_all(resp, 'tweet_results') if resp is not None else None

    def _get_tweet_detail(self, tweet_id: str) -> dict:
        resp = self.twitter_watcher.query(
            'TweetDetail',
            {'focalTweetId': tweet_id, 'withVoice': True,
             'includePromotedContent': True, 'withCommunity': True, 'withBirdwatchNotes': True},
        )
        entries = find_one(resp, 'entries') or []
        for entry in entries:
            if find_one(entry, 'rest_id') == tweet_id:
                return entry
        return resp

    # ------------------------------------------------------------------
    # Image download + Gemini extraction
    # ------------------------------------------------------------------

    def _process_images(self, photos: list) -> None:
        """
        Download each photo, save to follower/<username>/img/, then call
        Gemini to extract chart data → follower/json/.

        Rules:
        - If there are multiple images, insert a 2-minute delay between
          consecutive Gemini API calls to avoid rate-limiting.
        - Gemini key rotation is handled inside extract_chart() via the
          module-level round-robin state in gemini_extractor.
        """
        if not photos:
            return

        gemini_keys = self.token_config.get('gemini_api_keys', {})

        now      = datetime.now()
        date_str = now.strftime('%Y-%m-%d')

        # Structure: follower/<username>/[img|json]/<YYYY-MM-DD>/
        img_dir  = os.path.join(_ROOT, 'follower', self.username, 'img',  date_str)
        json_dir = os.path.join(_ROOT, 'follower', self.username, 'json', date_str)
        
        os.makedirs(img_dir,  exist_ok=True)
        os.makedirs(json_dir, exist_ok=True)

        total = len(photos)
        self.logger.info('Processing {} image(s) from tweet (Gemini will be called {} time(s)).'.format(
            total, total if gemini_keys else 0))

        for idx, photo_url in enumerate(photos):
            # ---- find next available sequence number in the date-specific folder ----
            seq = _next_sequence_number(img_dir, date_str, 'jpg')
            file_stem = '{}-{:03d}'.format(date_str, seq)
            img_path  = os.path.join(img_dir,  file_stem + '.jpg')
            json_path = os.path.join(json_dir, file_stem + '.json')

            # ---- download image ----
            try:
                resp = http_requests.get(photo_url, timeout=30)
                resp.raise_for_status()
                with open(img_path, 'wb') as f:
                    f.write(resp.content)
                self.logger.info('Image saved: {}'.format(img_path))
            except Exception as e:
                self.logger.error('Failed to download {}: {}'.format(photo_url, e))
                continue   # skip Gemini step if download failed

            # ---- Gemini extraction ----
            if not gemini_keys:
                self.logger.warning('No Gemini API keys configured — skipping chart extraction.')
                continue

            global _global_gemini_calls_count
            # Insert delay BEFORE every call except the very first one globally
            if _global_gemini_calls_count > 0:
                self.logger.info(
                    'Global image call ({}): waiting {}s before next Gemini call…'.format(
                        _global_gemini_calls_count + 1, _GEMINI_INTER_IMAGE_DELAY_SECONDS))
                time.sleep(_GEMINI_INTER_IMAGE_DELAY_SECONDS)

            _global_gemini_calls_count += 1
            ok = extract_chart(img_path, json_path)
            if not ok:
                self.logger.warning('Gemini extraction failed for {}'.format(img_path))

    # ------------------------------------------------------------------

    def watch(self) -> bool:
        tweet_list = self._get_tweet_list()
        if tweet_list is None:
            return False

        time_threshold = datetime.now(timezone.utc) - timedelta(minutes=_TWEET_MAX_AGE_MINUTES)
        max_seen_id    = -1
        new_tweets     = []

        for tweet in tweet_list:
            if not _tweet_belongs_to_user(tweet, self.user_id):
                continue
            tweet_id = int(find_one(tweet, 'rest_id'))
            if tweet_id <= self.last_tweet_id:
                continue
            if parse_create_time_from_tweet(tweet) < time_threshold:
                continue
            new_tweets.append(tweet)
            max_seen_id = max(max_seen_id, tweet_id)

        self.last_tweet_id = max(self.last_tweet_id, max_seen_id)
        StateManager.set(self.monitor_type, self.username, 'last_tweet_id', self.last_tweet_id)
        StateManager.save()

        for tweet in reversed(new_tweets):
            tweet_id = find_one(tweet, 'rest_id')
            detail   = self._get_tweet_detail(tweet_id)
            text     = parse_text_from_tweet(detail)
            retweet  = find_one(detail, 'retweeted_status_result')
            quote    = find_one(detail, 'quoted_status_result')

            if retweet:
                photos, videos = parse_media_from_tweet(retweet)
            else:
                photos, videos = parse_media_from_tweet(detail)
                if quote:
                    q_text     = get_content(quote).get('full_text', '')
                    q_username = find_one(find_one(quote, 'user_results'), 'screen_name')
                    text += '\n\nQuote @{}: {}'.format(q_username, q_text)

            source = find_one(detail, 'source')
            if source:
                text += '\n\nSource: {}'.format(convert_html_to_text(source))
            text += '\nLink: https://x.com/{}/status/{}'.format(self.username, tweet_id)

            self.send_message(text, photos, videos)
            self.logger.info('New tweet notified: {}'.format(tweet_id))

            # Download images & run Gemini extraction
            self._process_images(photos)

        self.update_last_watch_time()
        return True

    def status(self) -> str:
        return 'last_watch={}, last_tweet_id={}'.format(self.get_last_watch_time(), self.last_tweet_id)
