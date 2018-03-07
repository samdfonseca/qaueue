import typing

from qaueue import db
from qaueue.colors import colors
from qaueue.config import Config
from qaueue.constants import *

import aioredis
from aioredis import Redis


def message_body(args: dict = None, **kwargs) -> dict:
    is_verbose = args.get('-v', False)
    defaults = {
        'response_type': ('in_channel' if is_verbose else 'ephemeral'),
    }
    defaults.update(kwargs)
    return defaults


def attachment(opts) -> dict:
    defaults = {
        'color': colors.BLUE,
    }
    defaults.update(opts)
    return defaults


def attachment_field(title: str, value: str, short: bool = True) -> dict:
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
    if item.type in [item_types.GITHUB_PUlL_REQUEST, item_types.PIVOTAL_STORY]:
        item_attachment.update({
            'fallback': f'{item.url} - {item.status}',
            'text': item.name,
            'title': item.item_id,
            'title_link': item.url,
        })
    else:
        item_attachment.update({
            'fallback': f'{item.value} - {item.status}',
            'color': config.get_status_color(item.status),
            'title': item.value,
            'title_link': item.value,
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
        'attachments': [await list_item_attachment(item, config) for item in items],
    }
