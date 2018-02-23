import json
import os
import typing
import warnings

from .colors import colors

import dotenv
import redis
from redis import Redis

warnings.simplefilter('ignore', UserWarning)


class Config(object):
    REDIS_ADDRESS = os.environ.get('REDIS_ADDRESS', 'redis://localhost')
    REDIS_DB = int(os.environ.get('REDIS_DB', 1))
    SLACK_VERIFICATION_TOKEN = os.environ.get('SLACK_VERIFICATION_TOKEN')
    ENABLED_CHANNEL_COMMANDS = {
            'qa-talk': '*',
            '*': ['help', 'list'],
            }
    STATUS_COLORS = {
            'integration': colors.ORANGE,
            'staging': colors.YELLOW,
            'released': colors.GREEN,
            'queued': colors.BLUE,
            '*': colors.BLUE,
            }
    PIVOTAL_API_TOKEN = os.environ.get('PIVOTAL_API_TOKEN')
    PIVOTAL_PROJECT_IDS = os.environ.get('PIVOTAL_PROJECT_IDS')
    GITHUB_ACCESS_TOKEN = os.environ.get('GITHUB_ACCESS_TOKEN')

    def __init__(self, redis_conn: Redis = None, read_only: bool = True):
        if redis_conn is None:
            redis_address = object.__getattribute__(self, 'REDIS_ADDRESS')
            redis_db = object.__getattribute__(self, 'REDIS_DB')
            redis_conn = redis.from_url(redis_address, redis_db, encoding='utf-8')
        object.__setattr__(self, 'redis_conn', redis_conn)
        if read_only:
            return
        cls = object.__getattribute__(self, '__class__')
        attrs = filter(lambda attr: not callable(getattr(cls, attr)) and not attr.startswith('_'), dir(cls))
        for attr in attrs:
            val = os.environ.get(attr, dotenv.get_key('.env', attr)) or object.__getattribute__(self, attr)
            if isinstance(val, (list, dict)):
                val = json.dumps(val)
            redis_conn.hset('CONFIG', attr, val)

    def channel_command_enabled(self, channel: str, command: str) -> bool:
        enabled_channel_commands = self.ENABLED_CHANNEL_COMMANDS.get(channel,
                self.ENABLED_CHANNEL_COMMANDS.get('*'))
        return (enabled_channel_commands == '*' or command in enabled_channel_commands)

    def get_channels_command_enabled(self, command: str) -> typing.List[str]:
        return [k for k, v in self.ENABLED_CHANNEL_COMMANDS.items() if (command in v or v == '*')]

    def get_status_color(self, status: str) -> str:
        return self.STATUS_COLORS.get(status, self.STATUS_COLORS['*'])

    def __getattribute__(self, item):
        redis_address = object.__getattribute__(self, 'REDIS_ADDRESS')
        redis_db = object.__getattribute__(self, 'REDIS_DB')
        redis_conn: Redis = object.__getattribute__(self, 'redis_conn') or redis.from_url(redis_address, redis_db,
                                                                                          encoding='utf-8')
        res = redis_conn.hget('CONFIG', item)
        if res is None:
            res = os.environ.get(item, dotenv.get_key('.env', item))
            if res is not None:
                return json.loads(res)
            return object.__getattribute__(self, item)
        try:
            return json.loads(res.decode())
        except json.JSONDecodeError:
            return res.decode()
