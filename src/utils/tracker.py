"""
StatusTracker — tracks last-seen timestamps for monitors and notifier health.
Raises alerts when a monitor hasn't run for > threshold minutes.
"""
import logging
from datetime import datetime, timedelta, timezone


class StatusTracker:
    monitors_status:  dict = {}
    notifiers_status: dict = {}
    logger = logging.getLogger('status')

    # Alert if a monitor hasn't updated in this many minutes
    STALE_THRESHOLD_MINUTES = 30

    def __new__(cls):
        raise Exception('Do not instantiate StatusTracker!')

    # -- Monitor --

    @classmethod
    def update_monitor_status(cls, monitor_type: str, username: str) -> None:
        cls.monitors_status['{}-{}'.format(monitor_type, username)] = datetime.now(timezone.utc)

    @classmethod
    def get_monitor_status(cls, monitor_type: str, username: str) -> datetime | None:
        return cls.monitors_status.get('{}-{}'.format(monitor_type, username))

    # -- Notifier --

    @classmethod
    def set_notifier_status(cls, notifier: str, ok: bool) -> None:
        cls.notifiers_status[notifier] = ok

    # -- Health check --

    @classmethod
    def check(cls) -> list[str]:
        """Return list of alert strings for anything unhealthy."""
        alerts = []
        threshold = datetime.now(timezone.utc) - timedelta(minutes=cls.STALE_THRESHOLD_MINUTES)

        for name, ts in cls.monitors_status.items():
            cls.logger.info('{}: last_seen={}'.format(name, ts))
            if ts < threshold:
                alerts.append('[STALE] {} — last seen: {}'.format(name, ts.strftime('%H:%M:%S UTC')))

        for name, ok in cls.notifiers_status.items():
            cls.logger.info('{}: ok={}'.format(name, ok))
            if not ok:
                alerts.append('[NOTIFIER ERROR] {}'.format(name))

        return alerts

    @classmethod
    def summary(cls) -> str:
        """Human-readable status summary for daily digest."""
        lines = ['=== Monitor Status ===']
        for name, ts in cls.monitors_status.items():
            lines.append('  {}: {}'.format(name, ts.strftime('%Y-%m-%d %H:%M:%S UTC')))
        lines.append('=== Notifiers ===')
        for name, ok in cls.notifiers_status.items():
            lines.append('  {}: {}'.format(name, 'OK' if ok else 'ERROR'))
        return '\n'.join(lines)
