"""
Telegram notifier.
"""
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import List, Union

import telegram
from retry import retry
from telegram.error import BadRequest, RetryAfter, TimedOut, NetworkError

from src.notifiers.base import Message, NotifierBase


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
        cls.bot    = telegram.Bot(token=token,
                                  request=telegram.utils.request.Request(con_pool_size=2))
        cls.token  = token
        cls.logger = logging.getLogger(logger_name)
        updates    = cls._get_updates()
        cls.update_offset = updates[-1].update_id + 1 if updates else None
        cls.logger.info('Telegram notifier initialized.')
        super().init()

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------

    @classmethod
    @retry((RetryAfter, TimedOut, NetworkError), delay=10, tries=10)
    def _send_single(cls, chat_id, text, photos, videos):
        if videos:
            cls.bot.send_video(chat_id=chat_id, video=videos[0], caption=text, timeout=60)
        elif photos:
            if len(photos) == 1:
                cls.bot.send_photo(chat_id=chat_id, photo=photos[0], caption=text, timeout=60)
            else:
                group = [telegram.InputMediaPhoto(media=photos[0], caption=text)]
                group += [telegram.InputMediaPhoto(media=p) for p in photos[1:10]]
                cls.bot.send_media_group(chat_id=chat_id, media=group, timeout=60)
        else:
            cls.bot.send_message(chat_id=chat_id, text=text,
                                 disable_web_page_preview=True, timeout=60)

    @classmethod
    def send_message(cls, message: TelegramMessage):
        assert cls.initialized
        assert isinstance(message, TelegramMessage)
        for chat_id in message.chat_id_list:
            try:
                cls._send_single(chat_id, message.text,
                                  message.photo_url_list, message.video_url_list)
            except BadRequest as e:
                cls.logger.error('BadRequest ({}), retrying without media.'.format(e))
                cls._send_single(chat_id, message.text, None, None)

    # ------------------------------------------------------------------
    # Updates / interactive
    # ------------------------------------------------------------------

    @classmethod
    @retry((RetryAfter, TimedOut, NetworkError), delay=60)
    def _get_updates(cls, offset=None) -> List[telegram.Update]:
        return cls.bot.get_updates(offset=offset)

    @classmethod
    def _get_new_updates(cls) -> List[telegram.Update]:
        updates = cls._get_updates(offset=cls.update_offset)
        if updates:
            cls.update_offset = updates[-1].update_id + 1
        return updates

    @classmethod
    def confirm(cls, message: TelegramMessage) -> bool:
        assert cls.initialized
        message.text = '{}\nReply Y to confirm, N to cancel.'.format(message.text)
        cls.put_message_into_queue(message)
        sent_at = datetime.now(timezone.utc)
        while True:
            for upd in cls._get_new_updates():
                msg = upd.message
                if msg.date < sent_at or msg.chat.id not in message.chat_id_list:
                    continue
                if msg.text.upper() == 'Y':
                    return True
                if msg.text.upper() == 'N':
                    return False
            time.sleep(10)

    @classmethod
    def listen_exit_command(cls, chat_id):
        def _listen():
            started = datetime.now(timezone.utc)
            while True:
                for upd in cls._get_new_updates():
                    msg = upd.message
                    if msg.date < started or msg.chat.id != chat_id:
                        continue
                    if msg.text.upper() == 'EXIT':
                        if cls.confirm(TelegramMessage([chat_id], 'Confirm EXIT?')):
                            cls.put_message_into_queue(
                                TelegramMessage([chat_id], 'Shutting down in 5 seconds...'))
                            cls.logger.warning('EXIT command received via Telegram.')
                            time.sleep(5)
                            os._exit(0)
                time.sleep(20)
        threading.Thread(target=_listen, daemon=True, name='tg-exit-listener').start()


def send_alert(token: str, chat_id: int, message: str) -> None:
    """Fire-and-forget alert bypassing the queue — for critical situations."""
    try:
        bot = telegram.Bot(token=token)
        bot.send_message(chat_id=chat_id, text=message, timeout=60)
    except Exception as e:
        logging.getLogger('telegram').error('send_alert failed: {}'.format(e))
