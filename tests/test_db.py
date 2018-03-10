import hashlib
import random

from qaueue import db
from qaueue import pivotal
from qaueue.constants import colors, fields, item_types, statuses

import pytest


def pivotal_story_url():
    story_id = random.randrange(10**8, 10**9)
    return f'https://www.pivotaltracker.com/story/show/{str(story_id)}'


def github_story_url():
    pr_id = random.randrange(1, 100000)
    return f'https://github.com/testorg/testrepo/pull/{str(pr_id)}'


async def test_create_pivotal_item():
    url = pivotal_story_url()
    item_id = hashlib.md5(url.encode()).hexdigest()
    item = await db.Item.create(url=url, name='unit test story')
    assert item.status == statuses.INITIAL
    assert await item.get_priority() == 0
    assert await db.Item.exists(item.item_id) == True
    assert item.item_id == item_id
    assert item.type == item_types.PIVOTAL_STORY
    assert (await db.QAueueQueue.index(0)).item_id == item.item_id
    assert len((await db.QAueueQueue.items())) == 1


async def test_create_github_item():
    url = github_story_url()
    item_id = hashlib.md5(url.encode()).hexdigest()
    item = await db.Item.create(url=url, name='unit test story')
    assert item.status == statuses.INITIAL
    assert await item.get_priority() == 0
    assert await db.Item.exists(item.item_id) == True
    assert item.item_id == item_id
    assert item.type == item_types.GITHUB_PULL_REQUEST
    assert (await db.QAueueQueue.index(0)).item_id == item.item_id
    assert len((await db.QAueueQueue.items())) == 1


async def test_create_two_items():
    url1 = pivotal_story_url()
    url2 = pivotal_story_url()
    story_id1 = pivotal.get_story_id_from_url(url1)
    story_id2 = pivotal.get_story_id_from_url(url2)
    item1 = await db.Item.create(url=url1, name='unit test story 1')
    item2 = await db.Item.create(url=url2, name='unit test story 2')
    assert item1.status == statuses.INITIAL
    assert item2.status == statuses.INITIAL
    assert await db.Item.exists(item1.item_id) == True
    assert await db.Item.exists(item2.item_id) == True
    assert await item1.get_priority() == 0
    assert await item2.get_priority() == 1
    assert (await db.QAueueQueue.index(0)).item_id == item1.item_id
    assert (await db.QAueueQueue.index(1)).item_id == item2.item_id
    assert len((await db.QAueueQueue.items())) == 2


async def test_prioritize_items():
    url1 = pivotal_story_url()
    url2 = pivotal_story_url()
    story_id1 = pivotal.get_story_id_from_url(url1)
    story_id2 = pivotal.get_story_id_from_url(url2)
    item1 = await db.Item.create(url=url1, name='unit test story 1')
    item2 = await db.Item.create(url=url2, name='unit test story 2')
    assert await item1.get_priority() == 0
    assert await item2.get_priority() == 1
    assert (await db.QAueueQueue.index(0)).item_id == item1.item_id
    assert (await db.QAueueQueue.index(1)).item_id == item2.item_id
    assert len((await db.QAueueQueue.items())) == 2
    await item1.set_priority(1)
    assert await item1.get_priority() == 1
    assert await item2.get_priority() == 0
    assert (await db.QAueueQueue.index(1)).item_id == item1.item_id
    assert (await db.QAueueQueue.index(0)).item_id == item2.item_id
    assert len((await db.QAueueQueue.items())) == 2


async def test_update_item_status():
    url = pivotal_story_url()
    story_id = pivotal.get_story_id_from_url(url)
    item = await db.Item.create(url=url, name='unit test story')
    assert item.status == statuses.INITIAL
    item.status = 'integration'
    item = await item.update()
    assert item.status == 'integration'


async def test_remove_item():
    url = pivotal_story_url()
    story_id = pivotal.get_story_id_from_url(url)
    item = await db.Item.create(url=url, name='unit test story')
    assert await db.Item.exists(item.item_id) == True
    await item.remove()
    assert await db.Item.exists(item.item_id) == False
    assert await db.QAueueQueue.item_priority(item) is None
    assert len((await db.QAueueQueue.items())) == 0

