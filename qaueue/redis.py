from aiohttp.web import Application
import aioredis


_get_item_index_lua = '''
local items = redis.call('LRANGE', KEYS[1], 0, -1)
local i = 0
while true do
  if items[i+1] == ARGV[1] then
    return i
  end
  if i+1 == #items then
    break
  end
  i = i + 1
end
return -1
'''


async def init_redis(app: Application):
    conf = app['config']
    conn = await aioredis.create_redis(
            conf.REDIS_ADDRESS,
            db=conf.REDIS_DB,
            encoding='utf-8')
    app['redis'] = conn
    if (await conn.exists('get_item_index_sha') == 0):
        sha = await conn.execute('SCRIPT', 'LOAD', _get_item_index_lua)
        await conn.set('get_item_index_sha', sha)


async def close_redis(app: Application):
    app['redis'].close()
    await app['redis'].wait_closed()


