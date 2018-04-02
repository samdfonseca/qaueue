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
    /qaueue [-q] add <item>
    /qaueue [-v] help [<help_command>]
    /qaueue [-v] list
    /qaueue [-v] prioritize <prioritize_item_id> <priority_index>
    /qaueue [-v] remove <remove_item_id>
    /qaueue [-v] status <status_item_id>
    /qaueue [-v] update <update_item_id> <status>

Options:
    -v    Make the output of the command visible to the channel
'''


def json_resp(body) -> web.Response:
    return web.Response(body=json.dumps(body), content_type='application/json')


def md5(val: str) -> str:
    m = hashlib.md5()
    m.update(val.encode())
    return m.hexdigest()


def get_item_id_type(item_id: str) -> typing.Tuple[typing.Optional[str], typing.Optional[dict]]:
    if re.match('^[0-9]{1,4}$', item_id) is not None:
        return 'Index', {'item_index': int(item_id)}
    if github.is_pull_request_url(item_id) or pivotal.is_pivotal_story_url(item_id):
        return 'URL', {'item_url': item_id}
    if re.match('^[a-z0-9]{32}$', item_id) is not None:
        return 'ID', {'item_id': item_id}
    return None, None


def item_error(msg: str, item: db.Item) -> dict:
    return slack.attachment({
        'fallback': f'{msg} - {item.url}',
        'color': colors.RED,
        'text': item.name,
        'title': item.url,
        'title_link': item.url,
        'fields': [
            {'title': 'Error', 'value': msg, 'short': False},
        ]
    })


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
        return item_error('Item already exists', item)
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
        'title': story.url,
        'title_link': story.url,
        'fields': [
            slack.attachment_field('Priority', priority_index),
        ],
    })


async def _add_github_pr(conn: aioredis.Redis, pr_url: str, config: Config) -> dict:
    item_id = github.get_item_id_from_url(pr_url)
    if await db.Item.exists(item_id):
        item = await db.Item.get(item_id)
        return item_error('Item already exists', item)
    g = github.new_client(config.GITHUB_ACCESS_TOKEN)
    pull_request = await github.get_pull_request_item(g, pr_url)
    await pull_request.update()
    priority_index = await db.QAueueQueue.add_to_queue(pull_request)
    return slack.attachment({
        'fallback': f'Added to queue: {pull_request.url}',
        'text': pull_request.name,
        'title': pull_request.url,
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
async def add_item(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    '''/qaueue add <item>: adds the item to the pipeline'''
    item_url = args.get('<item>')
    if item_url is None:
        return await usage_help(conn, args, config)
    if await db.Item.exists(item_url=item_url):
        item = await db.Item.get(item_url=item_url)
        return json_resp(slack.message_body(args, **{
            'text': 'Add Item',
            'attachments': [item_error('Item already exists', item)],
        }))
    item_name = None
    if github.is_pull_request_url(item_url):
        g = github.new_client(config.GITHUB_ACCESS_TOKEN)
        pr = await github.get_pull_request(g, item_url)
        item_name = pr.title
    if pivotal.is_pivotal_story_url(item_url):
        if pivotal.is_full_story_url(item_url):
            project_id, story_id = pivotal.get_project_story_ids_from_full_url(item_url)
            story = await pivotal.get_story(story_id, [project_id])
        else:
            story_id = pivotal.get_story_id_from_url(item_url)
            story = await pivotal.get_story(story_id, config.PIVOTAL_PROJECT_IDS)
        item_name = story.get('name')
    if item_name is None:
        class UnableToGetItemNameError(Exception):
            pass
        raise UnableToGetItemNameError(item_url)
    item = await db.Item.create(url=item_url, name=item_name)
    return json_resp(slack.message_body(args, **{
        'text': 'Add Item',
        'attachments': [await slack.render_item_as_attachment(item, color=colors.GREEN)],
    }))


@qaueue_command('remove')
async def remove_item(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    item_id = args.get('<remove_item_id>')
    if item_id is None:
        return await usage_help(conn, args, config)
    item_id_type, get_item_kwargs = get_item_id_type(item_id)
    if get_item_kwargs is None:
        attachment = slack.attachment({
            'fallback': f'Item not found: {item_id}',
            'color': colors.RED,
            'text': f'Item not found. Unrecognized item ID type: {item_id}',
        })
        return json_resp(slack.message_body(args, **{
            'text': 'Remove Item',
            'attachments': [attachment],
        }))
    item: db.Item = await db.Item.get(**get_item_kwargs)
    if item is None:
        attachment = slack.attachment({
            'fallback': f'Item not found: {item_id}',
            'color': colors.RED,
            'text': 'Item not found',
            'fields': [
                slack.attachment_field(item_id_type, item_id),
            ],
        })
        return json_resp(slack.message_body(args, **{
            'text': 'Remove Item',
            'attachments': [attachment],
        }))
    await item.remove()
    item_attachment = await slack.render_item_as_attachment(item, color=colors.GREEN)
    return json_resp(slack.message_body(args, **{
        'text': 'Remove Item',
        'attachments': [item_attachment],
    }))


@qaueue_command('status')
async def get_item_status(conn: aioredis.Redis, args: dict, config: Config) -> web.Response:
    item_id = args.get('<status_item_id>')
    if item_id is None:
        return await usage_help(conn, args, config)
    item_id_type, get_item_kwargs = get_item_id_type(item_id)
    if get_item_kwargs is None:
        attachment = slack.attachment({
            'fallback': f'Item not found: {item_id}',
            'color': colors.RED,
            'text': f'Item not found. Unrecognized item ID type: {item_id}',
            'fields': [
                slack.attachment_field(item_id_type, item_id),
            ],
        })
        return json_resp(slack.message_body(args, **{
            'text': 'Item Status',
            'attachments': [attachment],
        }))
    item: db.Item = await db.Item.get(**get_item_kwargs)
    if item is None:
        attachment = slack.attachment({
            'fallback': f'Item not found: {item_id}',
            'color': colors.RED,
            'text': 'Item not found',
            'fields': [
                slack.attachment_field(item_id_type, item_id),
            ]
        })
        return json_resp(slack.message_body(args, **{
            'text': 'Item Status',
            'attachments': [attachment],
        }))
    return json_resp(slack.message_body(args, **{
        'text': 'Item Status',
        'attachments': [await slack.render_item_as_attachment(item)],
    }))


async def _complete_item(item: db.Item) -> typing.Optional[Exception]:
    if item.type == item_types.PIVOTAL_STORY:
        try:
            label = await pivotal.add_rc_label_to_story(item.url)
        except Exception as e:
            return e
        finally:
            await db.QAueueQueue.remove_from_queue(item)


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
            'fields': [
                slack.attachment_field(item_id_type, item_id),
            ],
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
    error = None
    if new_status == statuses.COMPLETED:
        error = await _complete_item(item)
    await item.update()
    item = await db.Item.get(item_id=item.item_id)
    if error is not None:
        return json_resp(slack.message_body(args, **{
            'text': 'Set Item Status',
            'attachments': [
                slack.attachment({
                    'color': colors.RED,
                    'text': 'Unable to tag Pivotal story',
                    'fields': [
                        slack.attachment_field('Error', str(error), short=False),
                    ],
                }),
                await slack.render_item_as_attachment(item, color=colors.GREEN),
            ],
        }))
    return json_resp(slack.message_body(args, **{
        'text': 'Set Item Status',
        'attachments': [
            await slack.render_item_as_attachment(item, color=colors.GREEN),
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
                    'title': item.url,
                    'title_link': item.url,
                    'fields': [
                        slack.attachment_field('Status', item.status),
                    ]
                }),
            ],
        }))
    await item.set_priority(new_pindex)
    item = await db.Item.get(item_id=item.item_id)
    return json_resp(slack.message_body(args, **{
        'text': 'Prioritize Item',
        'attachments': [await slack.render_item_as_attachment(item, color=colors.GREEN)],
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

