#!/usr/bin/env python3

import os
import sys

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tremolo import Application  # noqa: E402
from tremolo.middlewares import CORSMiddleware  # noqa: E402

CORS_HOST = '127.0.0.1'
CORS_PORT = 28100

app = Application()

# CORS applied app-wide (standard CORS API; no path scoping).
CORSMiddleware(app,
               allow_origins=['http://example.com'],
               allow_methods=['GET', 'POST'],
               allow_headers=['content-type'],
               expose_headers=['x-total-count'],
               max_age=600)

__all__ = ['app', 'serve', 'CORS_HOST', 'CORS_PORT']


@app.route('/cors')
async def cors_handler(**server):
    return b'cors'


@app.route('/cors/error')
async def cors_error(**server):
    raise Exception('boom')


def serve():
    # module-level entrypoint so multiprocessing (spawn) re-imports this module
    # and rebuilds the (CORS-wrapped) app in the child instead of pickling it
    app.run(CORS_HOST, port=CORS_PORT, worker_num=0, debug=False,
            loop='asyncio.SelectorEventLoop')


if __name__ == '__main__':
    serve()
