import re
import typing

import github
from github.Repository import Repository
from github.PullRequest import PullRequest


GITHUB_PR_REGEX = re.compile(('https:\/\/github.com\/(?P<org_name>[a-zA-Z_-]+)'
                              '\/(?P<repo_name>[a-zA-Z_-]+)\/pull\/(?P<pr_id>[0-9]+)$'))


def is_pull_request_url(url: str) -> bool:
    return GITHUB_PR_REGEX.match(url) is not None


def parse_pull_request_url(url: str) -> typing.Tuple[str, str, int]:
    m = GITHUB_PR_REGEX.match(url).groupdict()
    pr_id = m.get('pr_id')
    if pr_id is not None:
        pr_id = int(pr_id)
    return m.get('org_name'), m.get('repo_name'), pr_id


def new_client(access_token: str) -> github.Github:
    return github.Github(access_token)


async def get_repo(g: github.Github, url: str) -> Repository:
    org_name, repo_name, pr_id = parse_pull_request_url(url)
    return g.get_repo(f'{org_name}/{repo_name}')


async def get_pull_request(g: github.Github, url: str) -> PullRequest:
    org_name, repo_name, pr_id = parse_pull_request_url(url)
    repo = await get_repo(g, url)
    return repo.get_pull(pr_id)
