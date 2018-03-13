import typing

from qaueue import db
from qaueue.colors import colors
from qaueue.config import Config
from qaueue.constants import *

import aioredis
from aioredis import Redis


def message_body(args: dict = None, **kwargs) -> dict:
    defaults = {}
    if args.get('add', False):
        # Special case, `/qaueue add` has 'response_type' set to 'in_channel' by default
        # and 'ephemeral' only if the `-q` flag is used
        is_quiet = args.get('-q', False)
        if is_quiet:
            # `-q` flag is used, so set 'response_type' to 'ephemeral'
            defaults['response_type'] = 'ephemeral'
        else:
            # `-q` flag not used, so set 'response_type' to 'in_channel'
            defaults['response_type'] = 'in_channel'
    else:
        is_verbose = args.get('-v', False)
        defaults['response_type'] = 'in_channel' if is_verbose else 'ephemeral'
    defaults.update(kwargs)
    return defaults


def attachment(opts) -> dict:
    defaults = {
        'color': colors.BLUE,
    }
    defaults.update(opts)
    return defaults


def attachment_field(title: str, value: typing.Union[str, int], short: bool = True) -> dict:
    if isinstance(value, int):
        value = str(value)
    return dict(title=title, value=value, short=short)


def help_func(func: typing.Callable, config: Config = None):
    return {
        'attachments': [
            attachment({'text': func.__doc__}),
        ]
    }


async def list_item_attachment(item: db.Item, config: Config = None) -> dict:
    config = config or Config()
    item_attachment = attachment({
        'color': config.get_status_color(item.status),
        'fields': [
            attachment_field('Priority', str(await item.get_priority())),
            attachment_field('Status', item.status),
        ],
    })
    item_attachment.update({
        'fallback': f'{item.url} - {item.status}',
        'text': item.name,
        'title': item.url,
        'title_link': item.url,
    })
    return item_attachment


async def list_items(items: typing.List[db.Item], config: Config = None) -> dict:
    if len(items) == 0:
        return {
            'text': 'Queued Items',
            'attachments': [attachment({'text': 'No queued items'})],
        }
    return {
        'text': 'Queued Items',
        'attachments': [await render_item_as_attachment(item, config=config) for item in items],
    }


async def render_item_as_attachment(item: db.Item, color: str = None, config: Config = None) -> dict:
    opts = {
        'fallback': f'{item.url} - {item.name}',
        'text': item.name,
        'title': item.url,
        'title_link': item.url,
        'fields': [
            attachment_field('Priority', await item.get_priority()),
            attachment_field('Status', item.status),
        ],
    }
    if color is not None:
        opts['color'] = color
    if color is None and config is not None:
        opts['color'] = config.get_status_color(item.status)
    a = attachment(opts)
    if item.released_at is not None:
        a['fields'].append(attachment_field('Released At', item.released_at))
    return a
