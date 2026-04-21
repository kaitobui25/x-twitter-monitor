"""Following monitor — detects follow/unfollow changes."""
import time
from typing import Dict, Tuple, Union

from src.monitors.base import MonitorBase
from src.utils.parser  import find_all, find_one, get_cursor, get_content
from src.utils.state   import StateManager


class FollowingMonitor(MonitorBase):
    monitor_type = 'Following'

    def __init__(self, username, title, token_config, user_config, cookies_dir):
        super().__init__(self.monitor_type, username, title, token_config, user_config, cookies_dir)
        saved_following = StateManager.get(self.monitor_type, self.username, 'following_dict')
        if saved_following is not None:
            self.following_dict = saved_following
            self.logger.info('Loaded state: {} following'.format(len(self.following_dict)))
        else:
            self.following_dict = self._get_all_following(self.user_id)
            StateManager.set(self.monitor_type, self.username, 'following_dict', self.following_dict)

        self.logger.info('FollowingMonitor ready. {} following users.'.format(len(self.following_dict)))

    def _get_all_following(self, user_id: int) -> Dict[str, dict]:
        api_params    = {'userId': user_id, 'includePromotedContent': True, 'count': 1000}
        following_dict: Dict[str, dict] = {}

        while True:
            resp = self.twitter_watcher.query('Following', api_params)
            following_list = find_all(resp, 'user_results')

            # Retry if empty
            retries = 0
            while not following_list and not find_one(resp, 'result') and retries < 5:
                self.logger.warning('Empty following response, retrying...')
                time.sleep(10)
                resp           = self.twitter_watcher.query('Following', api_params)
                following_list = find_all(resp, 'user_results')
                retries       += 1

            for entry in following_list:
                uid = find_one(entry, 'rest_id')
                if uid:
                    following_dict[uid] = entry

            cursor = get_cursor(resp)
            if not cursor or cursor.startswith('-1|') or cursor.startswith('0|'):
                break
            api_params['cursor'] = cursor

        return following_dict

    def _user_card(self, user: dict) -> Tuple[str, Union[str, None]]:
        content = get_content(user)
        core    = find_one(user, 'core') or {}
        lines   = [
            'Name: {}'.format(core.get('name', '')),
            'Bio: {}'.format(content.get('description', '')),
            'Joined: {}'.format(core.get('created_at', '')),
            'Following: {}'.format(content.get('friends_count', '?')),
            'Followers: {}'.format(content.get('followers_count', '?')),
            'Tweets: {}'.format(content.get('statuses_count', '?')),
        ]
        website = content.get('entities', {}).get('url', {}).get('urls', [{}])[0].get('expanded_url', '')
        if website:
            lines.append('Website: {}'.format(website))
        avatar = find_one(user, 'avatar') or {}
        photo  = avatar.get('image_url', '').replace('_normal', '')
        return '\n'.join(lines), photo or None

    def _detect_and_notify(self, old: dict, new: dict) -> bool:
        if old.keys() == new.keys():
            return True
        max_changes = max(len(old) / 2, 10)
        unfollowed  = old.keys() - new.keys()
        followed    = new.keys() - old.keys()
        if len(unfollowed) > max_changes or len(followed) > max_changes:
            self.logger.warning('Too many changes ({}/{}), possible API glitch — skipping.'.format(
                len(unfollowed), len(followed)))
            return False
        for uid in unfollowed:
            screen = find_one(old[uid], 'screen_name') or uid
            card, photo = self._user_card(old[uid])
            self.send_message('Unfollowed: @{}\n{}'.format(screen, card),
                              photo_url_list=[photo] if photo else [])
        for uid in followed:
            screen = find_one(new[uid], 'screen_name') or uid
            card, photo = self._user_card(new[uid])
            self.send_message('Followed: @{}\n{}'.format(screen, card),
                              photo_url_list=[photo] if photo else [])
        return True

    def watch(self) -> bool:
        new_dict = self._get_all_following(self.user_id)
        if not self._detect_and_notify(self.following_dict, new_dict):
            return False
        self.following_dict = new_dict
        StateManager.set(self.monitor_type, self.username, 'following_dict', self.following_dict)
        StateManager.save()

        self.update_last_watch_time()
        return True

    def status(self) -> str:
        return 'last_watch={}, following={}'.format(self.get_last_watch_time(), len(self.following_dict))
