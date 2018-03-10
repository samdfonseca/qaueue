import asyncio
import hashlib
import json
import random
import time
import typing

from qaueue import db, pivotal
from qaueue.constants import colors, fields, item_types, statuses
from qaueue.config import Config
from qaueue.views import USAGE, QUEUE_KEY

from aiohttp import web
from aiohttp.test_utils import TestClient as AioTestClient
from aioredis import Redis
import pytest


QaueueCommandClient = typing.Callable[[str, typing.Optional[str]], typing.Awaitable[web.Response]]


def md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def pivotal_story_url():
    story_id = random.randrange(10**8, 10**9)
    return f'https://www.pivotaltracker.com/story/show/{str(story_id)}'


def github_story_url():
    pr_id = random.randrange(1, 100000)
    return f'https://github.com/testorg/testrepo/pull/{str(pr_id)}'


@pytest.fixture(autouse=True)
def mock_pivotal(monkeypatch):
    async def mock_get_item(project_id, story_id):
        return {
            'accepted_at': '2018-01-12T21:10:40Z',
            'created_at': '2018-01-11T23:24:05Z',
            'current_state': 'accepted',
            'description': 'test story description\n\nlorem ipsum',
            'id': story_id,
            'kind': 'story',
            'labels': [],
            'name': 'test story name',
            'owned_by_id': 1234567,
            'owner_ids': [1234567],
            'project_id': project_id,
            'requested_by_id': 2345678,
            'story_type': 'bug',
            'updated_at': '2018-01-16T02:42:21Z',
            'url': f'https://www.pivotaltracker.com/story/show/{story_id}'
        }
    async def mock_add_label_to_story(story_ref, label):
        return {
            "created_at": "2018-03-06T12:00:00Z",
            "id": 5100,
            "kind": "label",
            "name": "test label",
            "project_id": 99,
            "updated_at": "2018-03-06T12:00:00Z"
        }
    monkeypatch.setattr(pivotal, '_get_story', mock_get_item)
    monkeypatch.setattr(pivotal, 'add_label_to_story', mock_get_item)


@pytest.fixture
def qaueue_command(qaueue_client: AioTestClient):
    headers = {
        'content-type': 'application/x-www-form-urlencoded; charset=utf-8',
    }
    async def func(command: str, channel_name: str = None):
        channel_name = channel_name or 'qa-talk'
        data = {
            'channel_name': channel_name,
            'text': command,
        }
        return await qaueue_client.post('/qaueue', headers=headers, data=data)
    return func


async def test_help(qaueue_command):
    resp: web.Response = await qaueue_command('help')
    assert resp.status == 200
    resp_json = json.loads(await resp.text())
    assert resp_json['response_type'] == 'ephemeral'
    assert resp_json['text'] == f'```{USAGE}```'


async def test_help_verbose(qaueue_command):
    resp: web.Response = await qaueue_command('help -v')
    assert resp.status == 200
    resp_json = json.loads(await resp.text())
    assert resp_json['response_type'] == 'in_channel'
    assert resp_json['text'] == f'```{USAGE}```'


async def test_help_leading_verbose(qaueue_command: QaueueCommandClient):
    resp = await qaueue_command('-v help')
    assert resp.status == 200
    resp_json = json.loads(await resp.text())
    assert resp_json['response_type'] == 'in_channel'
    assert resp_json['text'] == f'```{USAGE}```'


async def test_list_no_queued_items(qaueue_app: web.Application, qaueue_command: QaueueCommandClient):
    redis_conn: Redis = qaueue_app['redis']
    await redis_conn.delete(QUEUE_KEY)
    resp = await qaueue_command('list')
    assert resp.status == 200
    resp_json = json.loads(await resp.text())
    assert resp_json['response_type'] == 'ephemeral'
    assert resp_json['text'] == 'Queued Items'
    assert len(resp_json['attachments'])
    assert resp_json['attachments'][0]['text'] == 'No queued items'


async def test_add_item_no_q_flag_response_type_in_channel(qaueue_command: QaueueCommandClient):
    resp = await qaueue_command('add https://www.pivotaltracker.com/story/show/123456789', 'qa-talk')
    assert resp.status == 200
    resp_json = json.loads(await resp.text())
    assert resp_json['response_type'] == 'in_channel'


async def test_add_item_with_q_flag_response_type_ephemeral(qaueue_command: QaueueCommandClient):
    resp = await qaueue_command('add -q https://www.pivotaltracker.com/story/show/123456789')
    assert resp.status == 200
    resp_json = json.loads(await resp.text())
    assert resp_json['response_type'] == 'ephemeral'


async def test_add_item_initial_status(qaueue_command: QaueueCommandClient):
    url = 'https://www.pivotaltracker.com/story/show/123456789'
    resp = await qaueue_command('add https://www.pivotaltracker.com/story/show/123456789')
    assert resp.status == 200
    item = await db.Item.get(item_url=url)
    assert item.status == statuses.INITIAL


async def test_add_item_color_green(qaueue_command: QaueueCommandClient):
    url = pivotal_story_url()
    resp = await qaueue_command(f'add {url}')
    assert resp.status == 200
    resp_json = json.loads(await resp.text())
    assert resp_json['attachments'][0]['color'] == colors.GREEN
