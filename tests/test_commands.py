import json

from qaueue.colors import colors
from qaueue.config import Config
from qaueue.routes import setup_routes
from qaueue.views import USAGE, QUEUE_KEY

from aiohttp import web
from aiohttp.test_utils import TestClient as AioTestClient
from aioredis import Redis
import pytest
import _pytest
from _pytest.config import Config as PytestConfig
from _pytest.fixtures import FixtureRequest


async def test_help(qaueue_client: AioTestClient):
    headers = {'content-type': 'application/x-www-form-urlencoded; charset=utf-8',
               }
    data = {'channel-name': 'qa-talk',
            'text': 'help',
            }
    resp: web.Response = await qaueue_client.post('/qaueue', headers=headers, data=data)
    assert resp.status == 200
    resp_json = json.loads(await resp.text())
    assert resp_json['response_type'] == 'ephemeral'
    assert resp_json['text'] == f'```{USAGE}```'


async def test_help_verbose(qaueue_client: AioTestClient):
    headers = {'content-type': 'application/x-www-form-urlencoded; charset=utf-8',
               }
    data = {'channel-name': 'qa-talk',
            'text': 'help -v',
            }
    resp: web.Response = await qaueue_client.post('/qaueue', headers=headers, data=data)
    assert resp.status == 200
    resp_json = json.loads(await resp.text())
    assert resp_json['response_type'] == 'in_channel'
    assert resp_json['text'] == f'```{USAGE}```'


async def test_help_leading_verbose(qaueue_client: AioTestClient):
    headers = {'content-type': 'application/x-www-form-urlencoded; charset=utf-8',
               }
    data = {'channel-name': 'qa-talk',
            'text': '-v help',
            }
    resp: web.Response = await qaueue_client.post('/qaueue', headers=headers, data=data)
    assert resp.status == 200
    resp_json = json.loads(await resp.text())
    assert resp_json['response_type'] == 'in_channel'
    assert resp_json['text'] == f'```{USAGE}```'


async def test_list_no_queued_items(aiohttp_client, qaueue_app: web.Application):
    redis_conn: Redis = qaueue_app['redis']
    await redis_conn.delete(QUEUE_KEY)
    qaueue_client = await aiohttp_client(qaueue_app)
    headers = {'content-type': 'application/x-www-form-urlencoded; charset=utf-8',
               }
    data = {'channel-name': 'qa-talk',
            'text': 'list',
            }
    resp: web.Response = await qaueue_client.post('/qaueue', headers=headers, data=data)
    assert resp.status == 200
    resp_json = json.loads(await resp.text())
    assert resp_json['response_type'] == 'ephemeral'
    assert resp_json['text'] == 'Queued Items'
    assert len(resp_json['attachments'])
    assert resp_json['attachments'][0]['text'] == 'No queued items'
