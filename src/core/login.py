# Reference: https://github.com/trevorhobenshield/twitter-api-client/blob/main/twitter/login.py
import sys

import requests
from requests import Session

from src.utils.parser import find_all
from src.core.graphql import GraphqlAPI


def _update_token(client: Session, key: str, url: str, **kwargs) -> Session:
    caller = sys._getframe(1).f_code.co_name
    try:
        client.headers.update({
            'x-guest-token':           client.cookies.get('guest_token', ''),
            'x-csrf-token':            client.cookies.get('ct0', ''),
            'x-twitter-auth-type':     'OAuth2Client' if client.cookies.get('auth_token') else '',
            'x-client-transaction-id': GraphqlAPI.get_client_transaction_id('POST', url),
        })
        r = client.post(url, **kwargs)
        print('[login] {} -> HTTP {}'.format(url.split('/')[-1], r.status_code))

        if not r.text:
            raise Exception('Empty response from {}'.format(url))

        info = r.json()

        for task in info.get('subtasks', []):
            if task.get('enter_text', {}).get('keyboard_type') == 'email':
                print('[login] Email challenge detected.')
                client.cookies.set('confirm_email', 'true')
            if task.get('subtask_id') == 'LoginAcid':
                if task['enter_text']['hint_text'].casefold() == 'confirmation code':
                    print('[login] Confirmation code challenge detected.')
                    client.cookies.set('confirmation_code', 'true')

        client.cookies.set(key, info[key])
    except KeyError as e:
        client.cookies.set('flow_errors', 'true')
        print('[login] Failed at step {}: {}'.format(caller, e))
    return client


def _init_guest_token(client: Session) -> Session:
    return _update_token(client, 'guest_token', 'https://api.x.com/1.1/guest/activate.json')


def _flow_start(client: Session) -> Session:
    return _update_token(client, 'flow_token', 'https://api.x.com/1.1/onboarding/task.json',
                         params={'flow_name': 'login'},
                         json={'input_flow_data': {'flow_context': {'debug_overrides': {},
                               'start_location': {'location': 'splash_screen'}}},
                               'subtask_versions': {}})


def _flow_instrumentation(client: Session) -> Session:
    return _update_token(client, 'flow_token', 'https://api.x.com/1.1/onboarding/task.json',
                         json={'flow_token': client.cookies.get('flow_token'),
                               'subtask_inputs': [{'subtask_id': 'LoginJsInstrumentationSubtask',
                                                   'js_instrumentation': {'response': '{}', 'link': 'next_link'}}]})


def _flow_username(client: Session) -> Session:
    return _update_token(client, 'flow_token', 'https://api.x.com/1.1/onboarding/task.json',
                         json={'flow_token': client.cookies.get('flow_token'),
                               'subtask_inputs': [{'subtask_id': 'LoginEnterUserIdentifierSSO',
                                                   'settings_list': {'setting_responses': [
                                                       {'key': 'user_identifier', 'response_data': {
                                                           'text_data': {'result': client.cookies.get('username')}}}],
                                                       'link': 'next_link'}}]})


def _flow_password(client: Session) -> Session:
    return _update_token(client, 'flow_token', 'https://api.x.com/1.1/onboarding/task.json',
                         json={'flow_token': client.cookies.get('flow_token'),
                               'subtask_inputs': [{'subtask_id': 'LoginEnterPassword',
                                                   'enter_password': {'password': client.cookies.get('password'),
                                                                      'link': 'next_link'}}]})


def _flow_finish(client: Session) -> Session:
    return _update_token(client, 'flow_token', 'https://api.x.com/1.1/onboarding/task.json',
                         json={'flow_token': client.cookies.get('flow_token'), 'subtask_inputs': []})


def _confirm_email(client: Session) -> Session:
    return _update_token(client, 'flow_token', 'https://api.x.com/1.1/onboarding/task.json',
                         json={'flow_token': client.cookies.get('flow_token'),
                               'subtask_inputs': [{'subtask_id': 'LoginAcid',
                                                   'enter_text': {'text': client.cookies.get('email'),
                                                                  'link': 'next_link'}}]})


def _solve_confirmation(client: Session, code: str) -> Session:
    return _update_token(client, 'flow_token', 'https://api.x.com/1.1/onboarding/task.json',
                         json={'flow_token': client.cookies.get('flow_token'),
                               'subtask_inputs': [{'subtask_id': 'LoginAcid',
                                                   'enter_text': {'text': code, 'link': 'next_link'}}]})


def login(username: str, password: str, confirmation_code: str = None) -> Session:
    """Authenticate with X.com and return a Session with valid cookies."""
    client = Session()
    client.cookies.set('username', username)
    client.cookies.set('password', password)
    client.cookies.set('guest_token', '')
    client.cookies.set('flow_token', '')
    client.headers.update(GraphqlAPI.headers | {
        'content-type':         'application/json',
        'x-twitter-active-user': 'yes',
        'x-twitter-client-language': 'en',
        'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                       'AppleWebKit/537.36 (KHTML, like Gecko) '
                       'Chrome/123.0.0.0 Safari/537.36'),
        'Accept':          '*/*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Origin':          'https://x.com',
        'Referer':         'https://x.com/',
    })

    client = _init_guest_token(client)
    for fn in [_flow_start, _flow_instrumentation, _flow_username, _flow_password]:
        client = fn(client)

    if client.cookies.get('confirm_email') == 'true':
        client = _confirm_email(client)
    if client.cookies.get('confirmation_code') == 'true':
        if not confirmation_code:
            raise Exception('[login] Confirmation code required — re-run with --confirmation_code')
        client = _solve_confirmation(client, confirmation_code)

    client = _flow_finish(client)
    if not client or client.cookies.get('flow_errors') == 'true':
        raise Exception('[login] {} login failed — check credentials.'.format(username))
    return client
