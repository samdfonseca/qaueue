import asyncio
import json
import signal

from qaueue import db
from qaueue.constants import colors
from qaueue.config import Config
from qaueue.routes import setup_routes

from aiohttp import web
from aiohttp.test_utils import TestClient
import aioredis
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
    redis_conn.hset('CONFIG', 'STATUS_COLORS', json.dumps({
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


@pytest.fixture(autouse=True)
def fake_aioredis(request: FixtureRequest, loop: asyncio.BaseEventLoop):
    r: aioredis.Redis = loop.run_until_complete(aioredis.create_redis('redis://localhost:6379', db=2, encoding='utf-8'))
    loop.run_until_complete(r.flushdb())
    redis_objects = filter(lambda i: i != db.RedisObject and issubclass(i, db.RedisObject),
           filter(lambda i: type(i) == type,
                  map(lambda i: getattr(db, i), dir(db))))
    for redis_object in redis_objects:
        redis_object.register_db(r)
    yield r
    loop.run_until_complete(r.flushdb())
    r._pool_or_conn.close()
    loop.run_until_complete(r._pool_or_conn.wait_closed())


@pytest.fixture
def read_only_config(config_loaded_redis: fakeredis.FakeRedis):
    # noinspection PyTypeChecker
    return Config(redis_conn=config_loaded_redis, read_only=True)


@pytest.fixture
def qaueue_app(request: FixtureRequest, read_only_config: Config, fake_aioredis: aioredis.Redis,
        loop: asyncio.BaseEventLoop):
    app = web.Application()
    app['config'] = read_only_config
    app['redis'] = fake_aioredis
    setup_routes(app)
    return app


@pytest.fixture
def qaueue_client(loop: asyncio.BaseEventLoop, aiohttp_client, qaueue_app: web.Application):
    yield loop.run_until_complete(aiohttp_client(qaueue_app))
