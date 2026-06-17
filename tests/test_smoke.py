#!/usr/bin/env python3

# A solution-independent regression test (pass_to_pass): it exercises core
# routing + the response-middleware chain that CORSMiddleware plugs into,
# WITHOUT importing the CORS solution. It must pass on the base repo and with
# the solution applied. Self-spawns its own server so it runs under pytest.

import multiprocessing as mp
import os
import signal
import sys
import unittest

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tremolo import Application  # noqa: E402
from tests.netizen import HTTPClient  # noqa: E402

SMOKE_HOST = '127.0.0.1'
SMOKE_PORT = 28200

app = Application()


@app.route('/ping')
async def ping(**server):
    return b'pong'


@app.on_response
async def add_marker(**server):
    server['response'].set_header(b'X-Smoke', b'ok')


__all__ = ['app', 'serve', 'SMOKE_HOST', 'SMOKE_PORT']


def serve():
    # module-level entrypoint (see cors_server.serve for why)
    app.run(SMOKE_HOST, port=SMOKE_PORT, worker_num=0, debug=False,
            loop='asyncio.SelectorEventLoop')


_server = None


def setUpModule():
    global _server

    mp.set_start_method('spawn', force=True)
    _server = mp.Process(target=serve)
    _server.start()


def tearDownModule():
    if _server is not None and _server.is_alive():
        os.kill(_server.pid, signal.SIGINT)
        _server.join()


class TestSmoke(unittest.TestCase):
    def setUp(self):
        print('\r\n[', self.id(), ']')

        self.client = HTTPClient(SMOKE_HOST, SMOKE_PORT, timeout=10, retries=10)

    def test_basic_route(self):
        with self.client:
            response = self.client.send(b'GET /ping HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.body(), b'pong')

    def test_response_middleware_runs(self):
        with self.client:
            response = self.client.send(b'GET /ping HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.headers[b'x-smoke'], [b'ok'])


if __name__ == '__main__':
    unittest.main()
