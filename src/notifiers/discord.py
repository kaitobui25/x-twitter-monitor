"""Discord notifier."""
import logging
from typing import List, Union

import requests

from src.notifiers.base import Message, NotifierBase


class DiscordMessage(Message):
    def __init__(self, webhook_url_list: List[str], text: str,
                 photo_url_list: Union[List[str], None] = None,
                 video_url_list: Union[List[str], None] = None):
        super().__init__(text, photo_url_list, video_url_list)
        self.webhook_url_list = webhook_url_list


class DiscordNotifier(NotifierBase):
    notifier_name = 'Discord'

    @classmethod
    def init(cls, logger_name: str):
        cls.logger = logging.getLogger(logger_name)
        cls.logger.info('Discord notifier initialized.')
        super().init()

    @classmethod
    def _post(cls, url: str, data: dict):
        r = requests.post(url, json=data, timeout=60)
        if r.status_code != 204:
            raise RuntimeError('Discord error {} {}'.format(r.status_code, r.text[:200]))

    @classmethod
    def send_message(cls, message: DiscordMessage):
        assert cls.initialized and isinstance(message, DiscordMessage)
        for url in message.webhook_url_list:
            cls._post(url, {'content': message.text})
            for p in (message.photo_url_list or []):
                cls._post(url, {'content': p})
            for v in (message.video_url_list or []):
                cls._post(url, {'content': v})
