"""Tweet monitor — watches for new tweets from a target user."""
import time
from datetime import datetime, timedelta, timezone

from src.monitors.base  import MonitorBase
from src.utils.parser   import (parse_media_from_tweet, parse_text_from_tweet,
                                parse_create_time_from_tweet, find_all, find_one,
                                get_content, convert_html_to_text)
from src.utils.state    import StateManager

# Ignore tweets older than this many minutes (avoids flood on startup)
_TWEET_MAX_AGE_MINUTES = 120


def _tweet_belongs_to_user(tweet: dict, user_id: str) -> bool:
    user = find_one(tweet, 'user_results')
    return find_one(user, 'rest_id') == user_id


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
            tweet_id     = find_one(tweet, 'rest_id')
            detail       = self._get_tweet_detail(tweet_id)
            text         = parse_text_from_tweet(detail)
            retweet      = find_one(detail, 'retweeted_status_result')
            quote        = find_one(detail, 'quoted_status_result')

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

        self.update_last_watch_time()
        return True

    def status(self) -> str:
        return 'last_watch={}, last_tweet_id={}'.format(self.get_last_watch_time(), self.last_tweet_id)
