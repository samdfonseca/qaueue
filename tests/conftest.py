import asyncio
import json

from qaueue.colors import colors
from qaueue.config import Config
from qaueue.routes import setup_routes

from aiohttp import web
from aiohttp.test_utils import TestClient
import fakeredis
import pytest
import _pytest
from _pytest.config import Config as PytestConfig
from _pytest.fixtures import FixtureRequest


@pytest.fixture
def config_loaded_redis(request: FixtureRequest):
    redis_conn = fakeredis.FakeRedis()
    redis_conn.hset('CONFIG', 'REDIS_ADDRESS', 'redis://localhost:6379')
    redis_conn.hset('CONFIG', 'REDIS_DB', 1)
    redis_conn.hset('CONFIG', 'ENABLED_CHANNEL_COMMANDS', json.dumps({
        'qa-talk': '*',
        '*': ['help', 'list'],
    }))
    redis_conn.hset('CONFIG', 'STATE_COLORS', json.dumps({
        'integration': colors.ORANGE,
        'staging': colors.YELLOW,
        'released': colors.GREEN,
        'queued': colors.BLUE,
        '*': colors.BLUE,
    }))
    redis_conn.hset('CONFIG', 'SLACK_VERIFICATION_TOKEN', 'slacktoken123')
    redis_conn.hset('CONFIG', 'PIVOTAL_API_TOKEN', 'pivotaltoken123')
    redis_conn.hset('CONFIG', 'PIVOTAL_PROJECT_IDS', json.dumps([
        1234567,
        2345678,
        3456789,
    ]))
    redis_conn.hset('CONFIG', 'GITHUB_ACCESS_TOKEN', 'githubtoken123')


class FakeAioRedis(fakeredis.FakeRedis):
    def __getattribute__(self, item):
        attr = object.__getattribute__(self, item)
        if not callable(attr):
            return attr
        async def wrapper(*args, **kwargs):
            return attr(*args, **kwargs)
        return wrapper


@pytest.fixture
def qaueue_app(request: FixtureRequest, config_loaded_redis: fakeredis.FakeRedis):
    app = web.Application()
    # noinspection PyTypeChecker
    config = Config(redis_conn=config_loaded_redis, read_only=True)
    app['config'] = config
    app['redis'] = FakeAioRedis()
    setup_routes(app)
    return app


@pytest.fixture
def qaueue_client(loop: asyncio.BaseEventLoop, aiohttp_client, qaueue_app: web.Application):
    return loop.run_until_complete(aiohttp_client(qaueue_app))
