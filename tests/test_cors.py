#!/usr/bin/env python3

import multiprocessing as mp
import os
import signal
import sys
import unittest

# makes imports relative from the repo directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tests.cors_server import serve, CORS_HOST, CORS_PORT  # noqa: E402
from tests.netizen import HTTPClient  # noqa: E402

ORIGIN = b'http://example.com'

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


class TestCORS(unittest.TestCase):
    def setUp(self):
        print('\r\n[', self.id(), ']')

        self.client = HTTPClient(CORS_HOST, CORS_PORT, timeout=10, retries=10)

    def test_preflight(self):
        with self.client:
            response = self.client.send(
                b'OPTIONS /cors HTTP/1.1',
                b'Origin: ' + ORIGIN,
                b'Access-Control-Request-Method: POST',
                b'Access-Control-Request-Headers: content-type'
            )

            # successful preflight: a 2xx with the allow-* headers present.
            # Exact status (200 vs 204) and header formatting are left to the
            # implementation; we assert the observable CORS contract only.
            self.assertIn(response.status, (200, 204))
            self.assertEqual(
                response.headers[b'access-control-allow-origin'], [ORIGIN]
            )
            methods = response.headers[b'access-control-allow-methods'][0].upper()
            self.assertIn(b'GET', methods)
            self.assertIn(b'POST', methods)
            self.assertIn(
                b'content-type',
                response.headers[b'access-control-allow-headers'][0].lower()
            )
            self.assertEqual(
                response.headers[b'access-control-max-age'], [b'600']
            )

    def test_preflight_disallowed_origin(self):
        with self.client:
            response = self.client.send(
                b'OPTIONS /cors HTTP/1.1',
                b'Origin: http://evil.com',
                b'Access-Control-Request-Method: POST'
            )

            # disallowed preflight is denied: no Access-Control-Allow-Origin
            # is returned (browser blocks). Exact status/body left to impl.
            self.assertNotIn(b'access-control-allow-origin', response.headers)

    def test_preflight_disallowed_method(self):
        with self.client:
            response = self.client.send(
                b'OPTIONS /cors HTTP/1.1',
                b'Origin: ' + ORIGIN,
                b'Access-Control-Request-Method: DELETE'
            )

            # disallowed method on preflight → no allow-origin header
            self.assertNotIn(b'access-control-allow-origin', response.headers)

    def test_preflight_disallowed_headers(self):
        with self.client:
            response = self.client.send(
                b'OPTIONS /cors HTTP/1.1',
                b'Origin: ' + ORIGIN,
                b'Access-Control-Request-Method: POST',
                b'Access-Control-Request-Headers: x-not-allowed'
            )

            # disallowed request-header on preflight → no allow-origin header
            self.assertNotIn(b'access-control-allow-origin', response.headers)

    def test_actual_request(self):
        with self.client:
            response = self.client.send(
                b'GET /cors HTTP/1.1',
                b'Origin: ' + ORIGIN
            )

            self.assertEqual(response.status, 200)
            self.assertEqual(response.body(), b'cors')
            self.assertEqual(
                response.headers[b'access-control-allow-origin'], [ORIGIN]
            )
            self.assertIn(
                b'x-total-count',
                response.headers[b'access-control-expose-headers'][0].lower()
            )
            # Vary must include Origin (specific-origin echo); extras/dupes ok
            self.assertIn(
                b'origin', b','.join(response.headers[b'vary']).lower()
            )

    def test_actual_request_disallowed_origin(self):
        with self.client:
            response = self.client.send(
                b'GET /cors HTTP/1.1',
                b'Origin: http://evil.com'
            )

            # spec-standard: not rejected, headers simply omitted
            self.assertEqual(response.status, 200)
            self.assertEqual(response.body(), b'cors')
            self.assertNotIn(b'access-control-allow-origin', response.headers)

    def test_no_origin(self):
        with self.client:
            response = self.client.send(b'GET /cors HTTP/1.1')

            self.assertEqual(response.status, 200)
            self.assertEqual(response.body(), b'cors')
            self.assertNotIn(b'access-control-allow-origin', response.headers)

    def test_error_response_has_cors(self):
        # a 500 still carries CORS headers so the browser sees the real error
        with self.client:
            response = self.client.send(
                b'GET /cors/error HTTP/1.1',
                b'Origin: ' + ORIGIN
            )

            self.assertEqual(response.status, 500)
            self.assertEqual(
                response.headers[b'access-control-allow-origin'], [ORIGIN]
            )

    def test_not_found_has_cors(self):
        with self.client:
            response = self.client.send(
                b'GET /cors/missing HTTP/1.1',
                b'Origin: ' + ORIGIN
            )

            self.assertEqual(response.status, 404)
            self.assertEqual(
                response.headers[b'access-control-allow-origin'], [ORIGIN]
            )

    def test_error_response_disallowed_origin(self):
        with self.client:
            response = self.client.send(
                b'GET /cors/missing HTTP/1.1',
                b'Origin: http://evil.com'
            )

            self.assertEqual(response.status, 404)
            self.assertNotIn(b'access-control-allow-origin', response.headers)


if __name__ == '__main__':
    unittest.main()
