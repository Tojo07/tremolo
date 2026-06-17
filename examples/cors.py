#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Author: Anggit Arfanto
# Description: Enabling CORS (preflight + actual request) with CORSMiddleware

from tremolo import Application
from tremolo.middlewares import CORSMiddleware

app = Application()

# apply middleware
# the OPTIONS preflight is answered automatically, and the matching
# Access-Control-Allow-* headers are added to the actual responses below
CORSMiddleware(app,
               allow_origins=['https://example.com'],
               allow_methods=['GET', 'POST'],
               allow_headers=['content-type'],
               allow_credentials=True,
               max_age=600)


@app.route('/hello')
async def hello_world(**server):
    return 'Hello World!'


if __name__ == '__main__':
    app.run('0.0.0.0', 8005, log_level='ERROR')
