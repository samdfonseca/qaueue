from aiohttp.web import Application
import aioredis


async def init_redis(app: Application):
    conf = app['config']
    conn = await aioredis.create_redis(
            conf.REDIS_ADDRESS,
            db=conf.REDIS_DB,
            encoding='utf-8')
    app['redis'] = conn


async def close_redis(app: Application):
    app['redis'].close()
    await app['redis'].wait_closed()


