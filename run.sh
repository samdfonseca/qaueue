#!/usr/bin/env sh
gunicorn wsgi:app --bind 0.0.0.0:8889 --worker-class aiohttp.GunicornWebWorker
