"""Like monitor — detects new likes by a target user."""
import time
from typing import List, Set, Union

from src.monitors.base import TwitterMonitorBase
from src.utils.parser  import parse_media_from_tweet, parse_text_from_tweet, find_all, find_one
from src.utils.state   import StateManager


def _like_id(like: dict) -> str:
    return find_one(like, 'rest_id') or ''


def _like_id_set(likes: list) -> Set[str]:
    return {_like_id(l) for l in likes}


def _filter_ads(likes: list) -> list:
    """Strip promoted/advertiser content from the like list."""
    clean = []
    for like in likes:
        if find_one(like, 'card'):
            continue
        if find_one(like, 'userLabelType') == 'BusinessLabel':
            continue
        if find_one(like, '__typename') == 'TweetWithVisibilityResultss':
            continue
        src = find_one(like, 'source') or ''
        if 'Advertiser' in src or 'advertiser' in src:
            continue
        clean.append(like)
    return clean


class LikeMonitor(TwitterMonitorBase):
    monitor_type         = 'Like'
    _ID_SET_MAX_SIZE     = 1000

    def __init__(self, username, title, token_config, user_config, cookies_dir):
        super().__init__(self.monitor_type, username, title, token_config, user_config, cookies_dir)

        saved_likes = StateManager.get(self.monitor_type, self.username, 'known_like_ids')
        if saved_likes is not None:
            self.known_like_ids = set(saved_likes)
            self.logger.info('Loaded state: {} known likes'.format(len(self.known_like_ids)))
        else:
            likes = self._get_likes()
            while likes is None:
                time.sleep(60)
                likes = self._get_likes()
            self.known_like_ids: Set[str] = _like_id_set(likes)
            StateManager.set(self.monitor_type, self.username, 'known_like_ids', list(self.known_like_ids))

        self.logger.info('LikeMonitor ready. {} existing likes.'.format(len(self.known_like_ids)))

    def _get_likes(self) -> Union[list, None]:
        resp = self.twitter_watcher.query(
            'Likes',
            {'userId': self.user_id, 'includePromotedContent': True, 'count': 1000},
        )
        return _filter_ads(find_all(resp, 'tweet_results')) if resp is not None else None

    def watch(self) -> bool:
        likes = self._get_likes()
        if likes is None:
            return False

        new_likes = []
        for like in likes:
            lid = _like_id(like)
            if lid in self.known_like_ids:
                break
            self.known_like_ids.add(lid)
            new_likes.append(like)

        # Prevent unbounded growth
        if len(self.known_like_ids) > self._ID_SET_MAX_SIZE:
            self.known_like_ids = set(list(self.known_like_ids)[-self._ID_SET_MAX_SIZE:])

        StateManager.set(self.monitor_type, self.username, 'known_like_ids', list(self.known_like_ids))
        StateManager.save()

        for like in reversed(new_likes):
            photos, videos = parse_media_from_tweet(like)
            text           = parse_text_from_tweet(like)
            user           = find_one(like, 'user_results')
            screen         = find_one(user, 'screen_name') or '?'
            self.send_message('Liked @{}: {}'.format(screen, text), photos, videos)

        self.update_last_watch_time()
        return True

    def status(self) -> str:
        return 'last_watch={}, known_likes={}'.format(
            self.get_last_watch_time(), len(self.known_like_ids))
