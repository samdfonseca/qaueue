import os

from qaueue.config import Config
from qaueue.redis import close_redis, init_redis
from qaueue.routes import setup_routes

from aiohttp import web
from dotenv import load_dotenv, find_dotenv


app = web.Application()
dotenv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')


async def auth_middleware(app: web.Application, handler):
    async def middleware_handler(request):
        conf: Config  = app['config']
        data = await request.post()
        if data.get('token') == conf.SLACK_VERIFICATION_TOKEN:
            response = await handler(request)
            return response
        raise web.HTTPForbidden(body='Token mismatch')
    return middleware_handler


def init_func(argv):
    load_dotenv(dotenv_path)
    app = web.Application()
    app['config'] = Config(read_only=False)
    app.middlewares.append(auth_middleware)
    app.on_startup.append(init_redis)
    app.on_cleanup.append(close_redis)
    setup_routes(app)
    return app


if __name__ == '__main__':
    app = init_func([])
    web.run_app(app, host='0.0.0.0', port=8889)
