import asyncio
from contextlib import contextmanager
import typing

from qaueue import github
from qaueue import pivotal
from qaueue.constants import colors, fields, item_types, statuses
import aioredis
from aioredis import Redis


class RedisObject(object):
    redis: typing.Optional[Redis] = None

    @classmethod
    def register_db(cls, conn: Redis):
        cls.redis = conn


class UnsupportedItemTypeError(Exception):
    def __init__(self):
        super().__init__('Unsupported item type: must be either a Pivotal story URL or GitHub PR URL')


class ItemAlreadyExistsError(Exception):
    def __init__(self, item):
        super().__init__(f'Item already exists: {item.item_id}')


class Item(RedisObject):
    _item_id_prefix = 'item:'
    _url_validators = [
            pivotal.is_pivotal_story_url,
            github.is_pull_request_url,
            ]

    def __init__(self, **kwargs):
        self.status = kwargs.get(fields.STATUS)
        self.url = kwargs.get(fields.URL)
        if not self.is_supported_url(self.url):
            raise UnsupportedItemTypeError
        self.value = self.url or kwargs.get(fields.VALUE)
        self.type = kwargs.get(fields.TYPE)
        self.name = kwargs.get(fields.NAME)
        self.released_at = kwargs.get(fields.RELEASED_AT)
        self.item_id = kwargs.get('item_id', self.item_id_from_url(self.value))

    @classmethod
    def is_supported_url(cls, url: str) -> str:
        for func in cls._url_validators:
            if func(url):
                return True
        return False

    @classmethod
    def item_id_from_url(cls, url: str) -> str:
        if github.is_pull_request_url(url):
            org_name, repo_name, pr_id = github.parse_pull_request_url(url)
            return cls.internal_item_id(f'GH/{repo_name}/{str(pr_id)}')
        if pivotal.is_pivotal_story_url(url):
            story_id = pivotal.get_story_id_from_url(url)
            return cls.internal_item_id(f'PT/{story_id}')
        raise UnsupportedItemTypeError

    @classmethod
    def internal_item_id(cls, item_id: str) -> str:
        return item_id
        #  if item_id.startswith(cls._item_id_prefix):
        #      return item_id
        #  return f'{cls._item_id_prefix}{item_id}'

    @classmethod
    async def exists(cls, item_id: str) -> bool:
        if cls.redis is None:
            return False
        exists = await cls.redis.exists(cls.internal_item_id(item_id))
        return exists == 1

    @classmethod
    async def create(cls, **kwargs):
        item = cls(**kwargs)
        if not await cls.exists(item.item_id):
            await item.add_to_queue()
        await item.update()
        return await cls.get(item.item_id)

    @classmethod
    async def get(cls, item_id: str):
        if cls.redis is None:
            return
        if not await cls.exists(item_id):
            return
        if item_id.startswith(cls._item_id_prefix):
            item_id = item_id.lstrip(cls._item_id_prefix)
        kwargs = {'item_id': item_id}
        for field in fields.values():
            kwargs[field] = await cls.redis.hget(cls.internal_item_id(item_id), field)
        return cls(**kwargs)

    #  @property
    #  def item_id(self) -> str:
    #      return self.internal_item_id(self._item_id)
    #  
    #  @item_id.setter
    #  def item_id(self, value):
    #      self._item_id = value
    #  
    #  @item_id.deleter
    #  def item_id(self):
    #      del self._item_id

    async def get_priority(self) -> int:
        return await QAueueQueue.item_priority(self)

    async def set_priority(self, value: int):
        await QAueueQueue.prioritize(self, value)

    async def update(self):
        hkeys = []
        for field in fields.values():
            value = getattr(self, field)
            if value is not None:
                hkeys.append(field)
                hkeys.append(value)
        await self.redis.hmset(self.item_id, *hkeys)
        return await Item.get(self.item_id)

    async def add_to_queue(self) -> int:
        return await QAueueQueue.add_to_queue(self)

    async def remove(self):
        queue_index = await QAueueQueue.item_priority(self)
        if queue_index is not None:
            await QAueueQueue.remove_from_queue(self)
        await self.redis.delete(self.item_id)


class QAueueQueue(RedisObject):
    key = 'qaueue_Q'

    @classmethod
    async def items(cls) -> typing.List[Item]:
        qlen = await cls.redis.llen(cls.key)
        items_ = []
        for i in range(qlen):
            item_id = await cls.redis.lindex(cls.key, i)
            item = await Item.get(item_id)
            items_.append(item)
        return items_

    @classmethod
    async def index(cls, i) -> Item:
        item_id = await cls.redis.lindex(cls.key, i)
        item = await Item.get(item_id)
        return item

    @classmethod
    async def item_priority(cls, item: Item) -> int:
        i = 0
        qlen = await cls.redis.llen(cls.key)
        while True:
            if i >= qlen:
                break
            queued_item_id = await cls.redis.lindex(cls.key, i)
            if queued_item_id == item.item_id:
                return i
            i += 1

    @classmethod
    async def prioritize(cls, item: Item, priority: int):
        tr: aioredis.commands.MultiExec = cls.redis.multi_exec()
        futs = []
        if priority == 1:
            futs.append(tr.lrem(cls.key, 0, item.item_id))
            futs.append(tr.lpush(cls.key, item.item_id))
        if priority >= 2:
            after_item_id = await cls.redis.lindex(cls.key, (priority - 1))
            if after_item_id != item.item_id:
                futs.append(tr.lrem(cls.key, 0, item.item_id))
                futs.append(tr.linsert(cls.key, after_item_id, item.item_id))
        await tr.execute()

    @classmethod
    async def add_to_queue(cls, item: Item):
        if await cls.item_priority(item) is not None:
            return
        tr = cls.redis.multi_exec()
        futs = [
            tr.rpush(cls.key, item.item_id),
            tr.hset(item.item_id, fields.STATUS, statuses.INITIAL),
            tr.llen(cls.key),
        ]
        res = await tr.execute()
        return res[-1]

    @classmethod
    async def remove_from_queue(cls, item: Item):
        await cls.redis.lrem(cls.key, 0, item.item_id)
