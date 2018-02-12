import asyncio
import hashlib
import json
import re
import typing

from .colors import colors
from .config import Config
from . import pivotal
from . import github

from aiohttp import web
import aioredis
from aioredis import RedisConnection
import docopt


QUEUE_KEY = 'qaueue_Q'
URL_FIELD = 'url'

USAGE = '''
QAueue: /qaueue manages the items in the QA pipeline

Usage:
    /qaueue add <item>...
    /qaueue [-v] help [<help_command>]
    /qaueue [-v] list
    /qaueue prioritize <prioritize_item_id> <priority_index>
    /qaueue remove <remove_item_id>...
    /qaueue update <update_item_id> <status>

Options:
    -v --verbose    Make the output of the command visible to the channel
'''


class AddItemResult(object):
    def __init__(self,
            item: str,
            item_id: str,
            priority_index: int,
            name: typing.Optional[str] = None,
            err: typing.Optional[str] = None):
        self.item = item
        self.item_id = item_id
        self.priority_index = priority_index
        self.name = name
        self.err = err


class RemoveItemResult(object):
    def __init__(self,
            item: str,
            item_id: str,
            name: typing.Optional[str] = None,
            err: typing.Optional[str] = None):
        self.item = item
        self.item_id = item_id
        self.name = name
        self.err = err


class fields:
    STATE = 'state'
    VALUE = 'value'
    TYPE = 'type'
    NAME = 'name'
    URL = 'url'


class states:
    INITIAL = 'queued'
    COMPLETED = 'released'


class item_types:
    PIVOTAL_STORY = 'pivotal_story'
    GITHUB_PUlL_REQUEST = 'github_pr'
    OTHER = 'other'


def parse_args(args: typing.List[str], usage: str = None) -> dict:
    usage = usage or USAGE
    return docopt.docopt(usage, argv=args)


def json_resp(body) -> web.Response:
    return web.Response(body=json.dumps(body), content_type='application/json')


def md5(val: str) -> str:
    m = hashlib.md5()
    m.update(val.encode())
    return m.hexdigest()


def attachment(opts) -> dict:
    defaults = {
            'color': colors.BLUE,
            }
    defaults.update(opts)
    return defaults


async def usage_help(args: dict) -> web.Response:
    '''/qaueue help [<help_command>]: displays this help message'''
    COMMAND_FUNC_MAP = {
            'add': add_items,
            'help': usage_help,
            'list': list_queue,
            'prioritize': prioritize_item,
            'remove': remove_items,
            'update': set_item_status,
            }
    response_type = ('in_channel' if args.get('--verbose') else 'ephemeral')
    command = args.get('<help_command>')
    if command is None:
        return json_resp({
            'response_type': response_type,
            'text': f'```{USAGE}```',
            })
    command_func = COMMAND_FUNC_MAP.get(command)
    if command_func is None:
        return json_resp({
            'response_type': response_type,
            'attachments': [
                attachment({
                    'color': colors.RED,
                    'text': f'`Unrecognized command: {command}`',
                    }),
                ],
            })
    return json_resp({
        'response_type': response_type,
        'text': f'`{command_func.__doc__}`',
        #  'attachments': [
        #      attachment({'text': f'`{command_func.__doc__}`'}),
        #      ],
        })
    return json_resp(body)


async def list_queue(conn: RedisConnection, args: dict, config: Config) -> web.Response:
    '''/qaueue list: lists the items in the pipeline and their current status'''
    is_verbose = args.get('--verbose', False)
    response_type = ('in_channel' if is_verbose else 'ephemeral')
    if args.get('help', False):
        return json_resp({
            'response_type': 'response_type',
            'attachments': [
                attachment({'text': list_queue.__doc__}),
                ],
            })
    queue_len = await conn.execute('llen', QUEUE_KEY)
    queued_item_ids = await conn.execute('lrange', QUEUE_KEY, 0, -1)
    attachments = []
    for i, item_id in enumerate(queued_item_ids):
        item_type = await conn.hget(item_id, fields.TYPE)
        if item_type == item_types.PIVOTAL_STORY or item_type == item_types.GITHUB_PUlL_REQUEST:
            item_url = await conn.hget(item_id, fields.URL)
            item_status = await conn.hget(item_id, fields.STATE)
            name = await conn.hget(item_id, fields.NAME)
            attachments.append(attachment({
                'fallback': f'{item_url} - {item_status}',
                'color': config.get_state_color(item_status),
                'text': name,
                'title': item_id,
                'title_link': item_url,
                'fields': [
                    {'title': 'Priority', 'value': str((i + 1)), 'short': True},
                    {'title': 'Status', 'value': item_status, 'short': True},
                    ]
                }))
        else:
            item_url = await conn.hget(item_id, fields.VALUE)
            item_status = await conn.hget(item_id, fields.STATE)
            attachments.append(attachment({
                'fallback': f'{item_url} - {item_status}',
                'color': config.get_state_color(item_status),
                'title': item_url,
                'title_link': item_url,
                'fields': [
                    {'title': 'Priority', 'value': str((i + 1)), 'short': True},
                    {'title': 'Status', 'value': item_status, 'short': True},
                    ]
                }))
    body = {
            'response_type': ('in_channel' if is_verbose else 'ephemeral'),
            'text': 'Queued Items',
            'attachments': (attachments or [attachment({'text': 'No queued items'})]),
            }
    return json_resp(body)


async def add_pivotal_story(conn: aioredis.Redis, story_project_ids: typing.Tuple[str, typing.Optional[str]],
        config: Config) -> AddItemResult:
    story_id = story_project_ids[0]
    project_id = None
    if len(story_project_ids) == 2:
        project_id = story_project_ids[1]
    if project_id is not None:
        story = await pivotal.get_story(story_id, project_id)
    else:
        story = await pivotal.get_story(story_id)
    story_url = story.get('url', f'https://www.pivotaltracker.com/story/show/{story_id}')
    item_id = f'PT/{story_id}'
    story_name = story.get('name')
    exists = await conn.exists(item_id)
    if exists == 1:
        return AddItemResult(story_url, item_id, None, story_name, 'Item already exists')
    tr = conn.multi_exec()
    futs = [
            tr.rpush(QUEUE_KEY, item_id),
            tr.hmset(item_id,
                fields.VALUE, story_url,
                fields.STATE, states.INITIAL,
                fields.TYPE, item_types.PIVOTAL_STORY,
                fields.URL, story_url,
                fields.NAME, story_name,
                ),
            tr.llen(QUEUE_KEY),
            ]
    res1 = await tr.execute()
    res2 = await asyncio.gather(*futs)
    assert res1 == res2
    return AddItemResult(story_url, item_id, res1[-1], story_name, None)


async def add_github_pr(conn: aioredis.Redis, pr_url: str, config: Config) -> AddItemResult:
    g = github.new_client(config.GITHUB_ACCESS_TOKEN)
    pull_request = await github.get_pull_request(g, pr_url)
    org_name, repo_name, pr_id = github.parse_pull_request_url(pr_url)
    item_id = f'GH/{repo_name}/{str(pr_id)}'
    pr_name = pull_request.title
    exists = await conn.exists(item_id)
    if exists == 1:
        return AddItemResult(pr_url, item_id, None, pr_name, 'Item already exists')
    tr = conn.multi_exec()
    futs = [
            tr.rpush(QUEUE_KEY, item_id),
            tr.hmset(item_id,
                fields.VALUE, pr_url,
                fields.STATE, states.INITIAL,
                fields.TYPE, item_types.GITHUB_PUlL_REQUEST,
                fields.URL, pr_url,
                fields.NAME, pr_name,
                ),
            tr.llen(QUEUE_KEY),
            ]
    res1 = await tr.execute()
    res2 = await asyncio.gather(*futs)
    assert res1 == res2
    return AddItemResult(pr_url, item_id, res1[-1], pr_name, None)


async def add_item(conn: aioredis.Redis, item: str, config: Config) -> AddItemResult:
    if pivotal.is_pivotal_story_url(item):
        if pivotal.is_full_story_url(item):
            project_id, story_id = pivotal.get_project_story_ids_from_full_url(item)
            return await add_pivotal_story(conn, (story_id, project_id), config)
        story_id = pivotal.get_story_id_from_url(item)
        return await add_pivotal_story(conn, (story_id, None), config)
    if github.is_pull_request_url(item):
        return await add_github_pr(conn, item, config)
    item_id = md5(item)
    exists = await conn.exists(item_id)
    if exists == 1:
        status = await conn.hget(item_id, fields.STATE)
        return AddItemResult(item, item_id, None, None, f'Item already exists')
    tr = conn.multi_exec()
    futs = [
            tr.rpush(QUEUE_KEY, item_id),
            tr.hmset(item_id, fields.VALUE, item, fields.STATE, states.INITIAL),
            tr.llen(QUEUE_KEY),
            ]
    res1 = await tr.execute()
    res2 = await asyncio.gather(*futs)
    assert res1 == res2
    return AddItemResult(item, item_id, res1[-1], None, None)


async def add_items(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue add <item>...: adds the item[s] to the pipeline'''
    res = [await add_item(conn, item, config) for item in args.get('<item>')]
    attachments = []
    for added_item in res:
        if added_item.err is not None:
            attachments.append(attachment({
                'fallback': f'{added_item.err} - {added_item.item}',
                'color': colors.RED,
                'text': (added_item.name or added_item.item),
                'title': added_item.item_id,
                'title_link': added_item.item,
                'fields': [
                    {'title': 'Error', 'value': added_item.err, 'short': True},
                    ]
                }))
        else:
            attachments.append(attachment({
                'fallback': f'Added to queue: {added_item.item}',
                'text': (added_item.name or added_item.item),
                'title': added_item.item_id,
                'title_link': added_item.item,
                'fields': [
                    {'title': 'Priority', 'value': added_item.priority_index, 'short': True},
                    ],
                }))
    body = {
            'response_type': 'in_channel',
            'text': 'Added Items',
            'attachments': attachments,
            }
    return json_resp(body)


async def remove_item(conn: aioredis.Redis, item_id: str) -> RemoveItemResult:
    exists = await conn.exists(item_id)
    if exists == 0:
        return RemoveItemResult(None, item_id, None, f'Item does not exist: {item_id}')
    tr: aioredis.commands.MultiExec = conn.multi_exec()
    status = await conn.hget(item_id, fields.STATE)
    name = await conn.hget(item_id, fields.NAME)
    item = await conn.hget(item_id, fields.VALUE)
    futs = []
    if status == states.INITIAL:
        futs.append(tr.lrem(QUEUE_KEY, 0, item_id))
    futs.append(tr.delete(item_id))
    res1 = await tr.execute()
    res2 = await asyncio.gather(*futs)
    assert res1 == res2
    return RemoveItemResult(item, item_id, name, None)



async def remove_items(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue remove <remove_item_id>...: removes an item from the pipeline and deletes the record of its status'''
    res = [await remove_item(conn, item) for item in args.get('<remove_item_id>', [])]
    if len(res) == 0:
        return json_resp({
            'attachments': [
                attachment({
                    'color': colors.RED,
                    'text': 'No Items Removed',
                    }),
                ],
            })
    attachments = []
    for removed_item in res:
        if removed_item.err is not None:
            attachments.append(attachment({
                'fallback': f'{removed_item.err} - {removed_item.item}',
                'color': colors.RED,
                'text': (removed_item.name or removed_item.item),
                'title': removed_item.item_id,
                'title_link': removed_item.item,
                'fields': [
                    {'title': 'Error', 'value': removed_item.err, 'short': True},
                    ]
                }))
        else:
            attachments.append(attachment({
                'fallback': f'Added to queue: {removed_item.item}',
                'text': (removed_item.name or removed_item.item),
                'title': removed_item.item_id,
                'title_link': removed_item.item,
                }))

    body = {
            'response_type': 'in_channel',
            'text': 'Removed Items',
            'attachments': attachments,
            }
    return json_resp(body)


async def get_item_status(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    is_verbose = args.get('verbose', False)
    attachments = []
    for item in args.get('item'):
        item_id = md5(item)
        exists = await conn.exists(item_id)
        if exists == 0:
            attachments.append(attachment({
                'pretext': f'Item Status: {item}',
                'color': colors.RED,
                'text': 'Does not exist',
                }))
            return json_resp({
                'response_type': ('in_channel' if is_verbose else 'ephemeral'),
                'text': f'Item Status: {item}',
                'attachments': [attachment({'text': 'Does not exist'})],
                })
        status = await conn.hget(item_id, fields.STATE)
    return json_resp({
        'response_type': ('in_channel' if is_verbose else 'ephemeral'),
        'text': f'Item Status: {item}',
        'attachments': [attachment({'text': status})],
        })


async def set_item_status(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue update <update_item_id> <status>: sets the items current status'''
    is_verbose = args.get('verbose', False)
    response_type = ('in_channel' if is_verbose else 'ephemeral')
    item_id = args.get('<update_item_id>')
    new_status = args.get('<status>')
    exists = await conn.exists(item_id)
    if exists == 0:
        return json_resp({
            'response_type': response_type,
            'text': f'Set Item Status: {item_id}',
            'attachments': [attachment({'text': 'Does not exist'})],
            })
    tr: aioredis.commands.MultiExec = conn.multi_exec()
    futs = []
    if new_status == states.COMPLETED:
        is_verbose = True
        futs.append(tr.lrem(QUEUE_KEY, 0, item_id))
    futs.append(tr.hset(item_id, fields.STATE, new_status))
    res1 = await tr.execute()
    res2 = await asyncio.gather(*futs)
    assert res1 == res2
    return json_resp({
        'response_type': response_type,
        'text': f'Set Item Status: {item_id}',
        'attachments': [attachment({'text': f'Set status: {new_status}'})],
        })


async def prioritize_item(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue prioritize <prioritize_item_id> <priority_index>: reorders an item in the pipeline (1 indexed)'''
    item_id = args.get('<prioritize_item_id>')
    new_pindex = int(args.get('<priority_index>'))
    if new_pindex <= 0:
        return json_resp({
            'response_type': 'in_channel',
            'text': 'Prioritize Item',
            'attachments': [attachment({'text': (f'Invalid priority index \'{new_pindex}\': '
                'must be greater than or equal to 0')})],
            })
    exists = await conn.exists(item_id)
    if exists == 0:
        return json_resp({
            'response_type': 'in_channel',
            'text': 'Prioritize Item',
            'attachments': [attachment({'text': f'Item does not exist: {item_id}'})],
            })
    status = await conn.hget(item_id, fields.STATE)
    if status != states.INITIAL:
        return json_resp({
            'response_type': 'in_channel',
            'text': 'Prioritize Item',
            'attachments': [attachment({'text': f'Item is not queued: {item_id}'})],
            })
    tr: aioredis.commands.MultiExec = conn.multi_exec()
    futs = []
    if new_pindex == 1:
        futs.append(tr.lrem(QUEUE_KEY, 0, item_id))
        futs.append(tr.lpush(QUEUE_KEY, item_id))
    if new_pindex >= 2:
        after_item_id = await conn.lindex(QUEUE_KEY, (new_pindex - 1))
        if after_item_id != item_id:
            futs.append(tr.lrem(QUEUE_KEY, 0, item_id))
            futs.append(tr.linsert(QUEUE_KEY, after_item_id, item_id))
    res1 = await tr.execute()
    res2 = await asyncio.gather(*futs)
    assert res1 == res2
    return json_resp({
        'response_type': 'in_channel',
        'text': 'Prioritize Item',
        'attachments': [attachment({'text': f'Set item to priority \'{new_pindex}\': {item_id}'})],
        })


def channel_command_not_enabled(channel: str, command: str, enabled_channels: typing.List[str] = None) -> web.Response:
    err_msg = f'Command is not enabled in #{channel}'
    if len(enabled_channels) > 0:
        err_msg += '. Use one of the following channels: ' + ', '.join([f'#{c}' for c in enabled_channels])
    return json_resp({
        'attachments': [
            attachment({
                'color': colors.RED,
                'text': err_msg,
                }),
            ],
        })


async def index(request: web.Request):
    conn = request.app['redis']
    config = request.app['config']
    data = await request.post()
    channel_name = data.get('channel_name')
    argv = data.get('text', 'help').split(' ')
    args = docopt.docopt(USAGE, argv=argv)
    args.setdefault('--verbose', False)
    if args.get('add'):
        if config.channel_command_enabled(channel_name, 'add'):
            return await add_items(conn, args, config)
        return channel_command_not_enabled(channel_name, 'add', config.get_channels_command_enabled('add'))
    if args.get('help'):
        if config.channel_command_enabled(channel_name, 'help'):
            return await usage_help(args)
        return channel_command_not_enabled(channel_name, 'help', config.get_channels_command_enabled('help'))
    if args.get('list'):
        if config.channel_command_enabled(channel_name, 'list'):
            return await list_queue(conn, args, config)
        return channel_command_not_enabled(channel_name, 'list', config.get_channels_command_enabled('list'))
    if args.get('prioritize'):
        if config.channel_command_enabled(channel_name, 'prioritize'):
            return await prioritize_item(conn, args, config)
        return channel_command_not_enabled(channel_name, 'prioritize',
                config.get_channels_command_enabled('prioritize'))
    if args.get('remove'):
        if config.channel_command_enabled(channel_name, 'remove'):
            return await remove_items(conn, args, config)
        return channel_command_not_enabled(channel_name, 'remove', config.get_channels_command_enabled('remove'))
    if args.get('update'):
        if config.channel_command_enabled(channel_name, 'update'):
            return await set_item_status(conn, args, config)
        return channel_command_not_enabled(channel_name, 'update', config.get_channels_command_enabled('update'))
    return await usage_help(args)
