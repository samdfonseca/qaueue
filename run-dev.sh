#!/usr/bin/env bash
gunicorn wsgi:app --bind localhost:8889 --worker-class aiohttp.GunicornWebWorker --reload
