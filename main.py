"""
Twitter Monitor — entry point.

Usage:
  python main.py run                          # start with default config
  python main.py run --config path/to/config.json
  python main.py check-tokens
  python main.py login --username X --password Y
"""
import sys

import json
import logging
import os
import platform
import time
from datetime import datetime, timezone

import click
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.schedulers.background import BlockingScheduler

# ---- project imports ----
from src.core.graphql      import GraphqlAPI
from src.core.login        import login
from src.core.watcher      import TwitterWatcher
from src.monitors.base     import MonitorManager
from src.monitors.following import FollowingMonitor
from src.monitors.like      import LikeMonitor
from src.monitors.profile   import ProfileMonitor
from src.monitors.tweet     import TweetMonitor
from src.notifiers.cqhttp   import CqhttpNotifier
from src.notifiers.discord  import DiscordNotifier
from src.notifiers.telegram import TelegramMessage, TelegramNotifier, send_alert
from src.utils.logger       import setup_root, get_logger
from src.utils.tracker      import StatusTracker
from src.utils.state        import StateManager

# ---------------------------------------------------------------------------
_ROOT = sys.path[0]

DEFAULT_CONFIG  = os.path.join(_ROOT, 'config', 'config.json')
DEFAULT_COOKIES = os.path.join(_ROOT, 'cookies')
DEFAULT_LOGS    = os.path.join(_ROOT, 'logs')

CONFIG_FIELD_TO_MONITOR = {
    'monitor_profile':   ProfileMonitor,
    'monitor_following': FollowingMonitor,
    'monitor_likes':     LikeMonitor,
    'monitor_tweets':    TweetMonitor,
}

# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _strip_comments(obj):
    if isinstance(obj, dict):
        return {k: _strip_comments(v) for k, v in obj.items() if not str(k).startswith('//')}
    if isinstance(obj, list):
        return [_strip_comments(i) for i in obj]
    return obj


def _load_config(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        cfg = _strip_comments(json.load(f))
    assert cfg.get('twitter_accounts'), "config: 'twitter_accounts' is required."
    assert cfg.get('telegram', {}).get('bot_token'), "config: 'telegram.bot_token' is required."
    assert cfg.get('targets'), "config: 'targets' list is required."
    return cfg


def _build_token_config(cfg: dict) -> dict:
    return {
        'telegram_bot_token':         cfg['telegram']['bot_token'],
        'twitter_auth_username_list': [a['username'] for a in cfg['twitter_accounts']],
        'cqhttp_access_token':        cfg.get('cqhttp', {}).get('access_token', ''),
    }


def _resolve_path(value: str | None, fallback: str) -> str:
    p = value or fallback
    return p if os.path.isabs(p) else os.path.join(_ROOT, p)


# ---------------------------------------------------------------------------
# Scheduled jobs
# ---------------------------------------------------------------------------

def _check_health(token: str, chat_id: int, monitors: dict):
    alerts = StatusTracker.check()
    for title, monitor in monitors.get(ProfileMonitor.monitor_type, {}).items():
        if monitor.username.element != monitor.original_username:
            alerts.append('[USERNAME CHANGED] {} -> {}'.format(title, monitor.username.element))
    if alerts:
        send_alert(token=token, chat_id=chat_id,
                   message='[HEALTH ALERT]\n' + '\n'.join(alerts))


def _check_tokens(token: str, chat_id: int, watcher: TwitterWatcher):
    result   = watcher.check_tokens()
    failures = [u for u, ok in result.items() if not ok]
    if failures:
        send_alert(token=token, chat_id=chat_id,
                   message='[TOKEN ALERT] These accounts failed:\n' + '\n'.join(failures))


def _daily_summary(chat_id: int, monitors: dict, watcher: TwitterWatcher,
                   notifier: TelegramNotifier):
    lines = ['=== Daily Summary ===', 'Time: {} UTC'.format(
        datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'))]
    for mtype, group in monitors.items():
        for title, mon in group.items():
            lines.append('[{}] {}: {}'.format(mtype, title, mon.status()))
    token_status = watcher.check_tokens()
    lines.append('')
    lines.append('--- Token Status ---')
    for u, ok in token_status.items():
        lines.append('  @{}: {}'.format(u, 'OK' if ok else 'FAILED'))
    notifier.put_message_into_queue(TelegramMessage([chat_id], '\n'.join(lines)))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
def cli():
    pass


@cli.command('run', context_settings={'show_default': True})
@click.option('--config',  default=DEFAULT_CONFIG,  help='Path to config.json')
@click.option('--cookies', default=DEFAULT_COOKIES, help='Cookie files directory')
@click.option('--logdir',  default=DEFAULT_LOGS,    help='Log output directory')
@click.option('--once',    is_flag=True,            help='Run exactly one scan and then exit (for cron)')
def run(config, cookies, logdir, once):
    """Start the Twitter Monitor."""

    cfg = _load_config(config)
    adv = cfg.get('advanced', {})

    cookies_dir      = _resolve_path(adv.get('cookies_dir'), cookies)
    log_dir          = _resolve_path(adv.get('log_dir'), logdir)
    scan_interval    = cfg.get('schedule', {}).get('scan_interval_seconds', 900)
    telegram_token   = cfg['telegram']['bot_token']
    maintainer_id    = cfg['telegram'].get('maintainer_chat_id')
    token_config     = _build_token_config(cfg)
    targets          = cfg['targets']
    send_daily       = adv.get('send_daily_summary', False)
    listen_exit      = adv.get('listen_exit_command', False)
    confirm_start    = adv.get('confirm_on_start', False)

    # ----- Logging & State -----
    setup_root(log_dir)
    StateManager.init(os.path.join(_ROOT, 'state'))

    get_logger('api',             log_dir)
    get_logger('status',          log_dir)
    get_logger('telegram',        log_dir)
    get_logger('cqhttp',          log_dir)
    get_logger('discord',         log_dir)
    get_logger('monitor-manager', log_dir)

    main_logger = logging.getLogger('main')

    # ----- Notifiers -----
    TelegramNotifier.init(token=telegram_token, logger_name='telegram')
    CqhttpNotifier.init(token=token_config.get('cqhttp_access_token', ''), logger_name='cqhttp')
    DiscordNotifier.init(logger_name='discord')

    # ----- Startup message -----
    startup_text = (
        '[STARTED] Twitter Monitor\n'
        'Host: {}\n'
        'Targets: {}\n'
        'Scan interval: {}s\n'
        'Started at: {} UTC'
    ).format(
        platform.node(),
        ', '.join(t.get('title', t['username']) for t in targets),
        scan_interval,
        datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),
    )
    if maintainer_id:
        TelegramNotifier.put_message_into_queue(
            TelegramMessage([maintainer_id], startup_text))
    main_logger.info(startup_text)

    # ----- Build monitors -----
    monitors  = {cls.monitor_type: {} for cls in CONFIG_FIELD_TO_MONITOR.values()}
    executors = {'default': ThreadPoolExecutor(max(len(targets), 1))}
    scheduler = BlockingScheduler(executors=executors)

    for target in targets:
        username = target['username']
        title    = target.get('title', username)
        user_cfg = {
            'telegram_chat_id_list':      target.get('notify_telegram_chat_ids', []),
            'discord_webhook_url_list':   target.get('notify_discord_webhooks', []),
            'cqhttp_url_list':            target.get('notify_cqhttp_urls', []),
            'monitoring_following_count': target.get('monitor_following', False),
            'monitoring_tweet_count':     target.get('monitor_tweets', False),
            'monitoring_like_count':      target.get('monitor_likes', False),
        }

        for field, monitor_cls in CONFIG_FIELD_TO_MONITOR.items():
            if not (target.get(field, False) or monitor_cls is ProfileMonitor):
                continue

            mtype       = monitor_cls.monitor_type
            logger_name = '{}-{}'.format(title, mtype)
            get_logger(logger_name, os.path.join(log_dir, 'monitors'))

            try:
                monitors[mtype][title] = monitor_cls(
                    username, title, token_config, user_cfg, cookies_dir)
            except Exception as e:
                main_logger.error('Failed to init {} for {}: {}'.format(mtype, title, e))
                if maintainer_id:
                    send_alert(telegram_token, maintainer_id,
                               '[ERROR] Failed to init {} monitor for @{}: {}'.format(
                                   mtype, username, e))
                continue

            if monitor_cls is ProfileMonitor:
                scheduler.add_job(
                    monitors[mtype][title].watch,
                    trigger='interval', seconds=scan_interval,
                    id='profile-{}'.format(title),
                    max_instances=1,
                )

    MonitorManager.init(monitors=monitors)

    # Refresh GraphQL API data every hour
    scheduler.add_job(GraphqlAPI.update_api_data, trigger='cron', hour='*',
                      id='graphql-refresh', max_instances=1)

    # ----- Maintainer periodic tasks -----
    if maintainer_id:
        watcher = TwitterWatcher(token_config['twitter_auth_username_list'], cookies_dir,
                                 on_signout=lambda u: send_alert(
                                     telegram_token, maintainer_id,
                                     '[SIGNED OUT] @{} has been signed out from X.com!\n'
                                     'Run: python main.py login --username {} --password <pass>'.format(u, u)))

        # Hourly health & token check
        scheduler.add_job(_check_health, trigger='cron', hour='*',
                          id='health-check', max_instances=1,
                          args=[telegram_token, maintainer_id, monitors])
        scheduler.add_job(_check_tokens, trigger='cron', hour='*',
                          id='token-check', max_instances=1,
                          args=[telegram_token, maintainer_id, watcher])

        if send_daily:
            scheduler.add_job(_daily_summary, trigger='cron', hour='6',
                              id='daily-summary', max_instances=1,
                              args=[maintainer_id, monitors, watcher, TelegramNotifier])

        if confirm_start:
            if not TelegramNotifier.confirm(
                    TelegramMessage([maintainer_id],
                                    'Monitor ready. Confirm to start watching?')):
                TelegramNotifier.put_message_into_queue(
                    TelegramMessage([maintainer_id], 'Cancelled — monitor will exit.'))
                raise SystemExit(0)
            TelegramNotifier.put_message_into_queue(
                TelegramMessage([maintainer_id], 'Monitor started successfully.'))

        if listen_exit:
            TelegramNotifier.listen_exit_command(maintainer_id)

    print('[OK] Monitor initialized. Targets: {}.'.format(len(targets)))
    print('     Logs -> {}'.format(log_dir))

    if once:
        print('[OK] Running ONE scan (--once).')
        for title, monitor in monitors[ProfileMonitor.monitor_type].items():
            monitor.watch()
        
        # Wait a bit for async notifier queues to drain
        time.sleep(10)
        print('[OK] Scan complete. Exiting.')
        return

    print('[OK] Starting scheduler every {}s.'.format(scan_interval))
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        shutdown_msg = '[STOPPED] Monitor shut down at {} UTC.'.format(
            datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'))
        main_logger.warning(shutdown_msg)
        if maintainer_id:
            send_alert(telegram_token, maintainer_id, shutdown_msg)


@cli.command('check-tokens', context_settings={'show_default': True})
@click.option('--config',          default=DEFAULT_CONFIG,   help='Path to config.json')
@click.option('--cookies',         default=DEFAULT_COOKIES,  help='Cookie files directory')
@click.option('--test_username',   default='X',              help='Username to test with')
@click.option('--output_response', is_flag=True, default=False, help='Print full JSON response')
@click.option('--telegram_chat_id', default=None,            help='Telegram chat_id to send result to')
def check_tokens(config, cookies, test_username, output_response, telegram_chat_id):
    """Check whether all configured auth tokens are valid."""
    cfg         = _load_config(config)
    token_cfg   = _build_token_config(cfg)
    adv         = cfg.get('advanced', {})
    cookies_dir = _resolve_path(adv.get('cookies_dir'), cookies)

    watcher = TwitterWatcher(token_cfg['twitter_auth_username_list'], cookies_dir)
    result  = watcher.check_tokens(test_username, output_response)
    print(json.dumps(result, indent=4))

    if telegram_chat_id:
        TelegramNotifier.init(token_cfg['telegram_bot_token'], 'telegram')
        TelegramNotifier.send_message(
            TelegramMessage([int(telegram_chat_id)], json.dumps(result, indent=4)))


@cli.command('login', context_settings={'show_default': True})
@click.option('--cookies',           default=DEFAULT_COOKIES, help='Cookie files directory')
@click.option('--username',          required=True,           help='X.com username')
@click.option('--password',          required=True,           help='X.com password')
@click.option('--confirmation_code', default=None,            help='2FA / email confirmation code')
def generate_auth_cookie(cookies, username, password, confirmation_code):
    """Login to X.com and save the auth cookie to cookies/."""
    os.makedirs(cookies, exist_ok=True)
    client    = login(username=username, password=password, confirmation_code=confirmation_code)
    dump_path = os.path.join(cookies, '{}.json'.format(username))
    with open(dump_path, 'w') as f:
        json.dump(dict(client.cookies), f, indent=2)
    print('Cookie saved: {}'.format(dump_path))


if __name__ == '__main__':
    cli()
