"""
MonitorBase — abstract base for all monitors.
MonitorManager — registry that holds active monitor instances.
"""
import logging
from abc import ABC, abstractmethod
from typing import List, Union

from src.notifiers.cqhttp    import CqhttpMessage, CqhttpNotifier
from src.notifiers.discord   import DiscordMessage, DiscordNotifier
from src.notifiers.telegram  import TelegramMessage, TelegramNotifier
from src.core.watcher        import TwitterWatcher
from src.utils.tracker       import StatusTracker


class MonitorBase(ABC):

    def __init__(self, monitor_type: str, username: str, title: str,
                 token_config: dict, user_config: dict, cookies_dir: str):
        self.monitor_type = monitor_type
        self.username     = username
        self.title        = title

        logger_name  = '{}-{}'.format(title, monitor_type)
        self.logger  = logging.getLogger(logger_name)

        # Build watcher with sign-out callback
        self.twitter_watcher = TwitterWatcher(
            auth_username_list=token_config.get('twitter_auth_username_list', []),
            cookies_dir=cookies_dir,
            on_signout=self._on_signout,
        )

        self.user_id = self.twitter_watcher.get_id_by_username(username)
        if not self.user_id:
            raise RuntimeError('Cannot find X.com user: @{}'.format(username))

        self.telegram_chat_id_list    = user_config.get('telegram_chat_id_list', [])
        self.cqhttp_url_list          = user_config.get('cqhttp_url_list', [])
        self.discord_webhook_url_list = user_config.get('discord_webhook_url_list', [])
        self.message_prefix           = '[{}][{}]'.format(title, monitor_type)
        self.update_last_watch_time()

    # ------------------------------------------------------------------
    # Sign-out alert
    # ------------------------------------------------------------------

    def _on_signout(self, account_username: str) -> None:
        self.logger.error('Auth account @{} has been signed out!'.format(account_username))
        msg = (
            '[ALERT] X.com auth account @{} has been SIGNED OUT!\n'
            'Please run: python main.py login --username {} --password <password>\n'
            'Then restart the monitor.'
        ).format(account_username, account_username)
        self.send_message(msg)

    # ------------------------------------------------------------------
    # Status tracking
    # ------------------------------------------------------------------

    def update_last_watch_time(self):
        StatusTracker.update_monitor_status(self.monitor_type, self.username)

    def get_last_watch_time(self):
        return StatusTracker.get_monitor_status(self.monitor_type, self.username)

    # ------------------------------------------------------------------
    # Notification dispatch
    # ------------------------------------------------------------------

    def send_message(self,
                     message: str,
                     photo_url_list: Union[List[str], None] = None,
                     video_url_list: Union[List[str], None] = None):
        full_msg = '{} {}'.format(self.message_prefix, message)
        self.logger.info('Sending: {}'.format(full_msg[:200]))

        photos = [p for p in (photo_url_list or []) if p] or None
        videos = [v for v in (video_url_list or []) if v] or None

        if self.telegram_chat_id_list:
            TelegramNotifier.put_message_into_queue(
                TelegramMessage(self.telegram_chat_id_list, full_msg, photos, videos))
        if self.cqhttp_url_list:
            CqhttpNotifier.put_message_into_queue(
                CqhttpMessage(self.cqhttp_url_list, full_msg, photos, videos))
        if self.discord_webhook_url_list:
            DiscordNotifier.put_message_into_queue(
                DiscordMessage(self.discord_webhook_url_list, full_msg, photos, videos))

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def watch(self) -> bool:
        """Perform one monitoring cycle. Return True on success."""

    @abstractmethod
    def status(self) -> str:
        """Return a short human-readable status string."""


# ---------------------------------------------------------------------------

class MonitorManager:
    monitors: dict | None = None

    def __new__(cls):
        raise Exception('Do not instantiate MonitorManager!')

    @classmethod
    def init(cls, monitors: dict):
        cls.monitors = monitors
        cls.logger   = logging.getLogger('monitor-manager')

    @classmethod
    def get(cls, monitor_type: str, title: str) -> MonitorBase | None:
        assert cls.monitors is not None
        return cls.monitors.get(monitor_type, {}).get(title)

    @classmethod
    def call(cls, monitor_type: str, title: str) -> bool:
        monitor = cls.get(monitor_type, title)
        if not monitor:
            return True
        return monitor.watch()
