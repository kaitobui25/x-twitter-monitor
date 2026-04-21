"""
Centralized logging setup.
- One rotating main.log for global WARNING+
- Per-component rotating log files (10 MB max, keep 5 backups)
- Console output mirrors WARNING+ to stdout
"""
import logging
import os
from logging.handlers import RotatingFileHandler

_MAX_BYTES  = 10 * 1024 * 1024   # 10 MB per file
_BACKUP_CNT = 5                   # keep 5 rotated backups
_FMT        = '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
_DATE_FMT   = '%Y-%m-%d %H:%M:%S'

_configured_loggers: set = set()


def _make_rotating_handler(path: str, level=logging.DEBUG) -> RotatingFileHandler:
    handler = RotatingFileHandler(
        path,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_CNT,
        encoding='utf-8',
    )
    handler.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    handler.setLevel(level)
    return handler


def setup_root(log_dir: str) -> None:
    """Configure root logger: WARNING -> main.log + stderr."""
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # Rotating file: WARNING+
    root.addHandler(_make_rotating_handler(
        os.path.join(log_dir, 'main.log'), level=logging.WARNING))

    # Console: WARNING+
    console = logging.StreamHandler()
    console.setLevel(logging.WARNING)
    console.setFormatter(logging.Formatter(_FMT, datefmt=_DATE_FMT))
    root.addHandler(console)


def get_logger(name: str, log_dir: str, level=logging.INFO) -> logging.Logger:
    """Return a named logger with its own rotating file handler.

    Safe to call multiple times with the same name (idempotent).
    """
    logger = logging.getLogger(name)
    if name in _configured_loggers:
        return logger

    os.makedirs(log_dir, exist_ok=True)
    safe_name = name.replace('/', '_').replace('\\', '_')
    log_path  = os.path.join(log_dir, '{}.log'.format(safe_name))

    logger.setLevel(level)
    logger.addHandler(_make_rotating_handler(log_path, level=level))
    _configured_loggers.add(name)
    return logger
