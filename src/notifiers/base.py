"""
Base classes for all notifiers.
"""
import queue
import threading
from abc import ABC, abstractmethod
from typing import List, Union

from src.utils.parser import check_initialized
from src.utils.tracker import StatusTracker


class Message:
    def __init__(self,
                 text: str,
                 photo_url_list: Union[List[str], None] = None,
                 video_url_list: Union[List[str], None] = None):
        self.text           = text
        self.photo_url_list = photo_url_list
        self.video_url_list = video_url_list


class NotifierBase(ABC):
    initialized = False

    def __new__(cls):
        raise Exception('Do not instantiate {}!'.format(cls.__name__))

    @classmethod
    @abstractmethod
    def init(cls):
        cls.message_queue = queue.SimpleQueue()
        StatusTracker.set_notifier_status(cls.notifier_name, True)
        cls.initialized = True
        cls._start_worker()

    @classmethod
    @abstractmethod
    @check_initialized
    def send_message(cls, message: Message):
        pass

    @classmethod
    @check_initialized
    def _worker(cls):
        while True:
            msg = cls.message_queue.get()
            try:
                StatusTracker.set_notifier_status(cls.notifier_name, False)
                cls.send_message(msg)
                StatusTracker.set_notifier_status(cls.notifier_name, True)
            except Exception as e:
                cls.logger.error('[{}] send failed: {}'.format(cls.notifier_name, e))

    @classmethod
    @check_initialized
    def _start_worker(cls):
        threading.Thread(target=cls._worker, daemon=True, name=cls.notifier_name + '-worker').start()

    @classmethod
    @check_initialized
    def put_message_into_queue(cls, message: Message):
        cls.message_queue.put(message)
