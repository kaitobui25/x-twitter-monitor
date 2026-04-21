"""
GraphQL API — fetches and caches X.com API endpoint data.
Refreshed automatically every hour by the scheduler.
"""
import logging
import time

import bs4
import requests
from x_client_transaction import ClientTransaction
from x_client_transaction.utils import generate_headers, get_ondemand_file_url

from src.utils.parser import check_initialized


class GraphqlAPI:
    initialized = False
    logger = logging.getLogger('api')

    def __new__(cls):
        raise Exception('Do not instantiate GraphqlAPI!')

    # ------------------------------------------------------------------
    # Init & data update
    # ------------------------------------------------------------------

    @classmethod
    def init(cls) -> None:
        while not cls.update_api_data():
            cls.logger.warning('GraphQL API init failed, retrying in 10s...')
            time.sleep(10)
        cls.initialized = True
        cls.logger.info('GraphQL API initialized.')

    @classmethod
    def update_api_data(cls) -> bool:
        try:
            response = requests.get(
                'https://github.com/ionic-bond/TwitterInternalAPIDocument/raw/master/docs/json/API.json',
                timeout=300,
            )
        except Exception as e:
            cls.logger.error('Network error fetching API data: {}'.format(e))
            return False

        if response.status_code != 200:
            cls.logger.error('API data request failed: {} {}'.format(
                response.status_code, response.text[:200]))
            return False

        json_data = response.json()
        if not json_data.get('graphql'):
            cls.logger.error('Missing graphql section in API data.')
            return False
        if not json_data.get('header'):
            cls.logger.error('Missing header section in API data.')
            return False

        cls.graphql_api_data = json_data['graphql']
        cls.headers          = json_data['header']
        cls._init_client_transaction()
        cls.logger.info('GraphQL API data updated — {} endpoints.'.format(
            len(cls.graphql_api_data)))
        return True

    @classmethod
    def _init_client_transaction(cls) -> None:
        session         = requests.Session()
        session.headers = generate_headers()
        home_page       = session.get('https://x.com')
        home_html       = bs4.BeautifulSoup(home_page.content, 'html.parser')
        ondemand_url    = get_ondemand_file_url(response=home_html)
        ondemand_file   = session.get(ondemand_url)
        ondemand_html   = bs4.BeautifulSoup(ondemand_file.content, 'html.parser')
        try:
            cls.ct = ClientTransaction(home_page_response=home_html,
                                       ondemand_file_response=ondemand_html)
        except Exception:
            cls.ct = ClientTransaction(home_page_response=home_html,
                                       ondemand_file_response=ondemand_file.text)

    # ------------------------------------------------------------------
    # API lookup
    # ------------------------------------------------------------------

    @classmethod
    def get_client_transaction_id(cls, method: str, url: str) -> str:
        path = url.replace('https://x.com', '').replace('https://twitter.com', '')
        return cls.ct.generate_transaction_id(method=method, path=path)

    @classmethod
    @check_initialized
    def get_api_data(cls, api_name: str):
        if api_name not in cls.graphql_api_data:
            raise ValueError('Unknown API: {}'.format(api_name))
        api   = cls.graphql_api_data[api_name]
        hdrs  = cls.headers.copy()
        hdrs['x-client-transaction-id'] = cls.get_client_transaction_id(
            api['method'], api['url'])
        return api['url'], api['method'], hdrs, api['features']


# Auto-init on import (same behaviour as original)
GraphqlAPI.init()
