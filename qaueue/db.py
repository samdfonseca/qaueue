import hashlib
import typing
from uuid import uuid4

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


class InvalidItemStatusError(Exception):
    def __init__(self, msg):
        super().__init__(msg)


class ItemNotInQueueError(Exception):
    def __init__(self, item):
        super().__init__(f'Item not found in queue: {item.item_id}')


class OutOfRangePriorityIndexError(Exception):
    def __init__(self, priority_index: int, range_len: int):
        index_min = 0
        index_max = range_len - 1
        index_negative_min = -1
        index_negative_max = -range_len
        msg = (f'Priority index \'{priority_index}\' is out of range. Valid ranges: '
               f'{index_min} <= priority_index <= {index_max}, '
               f'{index_negative_min} >= priority_index >= {index_negative_max}')
        super().__init__(msg)


class InvalidItemPriorityError(Exception):
    def __init__(self, priority_index: int):
        super().__init__(f'Priority index is not valid: {str(priority_index)}')


class UnsupportedKwargError(Exception):
    pass


class Item(RedisObject):
    _url_validators = [
        (pivotal.is_pivotal_story_url, item_types.PIVOTAL_STORY),
        (github.is_pull_request_url, item_types.GITHUB_PULL_REQUEST),
    ]

    def __init__(self, **kwargs):
        self.status = kwargs.get(fields.STATUS)
        self.url = kwargs.get(fields.URL)
        self.name = kwargs.get(fields.NAME)
        self.released_at = kwargs.get(fields.RELEASED_AT)
        self.item_id = kwargs.get(fields.ITEM_ID, self.item_id_from_url(self.url))
        if not self.is_supported_url(self.url):
            raise UnsupportedItemTypeError
        self.type = kwargs.get(fields.TYPE, self.get_item_type(self.url))
        if self.type not in item_types.values():
            raise UnsupportedItemTypeError

    @classmethod
    def is_supported_url(cls, url: str) -> bool:
        for func, _ in cls._url_validators:
            if func(url):
                return True
        return False

    @classmethod
    def get_item_type(cls, item_url) -> str:
        for check_url_func, item_type in cls._url_validators:
            if check_url_func(item_url):
                return item_type
        raise UnsupportedItemTypeError

    @classmethod
    def item_id_from_url(cls, url: str) -> str:
        if cls.is_supported_url(url):
            return hashlib.md5(url.encode()).hexdigest()
        raise UnsupportedItemTypeError

    @classmethod
    async def exists(cls, item_id: str = None, item_url: str = None) -> typing.Optional[bool]:
        if item_id is None and item_url is None:
            return
        if cls.redis is None:
            return False
        item_id = item_id or (cls.item_id_from_url(item_url) if item_url is not None else None)
        if item_id is None:
            return
        exists = await cls.redis.exists(item_id)
        return exists == 1

    @classmethod
    async def create(cls, **kwargs):
        if 'item_id' in kwargs:
            raise UnsupportedKwargError('item_id can not be passed as a kwarg')
        if 'type' in kwargs:
            raise UnsupportedKwargError('type can not be passed as a kwarg')
        kwargs['status'] = kwargs.get('status', statuses.INITIAL)
        item = cls(**kwargs)
        if not await cls.exists(item.item_id):
            await item.add_to_queue()
        await item.update()
        return await cls.get(item.item_id)

    @classmethod
    async def get(cls, item_id: str = None, item_index: int = None, item_url: str = None):
        if item_id is None and item_index is None and item_url is None:
            return
        if cls.redis is None:
            return
        if item_id is None and (item_index is not None or item_url is not None):
            if item_index is not None:
                return await QAueueQueue.index(item_index)
            # item_url is not None
            item_id = cls.item_id_from_url(item_url)
        if not await cls.exists(item_id):
            return
        kwargs = {'item_id': item_id}
        for field in fields.values():
            kwargs[field] = await cls.redis.hget(item_id, field)
        return cls(**kwargs)

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

    def to_json(self):
        item_json = {field: getattr(self, field) for field in fields.values()}
        item_json['priority'] = self.get_priority()
        return item_json


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
    async def index(cls, i) -> typing.Optional[Item]:
        item_id = await cls.redis.lindex(cls.key, i)
        if item_id is None:
            return
        item = await Item.get(item_id)
        return item

    @classmethod
    async def item_priority(cls, item: Item) -> typing.Optional[int]:
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
    async def prioritize(cls, item: Item, priority: int, force: bool = False):
        if item.status != statuses.INITIAL and force is not True:
            raise InvalidItemStatusError(f'Item cannot be prioritized since status is not \'queued\': {item.item_id}')
        tr: aioredis.commands.MultiExec = cls.redis.multi_exec()
        futs = []
        queue_len = len(await cls.items())
        if priority >= queue_len or (priority < 0 and abs(priority) > queue_len):
            # Priority index is out of bounds
            raise OutOfRangePriorityIndexError(priority, queue_len)
        if priority < 0:
            # Convert negative priority index to positive, ex. [1,2,3][-2] -> 3 + -2 = 1 -> [1,2,3][1]
            priority = queue_len + priority
        if priority == (queue_len - 1):
            # Move item to back of queue
            futs.append(tr.lrem(cls.key, 0, item.item_id))
            futs.append(tr.rpush(cls.key, item.item_id))
        if priority == 0:
            # Move item to front of queue
            futs.append(tr.lrem(cls.key, 0, item.item_id))
            futs.append(tr.lpush(cls.key, item.item_id))
        if priority >= 1:
            after_item_id = await cls.redis.lindex(cls.key, priority)
            if after_item_id != item.item_id:
                futs.append(tr.lrem(cls.key, 0, item.item_id))
                futs.append(tr.linsert(cls.key, after_item_id, item.item_id))
        await tr.execute()

    @classmethod
    async def add_to_queue(cls, item: Item):
        if await cls.item_priority(item) is not None:
            return
        tr = cls.redis.multi_exec()
        tr.llen(cls.key)
        tr.rpush(cls.key, item.item_id),
        tr.hset(item.item_id, fields.STATUS, statuses.INITIAL),
        tr.llen(cls.key),
        res = await tr.execute()
        assert res[0] == (res[-1] - 1)
        return await cls.item_priority(item)

    @classmethod
    async def remove_from_queue(cls, item: Item):
        await cls.redis.lrem(cls.key, 0, item.item_id)

    @classmethod
    async def to_json(cls) -> list:
        items = await cls.items()
        return [item.to_json() for item in items]
