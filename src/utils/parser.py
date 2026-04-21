"""
Tweet / profile parsing utilities.
Pure functions — no side-effects, no logging.
"""
from collections import deque
from datetime import datetime, timezone
from typing import Tuple

from bs4 import BeautifulSoup


# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------

def convert_html_to_text(html: str) -> str:
    return BeautifulSoup(html, 'html.parser').get_text()


# ---------------------------------------------------------------------------
# JSON tree traversal
# ---------------------------------------------------------------------------

def find_all(obj, key: str) -> list:
    """DFS — collect *every* value matching `key`."""
    def _dfs(obj, key, res):
        if not obj:
            return res
        if isinstance(obj, list):
            for e in obj:
                res.extend(_dfs(e, key, []))
            return res
        if isinstance(obj, dict):
            if key in obj:
                res.append(obj[key])
            for v in obj.values():
                res.extend(_dfs(v, key, []))
        return res
    return _dfs(obj, key, [])


def find_one(obj, key: str):
    """BFS — return *first* value matching `key`."""
    que = deque([obj])
    while que:
        node = que.popleft()
        if isinstance(node, list):
            que.extend(node)
        elif isinstance(node, dict):
            if key in node:
                return node[key]
            que.extend(node.values())
    return None


def get_content(obj: dict) -> dict:
    return find_one(obj, 'legacy') or {}


def get_cursor(obj) -> str | None:
    entries = find_one(obj, 'entries') or []
    for entry in entries:
        if entry.get('entryId', '').startswith('cursor-bottom'):
            return entry.get('content', {}).get('value')
    return None


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------

def get_photo_url_from_media(media: dict) -> str:
    return media.get('media_url_https', '')


def get_video_url_from_media(media: dict) -> str:
    variants = media.get('video_info', {}).get('variants', [])
    best_bitrate, best_url = -1, ''
    for v in variants:
        b = v.get('bitrate', 0)
        if b > best_bitrate:
            best_bitrate, best_url = b, v.get('url', '')
    return best_url


def parse_media_from_tweet(tweet: dict) -> Tuple[list, list]:
    photos, videos = [], []
    medias = get_content(tweet).get('extended_entities', {}).get('media', [])
    for m in medias:
        t = m.get('type', '')
        if t == 'photo':
            photos.append(get_photo_url_from_media(m))
        elif t in ('video', 'animated_gif'):
            videos.append(get_video_url_from_media(m))
    return photos, videos


# ---------------------------------------------------------------------------
# Tweet fields
# ---------------------------------------------------------------------------

def parse_text_from_tweet(tweet: dict) -> str:
    return convert_html_to_text(get_content(tweet).get('full_text', ''))


def parse_username_from_tweet(tweet: dict) -> str:
    user = find_one(tweet, 'user_results')
    return find_one(user, 'rest_id') or ''


def parse_create_time_from_tweet(tweet: dict) -> datetime:
    created_at = find_one(get_content(tweet), 'created_at')
    if not created_at:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return datetime.strptime(created_at, '%a %b %d %H:%M:%S %z %Y')


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------

def check_initialized(cls_method):
    def wrapper(cls, *args, **kwargs):
        if cls.initialized:
            return cls_method(cls, *args, **kwargs)
        raise RuntimeError('Class {} has not been initialized!'.format(cls.__name__))
    return wrapper
