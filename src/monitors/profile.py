"""
Profile monitor — detects any change in a user's X.com profile.
Also serves as the scheduler entry-point that triggers sub-monitors.
"""
import time
from functools import cached_property
from typing import Union

from src.monitors.base      import TwitterMonitorBase, MonitorManager
from src.monitors.following  import FollowingMonitor
from src.monitors.like       import LikeMonitor
from src.monitors.tweet      import TweetMonitor
from src.utils.parser        import find_one, get_content
from src.utils.state         import StateManager

_CHANGE_TPL = '{} changed\nOld: {}\nNew: {}'
_SUB_MONITORS = [FollowingMonitor, LikeMonitor, TweetMonitor]


class _ProfileParser:
    def __init__(self, data: dict):
        self._data    = data
        self._content = get_content(find_one(data, 'user')) or {}
        self._core    = find_one(data, 'core') or {}

    @cached_property
    def name(self)           -> str:  return self._core.get('name', '')
    @cached_property
    def username(self)       -> str:  return self._core.get('screen_name', '')
    @cached_property
    def location(self)       -> str:
        loc = find_one(self._data, 'location') or {}
        return loc.get('location', '') if isinstance(loc, dict) else ''
    @cached_property
    def bio(self)            -> str:  return self._content.get('description', '')
    @cached_property
    def website(self)        -> str:
        return (self._content.get('entities', {})
                .get('url', {}).get('urls', [{}])[0].get('expanded_url', ''))
    @cached_property
    def followers_count(self)-> int:  return self._content.get('followers_count', 0)
    @cached_property
    def following_count(self)-> int:  return self._content.get('friends_count', 0)
    @cached_property
    def like_count(self)     -> int:  return self._content.get('favourites_count', 0)
    @cached_property
    def tweet_count(self)    -> int:  return self._content.get('statuses_count', 0)
    @cached_property
    def profile_image_url(self) -> str:
        av = find_one(self._data, 'avatar') or {}
        return av.get('image_url', '').replace('_normal', '')
    @cached_property
    def profile_banner_url(self) -> str:
        return self._content.get('profile_banner_url', '')
    @cached_property
    def pinned_tweet(self) -> str | None:
        ids = self._content.get('pinned_tweet_ids_str', [])
        if not ids:
            return None
        return ids[0] if isinstance(ids, list) else ids
    @cached_property
    def highlighted_tweet_count(self):
        return find_one(self._data, 'highlighted_tweets')


class _ElementBuffer:
    """Require `change_threshold` consecutive differing values before confirming a change."""

    def __init__(self, value, change_threshold: int = 2):
        self.element          = value
        self.change_threshold = change_threshold
        self._pending_count   = 0

    def __str__(self):  return str(self.element)
    def __repr__(self): return str(self.element)

    def push(self, value) -> Union[dict, None]:
        if value == self.element:
            self._pending_count = 0
            return None
        self._pending_count += 1
        if self._pending_count >= self.change_threshold:
            result              = {'old': self.element, 'new': value}
            self.element        = value
            self._pending_count = 0
            return result
        return None


class ProfileMonitor(TwitterMonitorBase):
    monitor_type = 'Profile'

    def __init__(self, username, title, token_config, user_config, cookies_dir):
        super().__init__(self.monitor_type, username, title, token_config, user_config, cookies_dir)
        self.original_username = username

        data = self._fetch_user()
        while not data:
            time.sleep(60)
            data = self._fetch_user()
        p = _ProfileParser(data)

        self._load_state(p)

        self._monitor_following_count = user_config.get('monitoring_following_count', False)
        self._monitor_like_count      = user_config.get('monitoring_like_count', False)
        self._monitor_tweet_count     = user_config.get('monitoring_tweet_count', False)

        self._sub_up_to_date = {m.monitor_type: True for m in _SUB_MONITORS}
        self.logger.info('ProfileMonitor ready for @{}.'.format(username))

    def _load_state(self, p: _ProfileParser):
        state = StateManager.get(self.monitor_type, self.original_username, 'buffers')
        if state is None:
            self.name          = _ElementBuffer(p.name)
            self.username_buf  = _ElementBuffer(p.username)
            self.location      = _ElementBuffer(p.location)
            self.bio           = _ElementBuffer(p.bio)
            self.website       = _ElementBuffer(p.website)
            self.followers     = _ElementBuffer(p.followers_count)
            self.following     = _ElementBuffer(p.following_count)
            self.like_count    = _ElementBuffer(p.like_count)
            self.tweet_count   = _ElementBuffer(p.tweet_count, change_threshold=1)
            self.avatar        = _ElementBuffer(p.profile_image_url)
            self.banner        = _ElementBuffer(p.profile_banner_url)
            self.pinned        = _ElementBuffer(p.pinned_tweet)
            self.highlighted   = _ElementBuffer(p.highlighted_tweet_count)
            self._save_state()
            return

        def _restore(key, current_val, threshold=2):
            s = state.get(key, {})
            buf = _ElementBuffer(s.get('element', current_val), change_threshold=threshold)
            buf._pending_count = s.get('pending_count', 0)
            return buf

        self.name          = _restore('name', p.name)
        self.username_buf  = _restore('username', p.username)
        self.location      = _restore('location', p.location)
        self.bio           = _restore('bio', p.bio)
        self.website       = _restore('website', p.website)
        self.followers     = _restore('followers', p.followers_count)
        self.following     = _restore('following', p.following_count)
        self.like_count    = _restore('like_count', p.like_count)
        self.tweet_count   = _restore('tweet_count', p.tweet_count, 1)
        self.avatar        = _restore('avatar', p.profile_image_url)
        self.banner        = _restore('banner', p.profile_banner_url)
        self.pinned        = _restore('pinned', p.pinned_tweet)
        self.highlighted   = _restore('highlighted', p.highlighted_tweet_count)

    def _save_state(self):
        state = {
            'name':        {'element': self.name.element,        'pending_count': self.name._pending_count},
            'username':    {'element': self.username_buf.element,'pending_count': self.username_buf._pending_count},
            'location':    {'element': self.location.element,    'pending_count': self.location._pending_count},
            'bio':         {'element': self.bio.element,         'pending_count': self.bio._pending_count},
            'website':     {'element': self.website.element,     'pending_count': self.website._pending_count},
            'followers':   {'element': self.followers.element,   'pending_count': self.followers._pending_count},
            'following':   {'element': self.following.element,   'pending_count': self.following._pending_count},
            'like_count':  {'element': self.like_count.element,  'pending_count': self.like_count._pending_count},
            'tweet_count': {'element': self.tweet_count.element, 'pending_count': self.tweet_count._pending_count},
            'avatar':      {'element': self.avatar.element,      'pending_count': self.avatar._pending_count},
            'banner':      {'element': self.banner.element,      'pending_count': self.banner._pending_count},
            'pinned':      {'element': self.pinned.element,      'pending_count': self.pinned._pending_count},
            'highlighted': {'element': self.highlighted.element, 'pending_count': self.highlighted._pending_count},
        }
        StateManager.set(self.monitor_type, self.original_username, 'buffers', state)
        StateManager.save()

    # ------------------------------------------------------------------

    def _fetch_user(self) -> Union[dict, None]:
        resp = self.twitter_watcher.query('UserByScreenName',
                                          {'screen_name': self.original_username})
        return resp if find_one(resp, 'user') else None

    def _check_and_notify(self, data: dict):
        p = _ProfileParser(data)

        def _notify(label, buf, value, photos=None):
            r = buf.push(value)
            if r:
                self.send_message(_CHANGE_TPL.format(label, r['old'], r['new']),
                                  photo_url_list=photos)
            return r

        _notify('Name',     self.name,     p.name)
        _notify('Username', self.username_buf, p.username)
        _notify('Location', self.location, p.location)
        _notify('Bio',      self.bio,      p.bio)
        _notify('Website',  self.website,  p.website)

        self.followers.push(p.followers_count)   # tracked but not alerted

        r = self.following.push(p.following_count)
        if r:
            if self._monitor_following_count:
                self.send_message(_CHANGE_TPL.format('Following count', r['old'], r['new']))
            self._sub_up_to_date[FollowingMonitor.monitor_type] = False

        r = self.like_count.push(p.like_count)
        if r:
            if self._monitor_like_count:
                self.send_message(_CHANGE_TPL.format('Like count', r['old'], r['new']))
            if r['new'] > r['old']:
                self._sub_up_to_date[LikeMonitor.monitor_type] = False

        r = self.tweet_count.push(p.tweet_count)
        if r:
            if self._monitor_tweet_count:
                self.send_message(_CHANGE_TPL.format('Tweet count', r['old'], r['new']))
            if r['new'] > r['old']:
                self._sub_up_to_date[TweetMonitor.monitor_type] = False

        _notify('Profile image',  self.avatar,   p.profile_image_url,
                photos=[p.profile_image_url] if p.profile_image_url else None)
        _notify('Profile banner', self.banner,   p.profile_banner_url,
                photos=[p.profile_banner_url] if p.profile_banner_url else None)
        _notify('Pinned tweet',   self.pinned,   p.pinned_tweet)
        _notify('Highlighted',    self.highlighted, p.highlighted_tweet_count)

    def _run_sub_monitors(self):
        for sub_cls in _SUB_MONITORS:
            st   = sub_cls.monitor_type
            inst = MonitorManager.get(st, self.title)
            if not inst:
                continue
            if not self._sub_up_to_date[st]:
                self._sub_up_to_date[st] = MonitorManager.call(st, self.title)
            else:
                inst.update_last_watch_time()

    def watch(self) -> bool:
        data = self._fetch_user()
        if not data:
            return False
        self._check_and_notify(data)
        self._save_state()
        self._run_sub_monitors()
        self.update_last_watch_time()
        return True

    def status(self) -> str:
        return 'last_watch={}, username={}'.format(
            self.get_last_watch_time(), self.username_buf.element)
