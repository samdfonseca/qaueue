import re
import typing
from urllib.parse import urljoin

from .config import Config

import aiohttp


PIVOTAL_BASE_URL = 'https://www.pivotaltracker.com/services/v5'
PIVOTAL_SHORT_STORY_URL_REGEX = '^https:\/\/www\.pivotaltracker\.com\/story\/show\/(?P<story_id>[0-9]{9})$'
PIVOTAL_FULL_STORY_URL_REGEX = ('^https:\/\/www\.pivotaltracker\.com\/n\/'
                                'projects\/(?P<project_id>[0-9]{7})\/stories\/(?P<story_id>[0-9]{9})$')

PivotalId = typing.Union[str, int]


def is_short_story_url(url: str) -> bool:
    return re.match(PIVOTAL_SHORT_STORY_URL_REGEX, url) is not None


def is_full_story_url(url: str) -> bool:
    return re.match(PIVOTAL_FULL_STORY_URL_REGEX, url) is not None


def is_pivotal_story_url(url: str) -> bool:
    return (is_short_story_url(url) or is_full_story_url(url))



def get_story_id_from_short_url(url: str) -> str:
    m = re.match(PIVOTAL_SHORT_STORY_URL_REGEX, url)
    return m.groupdict().get('story_id')


def get_project_story_ids_from_full_url(url: str) -> typing.Tuple[str, str]:
    m = re.match(PIVOTAL_FULL_STORY_URL_REGEX, url)
    groups = m.groupdict()
    return groups.get('project_id'), groups.get('story_id')


def get_story_id_from_url(url: str) -> str:
    if is_full_story_url(url):
        pid, sid = get_project_story_ids_from_full_url(url)
    if is_short_story_url(url):
        sid = get_story_id_from_short_url(url)
    return sid


async def _get_story(project_id: PivotalId, story_id: PivotalId) -> dict:
    project_id = str(project_id)
    story_id = str(story_id)
    url = f'{PIVOTAL_BASE_URL}/projects/{project_id}/stories/{story_id}'
    headers = {
            'X-TrackerToken': Config.PIVOTAL_API_TOKEN,
            }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            if resp.status >= 300:
                return None
            return await resp.json()


async def get_story(story_id: PivotalId,
        possible_project_ids: typing.Optional[typing.Union[PivotalId, typing.List[PivotalId]]] = None) -> dict:
    possible_project_ids = possible_project_ids or Config.PIVOTAL_PROJECT_IDS
    if isinstance(possible_project_ids, str) or isinstance(possible_project_ids, int):
        possible_project_ids = [possible_project_ids]
    for project_id in possible_project_ids:
        resp = await _get_story(project_id, story_id)
        if resp is not None:
            return resp

