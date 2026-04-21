"""CQHttp notifier."""
import logging
from typing import List, Union

import requests

from src.notifiers.base import Message, NotifierBase


def _strip_http(text: str) -> str:
    """QQ intercepts http links — strip the scheme."""
    return text.replace('https://', '').replace('http://', '')


class CqhttpMessage(Message):
    def __init__(self, url_list: List[str], text: str,
                 photo_url_list: Union[List[str], None] = None,
                 video_url_list: Union[List[str], None] = None):
        super().__init__(text, photo_url_list, video_url_list)
        self.url_list = url_list


class CqhttpNotifier(NotifierBase):
    notifier_name = 'Cqhttp'

    @classmethod
    def init(cls, token: str, logger_name: str):
        cls.headers = {'Authorization': 'Bearer {}'.format(token)} if token else None
        cls.logger  = logging.getLogger(logger_name)
        cls.logger.info('CQHttp notifier initialized.')
        super().init()

    @classmethod
    def _post(cls, url: str, data: dict):
        r = requests.post(url, headers=cls.headers, data=data, timeout=60)
        if r.status_code != 200 or r.json().get('status') != 'ok':
            raise RuntimeError('CQHttp error {} {}'.format(r.status_code, r.text[:200]))

    @classmethod
    def send_message(cls, message: CqhttpMessage):
        assert cls.initialized and isinstance(message, CqhttpMessage)
        for url in message.url_list:
            cls._post(url, {'message': _strip_http(message.text)})
            for p in (message.photo_url_list or []):
                cls._post(url, {'message': '[CQ:image,file={}]'.format(p)})
            for v in (message.video_url_list or []):
                cls._post(url, {'message': '[CQ:video,file={}]'.format(v)})
