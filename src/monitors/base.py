"""
MonitorBase   — platform-agnostic base for ALL monitors.
               Handles: logging, notification dispatch, status tracking.
               Does NOT know anything about Twitter, Binance, or any platform.

TwitterMonitorBase — extends MonitorBase with Twitter-specific watcher setup.
               All existing Twitter monitors (Tweet, Profile, Like, Following)
               inherit from this class instead of MonitorBase.

MonitorManager — registry that holds active monitor instances (unchanged).
"""
import logging
from abc import ABC, abstractmethod
from typing import List, Union

from src.notifiers.cqhttp    import CqhttpMessage, CqhttpNotifier
from src.notifiers.discord   import DiscordMessage, DiscordNotifier
from src.notifiers.telegram  import TelegramMessage, TelegramNotifier
from src.utils.tracker       import StatusTracker


class MonitorBase(ABC):
    """
    Platform-agnostic abstract base.
    Subclasses are responsible for acquiring their own data source (watcher).
    """

    def __init__(self, monitor_type: str, identifier: str, title: str,
                 token_config: dict, user_config: dict):
        """
        Parameters
        ----------
        monitor_type : str
            Short string identifying the monitor kind (e.g. 'Tweet', 'BinanceSquare').
        identifier : str
            The target's unique handle on the platform (username, URL handle, etc.).
        title : str
            Human-readable label used in log/notification prefixes.
        token_config : dict
            Global secrets (API keys, bot tokens). Passed through to subclasses.
        user_config : dict
            Per-target notification config (telegram_chat_id_list, etc.).
        """
        self.monitor_type = monitor_type
        self.identifier   = identifier
        self.title        = title
        self.token_config = token_config  # available to subclasses (e.g. gemini_api_keys)

        logger_name = '{}-{}'.format(title, monitor_type)
        self.logger = logging.getLogger(logger_name)

        self.telegram_chat_id_list    = user_config.get('telegram_chat_id_list', [])
        self.cqhttp_url_list          = user_config.get('cqhttp_url_list', [])
        self.discord_webhook_url_list = user_config.get('discord_webhook_url_list', [])
        self.message_prefix           = '[{}][{}]'.format(title, monitor_type)
        self.update_last_watch_time()

    # ------------------------------------------------------------------
    # Status tracking
    # ------------------------------------------------------------------

    def update_last_watch_time(self):
        StatusTracker.update_monitor_status(self.monitor_type, self.identifier)

    def get_last_watch_time(self):
        return StatusTracker.get_monitor_status(self.monitor_type, self.identifier)

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

class TwitterMonitorBase(MonitorBase):
    """
    MonitorBase specialised for Twitter/X.com monitors.
    Adds: TwitterWatcher initialisation, user_id lookup, sign-out detection.

    All existing Twitter monitors (TweetMonitor, ProfileMonitor, LikeMonitor,
    FollowingMonitor) inherit from this class — zero behaviour change.
    """

    def __init__(self, monitor_type: str, username: str, title: str,
                 token_config: dict, user_config: dict, cookies_dir: str):
        # MonitorBase uses `identifier`; Twitter uses `username` as the identifier.
        super().__init__(monitor_type, username, title, token_config, user_config)

        # Keep `username` as a convenience alias for Twitter-specific code.
        self.username = username

        # Import here to avoid loading Twitter-specific deps for non-Twitter monitors.
        from src.core.watcher import TwitterWatcher

        self.twitter_watcher = TwitterWatcher(
            auth_username_list=token_config.get('twitter_auth_username_list', []),
            cookies_dir=cookies_dir,
            on_signout=self._on_signout,
        )

        self.user_id = self.twitter_watcher.get_id_by_username(username)
        if not self.user_id:
            raise RuntimeError('Cannot find X.com user: @{}'.format(username))

        self.logger.info('TwitterMonitorBase ready for @{} (user_id={})'.format(
            username, self.user_id))

    # ------------------------------------------------------------------
    # Sign-out alert (Twitter-specific)
    # ------------------------------------------------------------------

    def _on_signout(self, account_username: str) -> None:
        self.logger.error('Auth account @{} has been signed out!'.format(account_username))
        msg = (
            '[ALERT] X.com auth account @{} has been SIGNED OUT!\n'
            'Please run: python main.py login --username {} --password <password>\n'
            'Then restart the monitor.'
        ).format(account_username, account_username)
        self.send_message(msg)


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
