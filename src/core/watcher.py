"""
TwitterWatcher — handles authenticated X.com API requests.

New features vs. original:
- Sign-out / auth-failure detection: if a cookie returns 401 or repeated
  auth errors, an alert callback is fired (used to notify Telegram).
- Consecutive-failure counter per token: a token is flagged as "dead"
  after DEAD_TOKEN_THRESHOLD consecutive failures.
- Structured logging per query attempt.
"""
import json
import logging
import os
import random
import time
from typing import Callable, List, Mapping, Union

import requests

from src.core.graphql import GraphqlAPI
from src.utils.parser import find_one

# Number of consecutive failures before a token is considered signed-out
DEAD_TOKEN_THRESHOLD = 3
RATE_LIMIT_FALLBACK_SECONDS = 60


class RateLimitError(RuntimeError):
    """Raised when every usable auth token is rate-limited for one API call."""

    def __init__(self, api_name: str, reset_at: int, usernames: list[str]):
        self.api_name = api_name
        self.reset_at = int(reset_at)
        self.usernames = tuple(usernames)
        super().__init__(
            '{} rate-limited until Unix timestamp {}.'.format(api_name, self.reset_at)
        )


def _read_rate_limit_reset_at(
    headers: Mapping[str, str],
    now: float | None = None,
) -> int:
    """Read X's reset timestamp, using a short fallback only if header is absent."""
    current = time.time() if now is None else float(now)
    raw = headers.get('x-rate-limit-reset')
    try:
        reset_at = int(float(raw)) if raw is not None else 0
    except (TypeError, ValueError):
        reset_at = 0
    if reset_at > 0:
        return reset_at
    return int(current + RATE_LIMIT_FALLBACK_SECONDS)


def _build_auth_headers(base_headers: dict, cookies: dict) -> dict:
    merged = base_headers | {
        'cookie': cookies and '; '.join(f'{k}={v}' for k, v in cookies.items()),
        'referer': 'https://twitter.com/',
        'x-csrf-token': cookies.get('ct0', ''),
        'x-guest-token': cookies.get('guest_token', ''),
        'x-twitter-auth-type': 'OAuth2Session' if cookies.get('auth_token') else '',
        'x-twitter-active-user': 'yes',
        'x-twitter-client-language': 'en',
    }
    return dict(sorted({k.lower(): v for k, v in merged.items()}.items()))


def _build_params(params: dict) -> dict:
    return {k: json.dumps(v) for k, v in params.items()}


class TwitterWatcher:
    """
    Wraps multiple auth cookies and round-robins them for API requests.

    Parameters
    ----------
    auth_username_list : list[str]
        Usernames whose cookie JSON files live in `cookies_dir`.
    cookies_dir : str
        Directory containing `<username>.json` cookie files.
    on_signout : callable, optional
        Called with (username: str) when a token is detected as signed-out.
    """

    def __init__(self,
                 auth_username_list: List[str],
                 cookies_dir: str,
                 on_signout: Callable[[str], None] | None = None):
        assert auth_username_list, 'At least one auth account is required.'
        self.logger = logging.getLogger('api')
        self.on_signout = on_signout

        self.auth_cookies: list[dict] = []
        self._fail_count: dict[str, int] = {}
        self._dead: set[str] = set()

        for username in auth_username_list:
            path = os.path.join(cookies_dir, '{}.json'.format(username))
            with open(path, 'r') as f:
                cookie = json.load(f)
                cookie['_username'] = username
                self.auth_cookies.append(cookie)
            self._fail_count[username] = 0

        self.token_number = len(self.auth_cookies)
        self.current_token_index = random.randrange(self.token_number)

    # ------------------------------------------------------------------
    # Core query
    # ------------------------------------------------------------------

    def query(
        self,
        api_name: str,
        params: dict,
        *,
        raise_rate_limit: bool = False,
    ) -> Union[dict, list, None]:
        url, method, headers, features = GraphqlAPI.get_api_data(api_name)
        built_params = _build_params({'variables': params, 'features': features})
        rate_limited: list[tuple[str, int]] = []

        for _ in range(self.token_number):
            self.current_token_index = (self.current_token_index + 1) % self.token_number
            cookie = self.auth_cookies[self.current_token_index]
            username = cookie['_username']

            if username in self._dead:
                continue

            auth_headers = _build_auth_headers(headers, cookie)
            try:
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=auth_headers,
                    params=built_params,
                    timeout=300,
                )
            except requests.exceptions.ConnectionError as e:
                self.logger.error('[{}] Connection error: {}'.format(username, e))
                self._record_failure(username)
                continue

            if resp.status_code == 401:
                self.logger.error('[{}] 401 Unauthorized — token signed out!'.format(username))
                self._handle_signout(username)
                continue

            if resp.status_code == 429:
                reset_at = _read_rate_limit_reset_at(resp.headers)
                remaining = max(0, reset_at - int(time.time()))
                rate_limited.append((username, reset_at))
                self.logger.warning(
                    '[{}] 429 Rate-limited; reset in {}s, trying next token.'.format(
                        username, remaining
                    )
                )
                continue

            if resp.status_code not in (200, 403, 404):
                self.logger.error('[{}] Unexpected HTTP {}: {}'.format(
                    username, resp.status_code, resp.text[:300]))
                self._record_failure(username)
                continue

            if not resp.text:
                self.logger.error('[{}] Empty response (HTTP {}).'.format(
                    username, resp.status_code))
                self._record_failure(username)
                continue

            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                self.logger.error('[{}] JSON decode failed: {}'.format(username, e))
                self._record_failure(username)
                continue

            if 'errors' in data:
                errs = data['errors']
                if any(e.get('code') == 32 for e in errs):
                    self.logger.error('[{}] Auth error (code 32) — signed out!'.format(username))
                    self._handle_signout(username)
                    continue
                self.logger.error('[{}] API errors: {}'.format(username, errs))
                self._record_failure(username)
                continue

            self._reset_failure(username)
            return data

        if rate_limited and raise_rate_limit:
            reset_at = min(item[1] for item in rate_limited)
            usernames = [item[0] for item in rate_limited]
            raise RateLimitError(api_name, reset_at, usernames)

        self.logger.error('All tokens exhausted for API: {}'.format(api_name))
        return None

    # ------------------------------------------------------------------
    # Failure / sign-out tracking
    # ------------------------------------------------------------------

    def _record_failure(self, username: str) -> None:
        self._fail_count[username] = self._fail_count.get(username, 0) + 1
        if self._fail_count[username] >= DEAD_TOKEN_THRESHOLD:
            self.logger.error('[{}] {} consecutive failures — treating as signed out.'.format(
                username, DEAD_TOKEN_THRESHOLD))
            self._handle_signout(username)

    def _reset_failure(self, username: str) -> None:
        self._fail_count[username] = 0

    def _handle_signout(self, username: str) -> None:
        self._dead.add(username)
        if self.on_signout:
            try:
                self.on_signout(username)
            except Exception as e:
                self.logger.error('on_signout callback failed: {}'.format(e))

    # ------------------------------------------------------------------
    # User lookup helpers
    # ------------------------------------------------------------------

    def get_user_by_username(self, username: str, extra_params: dict = {}) -> dict:
        params = {'screen_name': username, **extra_params}
        data = self.query('UserByScreenName', params)
        while data is None:
            time.sleep(60)
            data = self.query('UserByScreenName', params)
        return data

    def get_user_by_id(self, user_id: int, extra_params: dict = {}) -> dict:
        params = {'userId': user_id, **extra_params}
        data = self.query('UserByRestId', params)
        while data is None:
            time.sleep(60)
            data = self.query('UserByRestId', params)
        return data

    def get_id_by_username(self, username: str) -> str | None:
        data = self.get_user_by_username(username)
        return find_one(data, 'rest_id')

    # ------------------------------------------------------------------
    # Token health check
    # ------------------------------------------------------------------

    def check_tokens(self,
                     test_username: str = 'X',
                     output_response: bool = False) -> dict:
        result = {}
        for cookie in self.auth_cookies:
            uname = cookie['_username']
            try:
                url, method, headers, features = GraphqlAPI.get_api_data('UserByScreenName')
                params = _build_params({
                    'variables': {'screen_name': test_username},
                    'features': features,
                })
                auth_headers = _build_auth_headers(headers, cookie)
                resp = requests.request(
                    method=method,
                    url=url,
                    headers=auth_headers,
                    params=params,
                    timeout=300,
                )
                result[uname] = (resp.status_code == 200)
                if output_response:
                    try:
                        print(json.dumps(resp.json(), indent=2))
                    except json.JSONDecodeError:
                        print(resp.text)
            except requests.exceptions.ConnectionError as e:
                self.logger.error('[{}] check_tokens connection error: {}'.format(uname, e))
                result[uname] = False
        return result
