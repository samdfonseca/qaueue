import asyncio
from datetime import datetime
from functools import partial
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
from faker import Faker, Generator
import pytest

QaueueCommandClient = typing.Callable[[str, typing.Any], typing.Awaitable[dict]]


def md5(s: str) -> str:
    return hashlib.md5(s.encode()).hexdigest()


def fake_pivotal_story():
    story_id = random.randrange(10 ** 8, 10 ** 9)
    return f'https://www.pivotaltracker.com/n/projects/1234567/stories/{str(story_id)}', story_id


def github_pr_url():
    pr_id = random.randrange(1, 100000)
    return f'https://github.com/testorg/testrepo/pull/{str(pr_id)}'


@pytest.fixture
def fake():
    return Faker()


def gen_story(project_id, story_id):
    fake = Faker()
    return {
        'accepted_at': fake.date_time_between(start_date='-2w', end_date='-1w'),
        'created_at': fake.date_time_between(start_date='-3w', end_date='-2w'),
        'current_state': 'accepted',
        'description': f'{fake.paragraph()}\n\n{github_pr_url()}',
        'kind': 'story',
        'labels': [],
        'name': f'test story: {fake.sentence()}',
        'owned_by_id': 1234567,
        'owner_ids': [1234567],
        'requested_by_id': 2345678,
        'story_type': 'bug',
        'updated_at': fake.date_time_between(start_date='-1w', end_date='now'),
        'project_id': project_id,
        'story_id': story_id,
        'url': f'https://www.pivotaltracker.com/story/show/{story_id}'
    }


@pytest.fixture(autouse=True)
def mock_get_story(monkeypatch):
    generated_stories = {}

    def _mock_get_story(project_id, story_id):
        project_id, story_id = int(project_id), int(story_id)
        key = (project_id, story_id)
        #  import pdb; pdb.set_trace()
        generated_stories[key] = generated_stories.get(key, gen_story(*key))
        return generated_stories[key]
    async def _mock_async_get_story(*args):
        return _mock_get_story(*args)

    monkeypatch.setattr(pivotal, '_get_story', _mock_async_get_story)
    return partial(_mock_get_story, 1234567)


@pytest.fixture
def mock_add_label_to_story(monkeypatch, fake: Generator):
    fake_labels = []

    def on_add_label_to_story():
        label = {
            'created_at': fake.date_time_between(start_date='-3w', end_date='-2w'),
            'id': random.randrange(1000, 10000),
            'kind': 'label',
            'project_id': 1234567,
            'updated_at': fake.date_time_between(start_date='-1w', end_date='now')
        }
        fake_labels.append(label)
        return label

    async def _mock_add_label_to_story(story_ref, label):
        return {**on_add_label_to_story(), **{
            'name': label,
        }}

    monkeypatch.setattr(pivotal, 'add_label_to_story', _mock_add_label_to_story)
    return fake_labels


@pytest.fixture
def qaueue_command(qaueue_client: AioTestClient) -> QaueueCommandClient:
    headers = {
        'content-type': 'application/x-www-form-urlencoded; charset=utf-8',
    }

    async def func(command: str, channel_name: str = None, expect_error: bool = False):
        channel_name = channel_name or 'qa-talk'
        data = {
            'channel_name': channel_name,
            'text': command,
        }
        resp = await qaueue_client.post('/qaueue', headers=headers, data=data)
        assert resp.status == 200
        resp_json = json.loads((await resp.text()))
        if 'attachments' in resp_json and expect_error == False:
            assert resp_json['attachments'][0]['color'] != colors.RED
        return resp_json

    return func


async def test_help(qaueue_command):
    resp_json = await qaueue_command('help')
    assert resp_json['response_type'] == 'ephemeral'
    assert resp_json['text'] == f'```{USAGE}```'


async def test_help_verbose(qaueue_command):
    resp_json = await qaueue_command('help -v')
    assert resp_json['response_type'] == 'in_channel'
    assert resp_json['text'] == f'```{USAGE}```'


async def test_help_leading_verbose(qaueue_command: QaueueCommandClient):
    resp_json = await qaueue_command('-v help')
    assert resp_json['response_type'] == 'in_channel'
    assert resp_json['text'] == f'```{USAGE}```'


async def test_list_no_queued_items(qaueue_app: web.Application, qaueue_command: QaueueCommandClient):
    redis_conn: Redis = qaueue_app['redis']
    await redis_conn.delete(QUEUE_KEY)
    resp_json = await qaueue_command('list')
    assert resp_json['response_type'] == 'ephemeral'
    assert resp_json['text'] == 'Queued Items'
    assert len(resp_json['attachments'])
    assert resp_json['attachments'][0]['text'] == 'No queued items'


async def test_add_item_no_q_flag_response_type_in_channel(qaueue_command: QaueueCommandClient,
                                                           mock_get_story: dict):
    url, story_id = fake_pivotal_story()
    resp_json = await qaueue_command(f'add {url}')
    assert resp_json['response_type'] == 'in_channel'


async def test_add_item_with_q_flag_response_type_ephemeral(qaueue_command: QaueueCommandClient,
                                                            mock_get_story):
    url, story_id = fake_pivotal_story()
    resp_json = await qaueue_command(f'add -q {url}')
    assert resp_json['response_type'] == 'ephemeral'


async def test_add_item_initial_status(qaueue_command: QaueueCommandClient, mock_get_story):
    url, story_id = fake_pivotal_story()
    resp_json = await qaueue_command(f'add {url}')
    item = await db.Item.get(item_url=url)
    assert item.status == statuses.INITIAL


async def test_add_item_color_green(qaueue_command: QaueueCommandClient, mock_get_story):
    url, story_id = fake_pivotal_story()
    resp_json = await qaueue_command(f'add {url}')
    assert resp_json['attachments'][0]['color'] == colors.GREEN


async def test_add_item_message_title_item_name(qaueue_command: QaueueCommandClient,
                                                mock_get_story: typing.Callable[[int], dict]):
    url, story_id = fake_pivotal_story()
    mock_story = mock_get_story(story_id)
    resp_json = await qaueue_command(f'add {url}')
    item = await db.Item.get(item_url=url)
    assert item.name == mock_story['name']
    assert resp_json['attachments'][0]['title'] == url


async def test_add_item_message_title_link_item_url(qaueue_command: QaueueCommandClient,
                                                    mock_get_story: typing.Callable[[int], dict]):
    url, story_id = fake_pivotal_story()
    resp_json = await qaueue_command(f'add {url}')
    item = await db.Item.get(item_url=url)
    assert item.url == url
    assert resp_json['attachments'][0]['title_link'] == url


async def test_add_existing_item_errors(qaueue_command: QaueueCommandClient,
                                        mock_get_story: typing.Callable[[int], dict]):
    url, story_id = fake_pivotal_story()
    mock_story = mock_get_story(story_id)
    item = await db.Item.create(url=url, name=mock_story['name'])
    resp_json = await qaueue_command(f'add {url}', expect_error=True)
    assert resp_json['attachments'][0]['title_link'] == url
    assert resp_json['attachments'][0]['title'] == url
    assert resp_json['attachments'][0]['fields'][0]['title'] == 'Error'


async def test_update_to_defined_status(qaueue_command: QaueueCommandClient, read_only_config: Config,
                                        mock_get_story: typing.Callable[[int], dict]):
    url, story_id = fake_pivotal_story()
    mock_story = mock_get_story(story_id)
    item = await db.Item.create(url=url, name=mock_story['name'])
    new_status = 'integration'
    resp_json = await qaueue_command(f'update 0 {new_status}')
    await item.reload()
    assert item.status == new_status
    assert resp_json['attachments'][0]['color'] == colors.GREEN


async def test_update_to_undefined_status(qaueue_command: QaueueCommandClient, read_only_config: Config,
                                          mock_get_story: typing.Callable[[int], dict]):
    url, story_id = fake_pivotal_story()
    mock_story = mock_get_story(story_id)
    item = await db.Item.create(url=url, name=mock_story['name'])
    new_status = 'undefined_status'
    resp_json = await qaueue_command(f'update 0 {new_status}')
    await item.reload()
    assert item.status == new_status
    assert resp_json['attachments'][0]['color'] == colors.GREEN


async def test_list_item_with_updated_defined_status(qaueue_command: QaueueCommandClient, read_only_config: Config,
                                                     mock_get_story: typing.Callable[[int], dict]):
    url, story_id = fake_pivotal_story()
    mock_story = mock_get_story(story_id)
    item = await db.Item.create(url=url, name=mock_story['name'])
    item.status = 'integration'
    await item.update()
    resp_json = await qaueue_command('list')
    assert resp_json['attachments'][0]['color'] == read_only_config.STATUS_COLORS[item.status]
    assert len(list(filter(lambda field: field['title'] == 'Status' and field['value'] == item.status,
                           resp_json['attachments'][0]['fields'])))


async def test_list_item_with_updated_undefined_status(qaueue_command: QaueueCommandClient, read_only_config: Config,
                                                       mock_get_story: typing.Callable[[int], dict]):
    url, story_id = fake_pivotal_story()
    mock_story = mock_get_story(story_id)
    item = await db.Item.create(url=url, name=mock_story['name'])
    item.status = 'undefined_status'
    await item.update()
    resp_json = await qaueue_command('list')
    assert resp_json['attachments'][0]['color'] == read_only_config.STATUS_COLORS['*']
    assert len(list(filter(lambda field: field['title'] == 'Status' and field['value'] == item.status,
                           resp_json['attachments'][0]['fields'])))


async def test_reprioritize_middle_item_to_current(qaueue_command: QaueueCommandClient,
                                                 mock_get_story: typing.Callable[[int], dict]):
    mock_stories = [mock_get_story(fake_pivotal_story()[1]) for _ in range(0, 4)]
    items = [(await db.Item.create(url=story['url'], name=story['name'])) for story in mock_stories]
    resp_json = await qaueue_command(f'prioritize 2 2')
    for original_item_index, expected_priority in enumerate([0, 1, 2, 3]):
        item = await items[original_item_index].reload()
        actual_priority = await item.get_priority()
        assert actual_priority == expected_priority


async def test_reprioritize_middle_item_to_first(qaueue_command: QaueueCommandClient,
                                                 mock_get_story: typing.Callable[[int], dict]):
    mock_stories = [mock_get_story(fake_pivotal_story()[1]) for _ in range(0, 4)]
    items = [(await db.Item.create(url=story['url'], name=story['name'])) for story in mock_stories]
    resp_json = await qaueue_command(f'prioritize 2 0')
    for original_item_index, expected_priority in enumerate([1, 2, 0, 3]):
        item = await items[original_item_index].reload()
        actual_priority = await item.get_priority()
        assert actual_priority == expected_priority


async def test_reprioritize_middle_item_to_middle(qaueue_command: QaueueCommandClient,
                                                  mock_get_story: typing.Callable[[int], dict]):
    mock_stories = [mock_get_story(fake_pivotal_story()[1]) for _ in range(0, 4)]
    items = [(await db.Item.create(url=story['url'], name=story['name'])) for story in mock_stories]
    resp_json = await qaueue_command(f'prioritize 2 1')
    for original_item_index, expected_priority in enumerate([0, 2, 1, 3]):
        item = await items[original_item_index].reload()
        actual_priority = await item.get_priority()
        assert actual_priority == expected_priority


async def test_reprioritize_middle_item_to_last(qaueue_command: QaueueCommandClient,
                                                mock_get_story: typing.Callable[[int], dict]):
    mock_stories = [mock_get_story(fake_pivotal_story()[1]) for _ in range(0, 4)]
    items = [(await db.Item.create(url=story['url'], name=story['name'])) for story in mock_stories]
    resp_json = await qaueue_command(f'prioritize 2 3')
    for original_item_index, expected_priority in enumerate([0, 1, 3, 2]):
        item = await items[original_item_index].reload()
        actual_priority = await item.get_priority()
        assert actual_priority == expected_priority


async def test_reprioritize_first_item_to_first(qaueue_command: QaueueCommandClient,
                                                   mock_get_story: typing.Callable[[int], dict]):
    mock_stories = [mock_get_story(fake_pivotal_story()[1]) for _ in range(0, 4)]
    items = [(await db.Item.create(url=story['url'], name=story['name'])) for story in mock_stories]
    resp_json = await qaueue_command(f'prioritize 0 0')
    for original_item_index, expected_priority in enumerate([0, 1, 2, 3]):
        item = await items[original_item_index].reload()
        actual_priority = await item.get_priority()
        assert actual_priority == expected_priority


async def test_reprioritize_first_item_to_middle(qaueue_command: QaueueCommandClient,
                                                 mock_get_story: typing.Callable[[int], dict]):
    mock_stories = [mock_get_story(fake_pivotal_story()[1]) for _ in range(0, 4)]
    items = [(await db.Item.create(url=story['url'], name=story['name'])) for story in mock_stories]
    item_ids = [item.item_id for item in items]
    resp_json = await qaueue_command('prioritize 0 2')
    for original_item_id, expected_priority in enumerate([2, 0, 1, 3]):
        item = await items[original_item_id].reload()
        actual_priority = await item.get_priority()
        assert actual_priority == expected_priority


async def test_reprioritize_first_item_to_last(qaueue_command: QaueueCommandClient,
                                               mock_get_story: typing.Callable[[int], dict]):
    mock_stories = [mock_get_story(fake_pivotal_story()[1]) for _ in range(0, 4)]
    items = [(await db.Item.create(url=story['url'], name=story['name'])) for story in mock_stories]
    resp_json = await qaueue_command('prioritize 0 3')
    for original_item_id, expected_priority in enumerate([3, 0, 1, 2]):
        item = await items[original_item_id].reload()
        actual_priority = await item.get_priority()
        assert actual_priority == expected_priority


async def test_reprioritize_last_item_to_last(qaueue_command: QaueueCommandClient,
                                                mock_get_story: typing.Callable[[int], dict]):
    mock_stories = [mock_get_story(fake_pivotal_story()[1]) for _ in range(0, 4)]
    items = [(await db.Item.create(url=story['url'], name=story['name'])) for story in mock_stories]
    resp_json = await qaueue_command(f'prioritize 3 3')
    for original_item_index, expected_priority in enumerate([0, 1, 2, 3]):
        item = await items[original_item_index].reload()
        actual_priority = await item.get_priority()
        assert actual_priority == expected_priority


async def test_reprioritize_last_item_to_first(qaueue_command: QaueueCommandClient,
                                               mock_get_story: typing.Callable[[int], dict]):
    mock_stories = [mock_get_story(fake_pivotal_story()[1]) for _ in range(0, 4)]
    items = [(await db.Item.create(url=story['url'], name=story['name'])) for story in mock_stories]
    resp_json = await qaueue_command('prioritize 3 0')
    for original_item_id, expected_priority in enumerate([1, 2, 3, 0]):
        item = await items[original_item_id].reload()
        actual_priority = await item.get_priority()
        assert actual_priority == expected_priority


async def test_reprioritize_last_item_to_middle(qaueue_command: QaueueCommandClient,
                                                mock_get_story: typing.Callable[[int], dict]):
    mock_stories = [mock_get_story(fake_pivotal_story()[1]) for _ in range(0, 4)]
    items = [(await db.Item.create(url=story['url'], name=story['name'])) for story in mock_stories]
    resp_json = await qaueue_command('prioritize 3 1')
    for original_item_id, expected_priority in enumerate([0, 2, 3, 1]):
        item = await items[original_item_id].reload()
        actual_priority = await item.get_priority()
        assert actual_priority == expected_priority


async def test_update_item_status(qaueue_command: QaueueCommandClient, read_only_config: Config,
        mock_get_story: typing.Callable[[int], dict]):
    url, story_id = fake_pivotal_story()
    mock_story = mock_get_story(story_id)
    await qaueue_command(f'add {url}')
    resp_json = await qaueue_command(f'update 0 integration')
