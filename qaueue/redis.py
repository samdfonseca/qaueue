from qaueue import db

from aiohttp.web import Application
import aioredis


async def init_redis(app: Application):
    conf = app['config']
    conn = await aioredis.create_redis(
            conf.REDIS_ADDRESS,
            db=conf.REDIS_DB,
            encoding='utf-8')
    redis_objects = filter(lambda i: i != db.RedisObject and issubclass(i, db.RedisObject),
           filter(lambda i: type(i) == type,
                  map(lambda i: getattr(db, i), dir(db))))
    for redis_object in redis_objects:
        redis_object.register_db(conn)
    app['redis'] = conn


async def close_redis(app: Application):
    app['redis'].close()
    await app['redis'].wait_closed()


