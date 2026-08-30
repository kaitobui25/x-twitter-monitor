from dataclasses import dataclass
from datetime import datetime
from html import unescape
from typing import Callable, Iterator

from src.core.watcher import TwitterWatcher
from src.exporters.csv_writer import CsvWriter


TWITTER_DATE_FORMAT = '%a %b %d %H:%M:%S %z %Y'


class ExportError(RuntimeError):
    pass


@dataclass
class ExportResult:
    username: str
    output_path: str
    pages_fetched: int
    rows_written: int
    oldest_seen: datetime | None
    newest_seen: datetime | None
    stop_reason: str


def _get_instructions(data: dict) -> list:
    try:
        return data['data']['search_by_raw_query']['search_timeline']['timeline']['instructions']
    except (KeyError, TypeError):
        return []


def _iter_instruction_entries(instructions: list) -> Iterator[dict]:
    for instruction in instructions:
        entry = instruction.get('entry')
        if isinstance(entry, dict):
            yield entry
        for entry in instruction.get('entries', []):
            if isinstance(entry, dict):
                yield entry


def _unwrap_tweet(item_content: dict) -> dict | None:
    result = item_content.get('tweet_results', {}).get('result')
    if not isinstance(result, dict):
        return None
    if result.get('__typename') == 'Tweet':
        return result
    tweet = result.get('tweet')
    if isinstance(tweet, dict) and tweet.get('__typename') == 'Tweet':
        return tweet
    return None


def _extract_page_tweets(instructions: list) -> list[dict]:
    tweets = []
    for entry in _iter_instruction_entries(instructions):
        content = entry.get('content', {})

        item_content = content.get('itemContent')
        if isinstance(item_content, dict):
            tweet = _unwrap_tweet(item_content)
            if tweet:
                tweets.append(tweet)

        for module_item in content.get('items', []):
            item_content = module_item.get('item', {}).get('itemContent')
            if not isinstance(item_content, dict):
                continue
            tweet = _unwrap_tweet(item_content)
            if tweet:
                tweets.append(tweet)
    return tweets


def _find_bottom_cursor(instructions: list) -> str | None:
    for entry in _iter_instruction_entries(instructions):
        content = entry.get('content', {})
        if content.get('cursorType') == 'Bottom':
            value = content.get('value')
            if value:
                return value
    return None


def _tweet_author_id(tweet: dict) -> str:
    legacy = tweet.get('legacy', {})
    author_id = legacy.get('user_id_str')
    if author_id:
        return str(author_id)
    try:
        return str(tweet['core']['user_results']['result']['rest_id'])
    except (KeyError, TypeError):
        return ''


def _tweet_created_at(tweet: dict) -> datetime | None:
    raw = tweet.get('legacy', {}).get('created_at')
    if not raw:
        return None
    try:
        return datetime.strptime(raw, TWITTER_DATE_FORMAT)
    except ValueError:
        return None


def _tweet_text(tweet: dict) -> str:
    note_text = (
        tweet.get('note_tweet', {})
        .get('note_tweet_results', {})
        .get('result', {})
        .get('text')
    )
    if note_text:
        return unescape(note_text)
    return unescape(tweet.get('legacy', {}).get('full_text', ''))


def _reply_status_id(tweet: dict) -> str:
    legacy = tweet.get('legacy', {})
    value = (
        legacy.get('in_reply_to_status_id_str')
        or tweet.get('in_reply_to_status_id_str')
        or tweet.get('in_reply_to_status_id')
    )
    return str(value) if value else ''


def _reply_user_id(tweet: dict) -> str:
    legacy = tweet.get('legacy', {})
    value = (
        legacy.get('in_reply_to_user_id_str')
        or tweet.get('in_reply_to_user_id_str')
        or tweet.get('in_reply_to_user_id')
    )
    return str(value) if value else ''


def _is_reply(tweet: dict) -> bool:
    if _reply_status_id(tweet) or _reply_user_id(tweet):
        return True

    legacy = tweet.get('legacy', {})
    tweet_id = str(tweet.get('rest_id') or legacy.get('id_str') or '')
    conversation_id = str(legacy.get('conversation_id_str') or '')

    # Some SearchTimeline responses omit in_reply_to_* fields. A reply still
    # belongs to the root conversation, so its conversation ID differs from
    # its own tweet ID. This is more reliable than checking for a leading @.
    return bool(tweet_id and conversation_id and conversation_id != tweet_id)


def _tweet_type(tweet: dict) -> str:
    legacy = tweet.get('legacy', {})
    if legacy.get('retweeted_status_result') or tweet.get('retweeted_status_result'):
        return 'retweet'
    if legacy.get('quoted_status_id_str') or tweet.get('quoted_status_result'):
        return 'quote'
    if _is_reply(tweet):
        return 'reply'
    return 'tweet'


def _record_from_tweet(tweet: dict, username: str, created_at: datetime) -> dict:
    legacy = tweet.get('legacy', {})
    tweet_id = str(tweet.get('rest_id') or legacy.get('id_str') or '')

    retweeted = legacy.get('retweeted_status_result') or tweet.get('retweeted_status_result') or {}
    retweeted_result = retweeted.get('result', {}) if isinstance(retweeted, dict) else {}
    if isinstance(retweeted_result, dict) and isinstance(retweeted_result.get('tweet'), dict):
        retweeted_result = retweeted_result['tweet']

    if isinstance(retweeted_result, dict):
        retweeted_tweet_id = (
            retweeted_result.get('rest_id')
            or retweeted_result.get('legacy', {}).get('id_str', '')
        )
    else:
        retweeted_tweet_id = ''

    return {
        'tweet_id': tweet_id,
        'username': username,
        'created_at': created_at.isoformat(),
        'text': _tweet_text(tweet),
        'url': f'https://x.com/{username}/status/{tweet_id}',
        'post_type': _tweet_type(tweet),
        'conversation_id': legacy.get('conversation_id_str', ''),
        'in_reply_to_status_id': _reply_status_id(tweet),
        'in_reply_to_user_id': _reply_user_id(tweet),
        'quoted_tweet_id': legacy.get('quoted_status_id_str', ''),
        'retweeted_tweet_id': retweeted_tweet_id,
    }


class TweetHistoryExporter:
    def __init__(
        self,
        watcher: TwitterWatcher,
        page_size: int = 20,
        progress_callback: Callable[[dict], None] | None = None,
    ):
        self.watcher = watcher
        self.page_size = page_size
        self.progress_callback = progress_callback

    def _resolve_user_id(self, username: str) -> str:
        data = self.watcher.get_user_by_username(username)
        try:
            user_id = data['data']['user']['result']['rest_id']
        except (KeyError, TypeError):
            user_id = None
        if not user_id:
            raise ExportError(f'Cannot find X.com user: {username}')
        return str(user_id)

    def export(
        self,
        username: str,
        start_dt: datetime,
        end_exclusive: datetime,
        output_path: str,
    ) -> ExportResult:
        username = username.strip().lstrip('@')
        if not username:
            raise ExportError('Username is required.')
        if start_dt >= end_exclusive:
            raise ExportError('Invalid date range.')
        if start_dt.tzinfo is None or end_exclusive.tzinfo is None:
            raise ExportError('start_dt and end_exclusive must be timezone-aware.')

        user_id = self._resolve_user_id(username)
        raw_query = (
            f'from:{username} '
            f'since:{start_dt.date().isoformat()} '
            f'until:{end_exclusive.date().isoformat()}'
        )

        cursor = None
        seen_cursors: set[str] = set()
        seen_tweet_ids: set[str] = set()
        pages_fetched = 0
        rows_written = 0
        oldest_seen = None
        newest_seen = None
        stop_reason = 'unknown'

        with CsvWriter(output_path) as writer:
            while True:
                variables = {
                    'rawQuery': raw_query,
                    'count': self.page_size,
                    'querySource': 'typed_query',
                    'product': 'Latest',
                }
                if cursor:
                    variables['cursor'] = cursor

                data = self.watcher.query('SearchTimeline', variables)
                if data is None:
                    raise ExportError(
                        f'Failed to fetch SearchTimeline page {pages_fetched + 1}.'
                    )

                pages_fetched += 1
                instructions = _get_instructions(data)
                if not instructions:
                    stop_reason = 'no_instructions'
                    break

                page_dates = []
                page_added = 0

                for tweet in _extract_page_tweets(instructions):
                    if _tweet_author_id(tweet) != user_id:
                        continue

                    created_at = _tweet_created_at(tweet)
                    if created_at is None:
                        continue

                    page_dates.append(created_at)
                    oldest_seen = created_at if oldest_seen is None else min(oldest_seen, created_at)
                    newest_seen = created_at if newest_seen is None else max(newest_seen, created_at)

                    if not (start_dt <= created_at < end_exclusive):
                        continue

                    legacy = tweet.get('legacy', {})
                    tweet_id = str(tweet.get('rest_id') or legacy.get('id_str') or '')
                    if not tweet_id or tweet_id in seen_tweet_ids:
                        continue

                    seen_tweet_ids.add(tweet_id)
                    writer.write_row(_record_from_tweet(tweet, username, created_at))
                    rows_written += 1
                    page_added += 1

                page_oldest = min(page_dates) if page_dates else None
                page_newest = max(page_dates) if page_dates else None

                if self.progress_callback:
                    self.progress_callback({
                        'page': pages_fetched,
                        'added': page_added,
                        'total': rows_written,
                        'newest': page_newest,
                        'oldest': page_oldest,
                    })

                if page_oldest and page_oldest < start_dt:
                    stop_reason = 'reached_before_start'
                    break

                next_cursor = _find_bottom_cursor(instructions)
                if not next_cursor:
                    stop_reason = 'no_bottom_cursor'
                    break

                if next_cursor == cursor or next_cursor in seen_cursors:
                    stop_reason = 'repeated_cursor'
                    break

                seen_cursors.add(next_cursor)
                cursor = next_cursor

        return ExportResult(
            username=username,
            output_path=output_path,
            pages_fetched=pages_fetched,
            rows_written=rows_written,
            oldest_seen=oldest_seen,
            newest_seen=newest_seen,
            stop_reason=stop_reason,
        )
