from datetime import datetime
import re
import typing
from urllib.parse import urljoin

from qaueue.config import Config
from qaueue.constants import fields, item_types, statuses

import aiohttp


PIVOTAL_BASE_URL = 'https://www.pivotaltracker.com/services/v5'
PIVOTAL_SHORT_STORY_URL_REGEX = re.compile(('^https:\/\/www\.pivotaltracker\.com'
                                            '\/story\/show\/(?P<story_id>[0-9]{9})$'))
PIVOTAL_FULL_STORY_URL_REGEX = re.compile(('^https:\/\/www\.pivotaltracker\.com'
                                           '\/n\/projects\/(?P<project_id>[0-9]{7})'
                                           '\/stories\/(?P<story_id>[0-9]{9})$'))
PIVOTAL_ITEM_ID_REGEX = re.compile('^PT\/[0-9]{9}$')

PivotalId = typing.Union[str, int]


def story_url(project_id: PivotalId, story_id: PivotalId) -> str:
    return f'{PIVOTAL_BASE_URL}/projects/{project_id}/stories/{story_id}'


def is_short_story_url(url: str) -> bool:
    return PIVOTAL_SHORT_STORY_URL_REGEX.match(url) is not None


def is_full_story_url(url: str) -> bool:
    return PIVOTAL_FULL_STORY_URL_REGEX.match(url) is not None


def is_pivotal_story_url(url: str) -> bool:
    return (is_short_story_url(url) or is_full_story_url(url))



def get_story_id_from_short_url(url: str) -> str:
    m = PIVOTAL_SHORT_STORY_URL_REGEX.match(url)
    return m.groupdict().get('story_id')


def get_project_story_ids_from_full_url(url: str) -> typing.Tuple[str, str]:
    m = PIVOTAL_FULL_STORY_URL_REGEX.match(url)
    groups = m.groupdict()
    return groups.get('project_id'), groups.get('story_id')


def get_story_id_from_url(url: str) -> str:
    sid = None
    if is_full_story_url(url):
        _, sid = get_project_story_ids_from_full_url(url)
    if is_short_story_url(url):
        sid = get_story_id_from_short_url(url)
    return sid


def get_item_id_from_url(url: str) -> str:
    story_id = get_story_id_from_url(url)
    return f'PT/{story_id}'


def is_item_id(item_id: str) -> bool:
    return PIVOTAL_ITEM_ID_REGEX.match(item_id) is not None


async def _get_story(project_id: PivotalId, story_id: PivotalId) -> typing.Optional[dict]:
    project_id = str(project_id)
    story_id = str(story_id)
    url = f'{PIVOTAL_BASE_URL}/projects/{project_id}/stories/{story_id}'
    headers = {
        'X-TrackerToken': Config().PIVOTAL_API_TOKEN,
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            print(f'story {story_id} in project {project_id} return status code {resp.status}')
            if resp.status >= 300:
                return None
            return await resp.json()


async def get_story(story_id: PivotalId,
        possible_project_ids: typing.Optional[typing.Union[PivotalId, typing.List[PivotalId]]] = None) -> dict:
    possible_project_ids = possible_project_ids or Config().PIVOTAL_PROJECT_IDS
    if isinstance(possible_project_ids, str) or isinstance(possible_project_ids, int):
        possible_project_ids = [possible_project_ids]
    for project_id in possible_project_ids:
        resp = await _get_story(project_id, story_id)
        if resp is not None:
            return resp


async def get_story_item(story_id: PivotalId,
        possible_project_ids: typing.Optional[typing.Union[PivotalId, typing.List[PivotalId]]] = None):
    from qaueue import db
    item_id = f'PT/{story_id}'
    if await db.Item.exists(item_id):
        return await db.Item.get(item_id)
    resp = await get_story(story_id, possible_project_ids)
    status = statuses.INITIAL
    url = resp.get('url')
    type = item_types.PIVOTAL_STORY
    name = resp.get('name')
    return db.Item(item_id=item_id, status=status, type=type, name=name, url=url)


async def add_label_to_story(story_ref, label: str) -> dict:
    conf = Config()
    story_id = story_ref
    if is_pivotal_story_url(story_ref):
        story_id = get_story_id_from_url(story_ref)
    project_id = (await get_story(story_id, conf.PIVOTAL_PROJECT_IDS)).get('project_id')
    headers = {
        'X-TrackerToken': conf.PIVOTAL_API_TOKEN,
    }
    body = {'name': label}
    async with aiohttp.ClientSession() as session:
        async with session.get(f'{PIVOTAL_BASE_URL}/projects/{project_id}/labels', headers=headers) as resp:
            for existing_label in await resp.json():
                if existing_label.get('name') == label:
                    body.pop('name')
                    body['id'] = existing_label.get('id')
                    break
    async with aiohttp.ClientSession() as session:
        async with session.post(f'{PIVOTAL_BASE_URL}/projects/{project_id}/stories/{story_id}/labels',
                                headers=headers, json=body) as resp:
            assert resp.status == 200
            return await resp.json()


async def add_rc_label_to_story(story_ref, label: str = None) -> dict:
    label = 'rc-{}'.format(datetime.today().strftime('%Y-%m-%d'))
    return await add_label_to_story(story_ref, label)
