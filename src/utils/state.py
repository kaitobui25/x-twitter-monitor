"""
State Manager — persists monitor state to a JSON file.
Useful for run-once (cron) mode so the bot remembers the last seen data.
"""
import json
import os

class StateManager:
    state_file = 'state.json'
    state_data = {}

    @classmethod
    def init(cls, state_dir: str):
        os.makedirs(state_dir, exist_ok=True)
        cls.state_file = os.path.join(state_dir, 'state.json')
        if os.path.exists(cls.state_file):
            try:
                with open(cls.state_file, 'r', encoding='utf-8') as f:
                    cls.state_data = json.load(f)
            except Exception:
                cls.state_data = {}

    @classmethod
    def get(cls, monitor_type: str, username: str, key: str, default=None):
        return cls.state_data.get('{}-{}'.format(monitor_type, username), {}).get(key, default)

    @classmethod
    def set(cls, monitor_type: str, username: str, key: str, value):
        k = '{}-{}'.format(monitor_type, username)
        if k not in cls.state_data:
            cls.state_data[k] = {}
        cls.state_data[k][key] = value

    @classmethod
    def save(cls):
        with open(cls.state_file, 'w', encoding='utf-8') as f:
            json.dump(cls.state_data, f, indent=2)
