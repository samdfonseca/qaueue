from .config import Config as conf
from .redis import close_redis, init_redis
from .routes import setup_routes

from aiohttp import web
from dotenv import load_dotenv, find_dotenv


load_dotenv(find_dotenv(), override=True)
app = web.Application()


async def auth_middleware(app: web.Application, handler):
    async def middleware_handler(request):
        data = await request.post()
        if data.get('token') == conf.SLACK_VERIFICATION_TOKEN:
            response = await handler(request)
            return response
        raise web.HTTPForbidden
    return middleware_handler


def init_func(argv):
    app = web.Application()
    app['config'] = conf
    app.middlewares.append(auth_middleware)
    app.on_startup.append(init_redis)
    app.on_cleanup.append(close_redis)
    setup_routes(app)
    return app


if __name__ == '__main__':
    app['config'] = conf
    app.middlewares.append(auth_middleware)
    app.on_startup.append(init_redis)
    app.on_cleanup.append(close_redis)
    setup_routes(app)
    web.run_app(app, host='0.0.0.0', port=8889)
