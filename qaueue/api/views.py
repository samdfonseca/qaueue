from qaueue import db, github, pivotal
from qaueue.config import Config
from qaueue import views as base_views
from aiohttp import web


async def list_queue(request: web.Request) -> web.Response:
    return web.json_response(db.QAueueQueue.to_json())


async def _add_pivotal_story(story_url: str, config: Config) -> web.Response:
    item_id = pivotal.get_item_id_from_url(story_url)
    if await db.Item.exists(item_id):
        return web.HTTPConflict
    story_id = pivotal.get_story_id_from_url(story_url)
    project_id = None
    if pivotal.is_full_story_url(story_url):
        project_id, story_id = pivotal.get_project_story_ids_from_full_url(story_url)
    if project_id is not None:
        story = await pivotal.get_story_item(story_id, project_id)
    else:
        story = await pivotal.get_story_item(story_id, config.PIVOTAL_PROJECT_IDS)
    await story.update()
    return web.json_response(story.to_json())


async def _add_github_pr(pr_url: str, config: Config) -> web.Response:
    item_id = github.get_item_id_from_url(pr_url)
    if await db.Item.exists(item_id):
        return web.HTTPConflict('item already exists')
    g = github.new_client(config.GITHUB_ACCESS_TOKEN)
    pull_request = await github.get_pull_request_item(g, pr_url)
    await pull_request.update()
    return web.json_response(pull_request.to_json())


async def add_item(request: web.Request) -> web.Response:
    config = request.app['config']
    data = await request.json()
    item_url = data.get('item_url')
    if item_url is None:
        return web.HTTPBadRequest('item_url not found in request body')
    if pivotal.is_pivotal_story_url(item_url):
        return await _add_pivotal_story(item_url, config)
    if github.is_pull_request_url(item_url):
        return await _add_github_pr(item_url, config)
    return web.HTTPBadRequest('unsupported url')


async def remove_item(request: web.Request) -> web.Response:
    data = await request.json()
    item_id = data.get('item_id')
