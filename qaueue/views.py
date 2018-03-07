import asyncio
from datetime import datetime
import hashlib
import json
import re
import typing

from qaueue.command import qaueue_command, Commands
from qaueue.config import Config
from qaueue.constants import colors, fields, item_types, statuses
from qaueue import db
from qaueue import github
from qaueue import pivotal
from qaueue import slack

from aiohttp import web
import aioredis
import docopt


QUEUE_KEY = 'qaueue_Q'

USAGE = '''
QAueue: /qaueue manages the items in the QA pipeline

Usage:
    /qaueue [-v] add <item>...
    /qaueue [-v] help [<help_command>]
    /qaueue [-v] list
    /qaueue [-v] prioritize <prioritize_item_id> <priority_index>
    /qaueue [-v] remove <remove_item_id>...
    /qaueue [-v] status <status_item_id>...
    /qaueue [-v] update <update_item_id> <status>

Options:
    -v    Make the output of the command visible to the channel
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


def json_resp(body) -> web.Response:
    return web.Response(body=json.dumps(body), content_type='application/json')


def md5(val: str) -> str:
    m = hashlib.md5()
    m.update(val.encode())
    return m.hexdigest()


def get_item_id_type(item_id: str) -> typing.Tuple[typing.Optional[str], typing.Optional[dict]]:
    if re.match('[0-9]+', item_id) is not None:
        return 'Index', {'item_index': int(item_id)}
    if github.is_pull_request_url(item_id) or pivotal.is_pivotal_story_url(item_id):
        return 'URL', {'item_url': item_id}
    if github.is_item_id(item_id) or pivotal.is_item_id(item_id):
        return 'ID', {'item_id': item_id}
    return None, None


@qaueue_command('help', default=True)
async def usage_help(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue [-v] help: displays this help message'''
    body = slack.message_body(args, **{
        'text': f'```{USAGE}```',
        })
    return json_resp(body)


@qaueue_command('list')
async def list_queue(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue list: lists the items in the pipeline and their current status'''
    if args.get('help', False):
        body = slack.message_body(args, **slack.help_func(list_queue))
        return json_resp(body)
    body = slack.message_body(args, **(await slack.list_items(await db.QAueueQueue.items(), config)))
    return json_resp(body)


async def _add_pivotal_story(conn: aioredis.Redis, story_url: str, config: Config) -> dict:
    item_id = pivotal.get_item_id_from_url(story_url)
    if await db.Item.exists(item_id):
        item = await db.Item.get(item_id)
        return slack.attachment({
            'fallback': f'Item already exists - {item.url}',
            'color': colors.RED,
            'text': item.name,
            'title': item.item_id,
            'title_link': item.url,
            'fields': [
                {'title': 'Error', 'value': 'Item already exists', 'short': True},
            ]
        })
    story_id = pivotal.get_story_id_from_url(story_url)
    project_id = None
    if pivotal.is_full_story_url(story_url):
        project_id, story_id = pivotal.get_project_story_ids_from_full_url(story_url)
    if project_id is not None:
        story = await pivotal.get_story_item(story_id, project_id)
    else:
        story = await pivotal.get_story_item(story_id, config.PIVOTAL_PROJECT_IDS)
    await story.update()
    priority_index = await db.QAueueQueue.add_to_queue(story)
    return slack.attachment({
        'fallback': f'Added to queue: {story.url}',
        'text': story.name,
        'title': story.item_id,
        'title_link': story.url,
        'fields': [
            slack.attachment_field('Priority', priority_index),
        ],
    })


async def _add_github_pr(conn: aioredis.Redis, pr_url: str, config: Config) -> dict:
    item_id = github.get_item_id_from_url(pr_url)
    if await db.Item.exists(item_id):
        item = await db.Item.get(item_id)
        return slack.attachment({
            'fallback': f'Item already exists - {item.url}',
            'color': colors.RED,
            'text': item.name,
            'title': item.item_id,
            'title_link': item.url,
            'fields': [
                {'title': 'Error', 'value': 'Item already exists', 'short': True},
            ]
        })
    g = github.new_client(config.GITHUB_ACCESS_TOKEN)
    pull_request = await github.get_pull_request_item(g, pr_url)
    await pull_request.update()
    priority_index = await db.QAueueQueue.add_to_queue(pull_request)
    return slack.attachment({
        'fallback': f'Added to queue: {pull_request.url}',
        'text': pull_request.name,
        'title': pull_request.item_id,
        'title_link': pull_request.url,
        'fields': [
            slack.attachment_field('Priority', priority_index),
        ],
    })


async def _add_item(conn: aioredis.Redis, item: str, config: Config) -> dict:
    if pivotal.is_pivotal_story_url(item):
        return await _add_pivotal_story(conn, item, config)
    if github.is_pull_request_url(item):
        return await _add_github_pr(conn, item, config)
    return slack.attachment({
        'fallback': 'Unsupported item type: Must be either a Pivotal story URL or GitHub PR URL',
        'color': colors.RED,
        'text': 'Must be either Pivotal story URL or GitHub PR URL',
        'fields': [
            slack.attachment_field('Error', 'Unsupported item type'),
        ]
    })


@qaueue_command('add')
async def add_items(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue add <item>...: adds the item[s] to the pipeline'''
    attachments = [await _add_item(conn, item, config) for item in args.get('<item>')]
    body = slack.message_body(args, **{
        'text': 'Added Items',
        'attachments': (attachments or [slack.attachment({'text': 'No added items'})]),
        })
    return json_resp(body)


async def _remove_item(conn: aioredis.Redis, item_id: str, config: Config) -> dict:
    item_id_type, get_item_kwargs = get_item_id_type(item_id)
    if get_item_kwargs is None:
        return slack.attachment({
            'fallback': f'Item not found: {item_id}',
            'color': colors.RED,
            'text': f'Item not found. Unrecognized item ID type: {item_id}',
        })
    item: db.Item = await db.Item.get(**get_item_kwargs)
    if item is None:
        return slack.attachment({
            'fallback': f'Item not found: {item_id}',
            'color': colors.RED,
            'text': 'Item not found',
            'fields': [
                slack.attachment_field(item_id_type, item_id),
            ],
        })
    await item.remove()
    return slack.attachment({
        'fallback': f'Item removed from queue: {item.item_id}',
        'color': colors.GREEN,
        'text': item.name,
        'title': item.item_id,
        'title_link': item.url,
    })


@qaueue_command('remove')
async def remove_items(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue remove <remove_item_id>...: removes an item from the pipeline and deletes the record of its status'''
    attachments = [await _remove_item(conn, item, config) for item in args.get('<remove_item_id>', [])]
    body = slack.message_body(args, **{
        'text': 'Removed Items',
        'attachments': (attachments or [slack.attachment({'text': 'No removed items'})]),
    })
    return json_resp(body)


async def _get_item_status(conn: aioredis.Redis, item_id: str, config: Config) -> dict:
    item_id_type, get_item_kwargs = get_item_id_type(item_id)
    if get_item_kwargs is None:
        return slack.attachment({
            'fallback': f'Item not found: {item_id}',
            'color': colors.RED,
            'text': f'Item not found. Unrecognized item ID type: {item_id}',
        })
    item: db.Item = await db.Item.get(**get_item_kwargs)
    if item is None:
        return slack.attachment({
            'fallback': f'Item not found: {item_id}',
            'color': colors.RED,
            'text': 'Item not found',
            'fields': [
                slack.attachment_field(item_id_type, item_id),
            ]
        })
    msg_fields = [
        slack.attachment_field('Status', item.status),
    ]
    if item.status == statuses.COMPLETED and item.released_at is not None:
        msg_fields.append(slack.attachment_field('Released At', item.released_at))
    return slack.attachment({
        'text': item.name,
        'title': item.item_id,
        'title_link': item.url,
        'fields': msg_fields,
    })


@qaueue_command('status')
async def get_item_statuses(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue [-v] status <status_item_id>...: gets the statuses for the given items'''
    attachments = [await _get_item_status(conn, item, config) for item in args.get('<status_item_id>', [])]
    body = slack.message_body(args, **{
        'text': 'Item Statuses',
        'attachments': (attachments or [slack.attachment({'text': 'No item statuses'})]),
    })
    return json_resp(body)


async def _complete_item(item: db.Item):
    if item.type == item_types.PIVOTAL_STORY:
        label = await pivotal.add_rc_label_to_story(item.url)


@qaueue_command('update')
async def set_item_status(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue update <update_item_id> <status>: sets the items current status'''
    item_id = args.get('<update_item_id>')
    new_status = args.get('<status>')
    item_id_type, get_item_kwargs = get_item_id_type(item_id)
    if get_item_kwargs is None:
        attachment = slack.attachment({
            'fallback': f'Item not found: {item_id}',
            'color': colors.RED,
            'text': f'Item not found. Unrecognized item ID type: {item_id}',
        })
        return json_resp(slack.message_body(args, **{
            'text': 'Set Item Status',
            'attachments': [
                attachment,
            ],
        }))
    item: db.Item = await db.Item.get(**get_item_kwargs)
    if item is None:
        return json_resp(slack.message_body(args, **{
            'text': 'Set Item Status',
            'attachments': [
                slack.attachment({
                    'fallback': f'Item not found: {item_id}',
                    'color': colors.RED,
                    'text': 'Item not found',
                    'fields': [
                        slack.attachment_field(item_id_type, item_id),
                    ],
                }),
            ],
        }))
    item.status = new_status
    if new_status == statuses.COMPLETED:
        await _complete_item(item)
    await item.update()
    return json_resp(slack.message_body(args, **{
        'text': 'Set Item Status',
        'attachments': [
            slack.attachment({
                'title': item.item_id,
                'title_link': item.url,
                'fields': [
                    slack.attachment_field('Status', item.status),
                ],
            }),
        ],
    }))


@qaueue_command('prioritize')
async def prioritize_item(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue prioritize <prioritize_item_id> <priority_index>: reorders an item in the pipeline (1 indexed)'''
    item_id = args.get('<prioritize_item_id>')
    new_pindex = int(args.get('<priority_index>'))
    item_id_type, get_item_kwargs = get_item_id_type(item_id)
    if get_item_kwargs is None:
        attachment = slack.attachment({
            'fallback': f'Item not found: {item_id}',
            'color': colors.RED,
            'text': f'Item not found. Unrecognized item ID type: {item_id}',
        })
        return json_resp(slack.message_body(args, **{
            'text': 'Prioritize Item',
            'attachments': [
                attachment,
            ],
        }))
    item: db.Item = await db.Item.get(**get_item_kwargs)
    if new_pindex < 0:
        return json_resp(slack.message_body(args, **{
            'text': 'Prioritize Item',
            'attachments': [
                slack.attachment({
                    'text': ((f'Invalid priority index \'{new_pindex}\': '
                              f'must be greater than or equal to 0')),
                }),
            ],
        }))
    if item is None:
        return json_resp(slack.message_body(args, **{
            'text': 'Prioritize Item',
            'attachments': [
                slack.attachment({
                    'fallback': f'Item not found: {item_id}',
                    'color': colors.RED,
                    'text': 'Item not found',
                    'fields': [
                        slack.attachment_field(item_id_type, item_id),
                    ],
                }),
            ],
        }))
    if item.status != statuses.INITIAL:
        return json_resp(slack.message_body(args, **{
            'text': 'Prioritize Item',
            'attachments': [
                slack.attachment({
                    'fallback': f'Item is not queued: {item.item_id}',
                    'color': colors.RED,
                    'text': 'Item is not queued',
                    'title': item.item_id,
                    'title_link': item.url,
                    'fields': [
                        slack.attachment_field('Status', item.status),
                    ]
                }),
            ],
        }))
    await item.set_priority(new_pindex)
    return json_resp(slack.message_body(args, **{
        'text': 'Prioritize Item',
        'attachments': [
            slack.attachment({
                'fallback': f'Set item to priority \'{new_pindex}\': {item_id}',
                'text': item.name,
                'title': item.item_id,
                'title_link': item.url,
                'fields': [
                    slack.attachment_field('Priority', str(new_pindex)),
                ],
            }),
        ],
    }))


def channel_command_not_enabled(args: dict, channel: str, command: str, enabled_channels: typing.List[str] = None) -> web.Response:
    err_msg = f'Command is not enabled in #{channel}'
    if len(enabled_channels) > 0:
        err_msg += '. Use one of the following channels: ' + ', '.join([f'#{c}' for c in enabled_channels])
    return json_resp(slack.message_body(args, **{
        'attachments': [
            slack.attachment({
                'color': colors.RED,
                'text': err_msg,
            }),
        ],
    }))


async def index(request: web.Request):
    conn = request.app['redis']
    config = request.app['config']
    data = await request.post()
    channel_name = data.get('channel_name')
    argv = data.get('text', 'help').split(' ')
    args = docopt.docopt(USAGE, argv=argv)
    args.setdefault('--verbose', False)
    commands = Commands(conn=conn, args=args, config=config)
    for cmd in commands:
        if args.get(cmd):
            func = commands.get(cmd)
            break
    else:
        cmd, func = commands.default()
    if config.channel_command_enabled(channel_name, cmd):
        return await func()
    return channel_command_not_enabled(args, channel_name, cmd, config.get_channels_command_enabled(cmd))

