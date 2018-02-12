from . import views

from aiohttp import web


def setup_routes(app: web.Application):
    app.router.add_post('/qaueue', views.index)
