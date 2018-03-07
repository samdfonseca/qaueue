import re
import typing

import github
from github.Repository import Repository
from github.PullRequest import PullRequest

from qaueue.constants import item_types, statuses

GITHUB_PR_REGEX = re.compile(('https:\/\/github.com\/(?P<org_name>[a-zA-Z_-]+)'
                              '\/(?P<repo_name>[a-zA-Z_-]+)\/pull\/(?P<pr_id>[0-9]+)$'))
GITHUB_ITEM_ID_REGEX = re.compile('^GH\/.+\/[0-9]+$')


def is_pull_request_url(url: str) -> bool:
    return GITHUB_PR_REGEX.match(url) is not None


def parse_pull_request_url(url: str) -> typing.Tuple[str, str, int]:
    m = GITHUB_PR_REGEX.match(url).groupdict()
    pr_id = m.get('pr_id')
    if pr_id is not None:
        pr_id = int(pr_id)
    return m.get('org_name'), m.get('repo_name'), pr_id


def get_item_id_from_url(url: str) -> str:
    _, repo_name, pr_id = parse_pull_request_url(url)
    return f'GH/{repo_name}/{pr_id}'


def is_item_id(item_id: str) -> bool:
    return GITHUB_ITEM_ID_REGEX.match(item_id) is not None


def new_client(access_token: str) -> github.Github:
    return github.Github(access_token)


async def get_repo(g: github.Github, url: str) -> Repository:
    org_name, repo_name, pr_id = parse_pull_request_url(url)
    return g.get_repo(f'{org_name}/{repo_name}')


async def get_pull_request(g: github.Github, url: str) -> PullRequest:
    org_name, repo_name, pr_id = parse_pull_request_url(url)
    repo = await get_repo(g, url)
    return repo.get_pull(pr_id)


async def get_pull_request_item(g: github.Github, url: str):
    from qaueue import db
    org_name, repo_name, pr_id = parse_pull_request_url(url)
    item_id = f'GH/{repo_name}/{str(pr_id)}'
    if await db.Item.exists(item_id):
        return await db.Item.get(item_id)
    pr = await get_pull_request(g, url)
    status = statuses.INITIAL
    value = url
    type = item_types.GITHUB_PUlL_REQUEST
    name = pr.title
    return db.Item(item_id=item_id, value=value, status=status, type=type, name=name, url=url)
