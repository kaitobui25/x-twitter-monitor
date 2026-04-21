"""
Telegram notifier — Python 3.12 compatible.

Gọi thẳng Telegram Bot API qua httpx (không dùng python-telegram-bot SDK)
để tránh xung đột dependency với APScheduler.
"""
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import List, Union

import httpx

from src.notifiers.base import Message, NotifierBase

# ---------------------------------------------------------------------------
# Telegram Bot API helper
# ---------------------------------------------------------------------------

_TELEGRAM_API = 'https://api.telegram.org/bot{token}/{method}'
_SEND_TIMEOUT = 60          # seconds per request
_RETRY_DELAYS = [10, 30, 60, 60, 120]   # back-off schedule on failure


def _api_url(token: str, method: str) -> str:
    return _TELEGRAM_API.format(token=token, method=method)


def _post(token: str, method: str, **kwargs) -> dict:
    """POST to Telegram Bot API. Raises on HTTP/API error."""
    url  = _api_url(token, method)
    resp = httpx.post(url, timeout=_SEND_TIMEOUT, **kwargs)
    resp.raise_for_status()
    data = resp.json()
    if not data.get('ok'):
        raise RuntimeError('Telegram API error: {}'.format(data))
    return data


def _post_with_retry(token: str, method: str, logger: logging.Logger, **kwargs) -> dict | None:
    """_post with simple back-off retry."""
    for attempt, delay in enumerate(_RETRY_DELAYS, 1):
        try:
            return _post(token, method, **kwargs)
        except httpx.HTTPStatusError as e:
            # 429 Too Many Requests — respect Retry-After if present
            retry_after = int(e.response.headers.get('Retry-After', delay))
            logger.warning('[TG] 429 rate-limit, waiting {}s…'.format(retry_after))
            time.sleep(retry_after)
        except (httpx.TimeoutException, httpx.NetworkError, RuntimeError) as e:
            logger.warning('[TG] Attempt {}: {} — retrying in {}s'.format(attempt, e, delay))
            time.sleep(delay)
    logger.error('[TG] {} failed after {} retries.'.format(method, len(_RETRY_DELAYS)))
    return None


# ---------------------------------------------------------------------------
# Message & Notifier
# ---------------------------------------------------------------------------

class TelegramMessage(Message):
    def __init__(self,
                 chat_id_list: List[int],
                 text: str,
                 photo_url_list: Union[List[str], None] = None,
                 video_url_list: Union[List[str], None] = None):
        super().__init__(text, photo_url_list, video_url_list)
        self.chat_id_list = chat_id_list


class TelegramNotifier(NotifierBase):
    notifier_name = 'Telegram'

    @classmethod
    def init(cls, token: str, logger_name: str):
        assert token, 'Telegram bot token must not be empty.'
        cls.token  = token
        cls.logger = logging.getLogger(logger_name)

        # Seed update_offset so listen/confirm can track incoming messages
        updates = cls._get_updates()
        cls.update_offset = updates[-1]['update_id'] + 1 if updates else None

        cls.logger.info('Telegram notifier initialized.')
        super().init()

    # ------------------------------------------------------------------
    # Internal send helpers
    # ------------------------------------------------------------------

    @classmethod
    def _send_text(cls, chat_id: int, text: str):
        _post_with_retry(cls.token, 'sendMessage', cls.logger,
                         json={'chat_id': chat_id, 'text': text,
                               'disable_web_page_preview': True})

    @classmethod
    def _send_photo(cls, chat_id: int, photo_url: str, caption: str = ''):
        _post_with_retry(cls.token, 'sendPhoto', cls.logger,
                         json={'chat_id': chat_id, 'photo': photo_url,
                               'caption': caption})

    @classmethod
    def _send_media_group(cls, chat_id: int, photos: List[str], caption: str = ''):
        media = [{'type': 'photo', 'media': photos[0], 'caption': caption}]
        media += [{'type': 'photo', 'media': p} for p in photos[1:10]]
        _post_with_retry(cls.token, 'sendMediaGroup', cls.logger,
                         json={'chat_id': chat_id, 'media': media})

    @classmethod
    def _send_video(cls, chat_id: int, video_url: str, caption: str = ''):
        _post_with_retry(cls.token, 'sendVideo', cls.logger,
                         json={'chat_id': chat_id, 'video': video_url,
                               'caption': caption})

    @classmethod
    def _send_single(cls, chat_id: int, text: str,
                     photos: Union[List[str], None],
                     videos: Union[List[str], None]):
        try:
            if videos:
                cls._send_video(chat_id, videos[0], caption=text)
            elif photos:
                if len(photos) == 1:
                    cls._send_photo(chat_id, photos[0], caption=text)
                else:
                    cls._send_media_group(chat_id, photos, caption=text)
            else:
                cls._send_text(chat_id, text)
        except Exception as e:
            cls.logger.error('[TG] _send_single failed ({}), retrying text-only: {}'.format(chat_id, e))
            cls._send_text(chat_id, text)

    # ------------------------------------------------------------------
    # Public send
    # ------------------------------------------------------------------

    @classmethod
    def send_message(cls, message: TelegramMessage):
        assert cls.initialized
        assert isinstance(message, TelegramMessage)
        for chat_id in message.chat_id_list:
            cls._send_single(chat_id, message.text,
                             message.photo_url_list, message.video_url_list)

    # ------------------------------------------------------------------
    # Updates / interactive (for confirm & listen_exit_command)
    # ------------------------------------------------------------------

    @classmethod
    def _get_updates(cls, offset=None) -> list:
        params = {'timeout': 5}
        if offset is not None:
            params['offset'] = offset
        try:
            data = _post(cls.token, 'getUpdates', json=params)
            return data.get('result', [])
        except Exception:
            return []

    @classmethod
    def _get_new_updates(cls) -> list:
        updates = cls._get_updates(offset=cls.update_offset)
        if updates:
            cls.update_offset = updates[-1]['update_id'] + 1
        return updates

    @classmethod
    def confirm(cls, message: TelegramMessage) -> bool:
        assert cls.initialized
        message.text = '{}\nReply Y to confirm, N to cancel.'.format(message.text)
        cls.put_message_into_queue(message)
        sent_at = datetime.now(timezone.utc)
        while True:
            for upd in cls._get_new_updates():
                msg = upd.get('message', {})
                msg_date = datetime.fromtimestamp(msg.get('date', 0), tz=timezone.utc)
                chat_id  = msg.get('chat', {}).get('id')
                text     = (msg.get('text') or '').strip().upper()
                if msg_date < sent_at or chat_id not in message.chat_id_list:
                    continue
                if text == 'Y':
                    return True
                if text == 'N':
                    return False
            time.sleep(10)

    @classmethod
    def listen_exit_command(cls, chat_id: int):
        def _listen():
            started = datetime.now(timezone.utc)
            while True:
                for upd in cls._get_new_updates():
                    msg = upd.get('message', {})
                    msg_date = datetime.fromtimestamp(msg.get('date', 0), tz=timezone.utc)
                    cid  = msg.get('chat', {}).get('id')
                    text = (msg.get('text') or '').strip().upper()
                    if msg_date < started or cid != chat_id:
                        continue
                    if text == 'EXIT':
                        if cls.confirm(TelegramMessage([chat_id], 'Confirm EXIT?')):
                            cls.put_message_into_queue(
                                TelegramMessage([chat_id], 'Shutting down in 5 seconds...'))
                            cls.logger.warning('EXIT command received via Telegram.')
                            time.sleep(5)
                            os._exit(0)
                time.sleep(20)
        threading.Thread(target=_listen, daemon=True, name='tg-exit-listener').start()


# ---------------------------------------------------------------------------
# Standalone fire-and-forget alert
# ---------------------------------------------------------------------------

def send_alert(token: str, chat_id: int, message: str) -> None:
    """Fire-and-forget alert bypassing the queue — for critical situations."""
    try:
        _post(token, 'sendMessage',
              json={'chat_id': chat_id, 'text': message})
    except Exception as e:
        logging.getLogger('telegram').error('send_alert failed: {}'.format(e))
