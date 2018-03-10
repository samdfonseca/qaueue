import hashlib

import redis.client


def run(conn: redis.client.Redis, pipe: redis.client.Pipeline):
    patterns = ['PT/*', 'GH/*']
    for pattern in patterns:
        keys = conn.keys(pattern)
        for key in keys:
            item_url = conn.hget(key, 'url')
            item_id = hashlib.md5(item_url).hexdigest()
            pipe.rename(key, item_id)
    queued_ids = conn.lrange('qaueue_Q', 0, -1)
    for queued_id in queued_ids:
        item_url = conn.hget(queued_id, 'url')
        pipe.rpush('tmp_Q1', hashlib.md5(item_url).hexdigest())
    pipe.delete('qaueue_Q')
    pipe.rename('tmp_Q1', 'qaueue_Q')

