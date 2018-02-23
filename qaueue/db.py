import asyncio
from contextlib import contextmanager
import typing

from qaueue.constants import colors, fields, item_types, statuses
import aioredis
from aioredis import Redis





class RedisObject(object):
    redis: typing.Optional[Redis] = None

    @classmethod
    def register_db(cls, conn: Redis):
        cls.redis = conn


class Item(RedisObject):
    def __init__(self, **kwargs):
        self.item_id = kwargs.get('item_id')
        self.status = kwargs.get(fields.STATUS)
        self.value = kwargs.get(fields.VALUE)
        self.type = kwargs.get(fields.TYPE)
        self.name = kwargs.get(fields.NAME)
        self.url = kwargs.get(fields.URL)
        self.released_at = kwargs.get(fields.RELEASED_AT)

    @classmethod
    async def exists(cls, item_id: str) -> bool:
        if cls.redis is None:
            return False
        exists = await cls.redis.exists(item_id)
        return exists == 1

    @classmethod
    async def get(cls, item_id: str):
        if cls.redis is None:
            return
        if not await cls.exists(item_id):
            return
        kwargs = {'item_id': item_id}
        for field in fields.values():
            kwargs[field] = await cls.redis.hget(item_id, field)
        return cls(**kwargs)

    async def update(self):
        hkeys = []
        for field in fields.values():
            value = getattr(self, field)
            if value is not None:
                hkeys.append(field)
                hkeys.append(value)
        await self.redis.hmset(self.item_id, *hkeys)
        return self

    async def remove(self):
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
            queued_item = await cls.index(i)
            if queued_item.item_id == item.item_id:
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
        res1 = tr.execute()
        res2 = asyncio.gather(*futs)
        assert res1 == res2

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
        res1 = await tr.execute()
        res2 = await asyncio.gather(*futs)
        assert res1 == res2
        return res1[-1]

    @classmethod
    async def remove_from_queue(cls, item: Item):
        await cls.redis.lrem(cls.key, 0, item.item_id)
        await item.remove()
