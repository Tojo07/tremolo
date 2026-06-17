# SPDX-License-Identifier: MIT
# Copyright (c) 2023 Anggit Arfanto

from functools import partial
from inspect import isawaitable

__all__ = ['CORSMiddleware']


def _normalize(values, upper=False):
    result = []

    for value in values:
        if isinstance(value, str):
            value = value.encode('latin-1')

        result.append(value.upper() if upper else value)

    return result


async def _cors_error_handler(cors, handler, **server):
    """Run the original error handler, then re-apply CORS headers.

    Bound to its ``cors``/``handler`` via ``functools.partial`` (see
    ``CORSMiddleware._on_error``) instead of a closure: a closure captured
    inside a method is not picklable, which would make a CORS-enabled
    ``Application`` unpicklable and unable to run under Tremolo's default
    multi-process (spawn) worker model. A module-level coroutine + partial
    pickles cleanly, is recognized by ``inspect.iscoroutinefunction``, and
    accepts a ``__name__``.
    """
    data = handler(**server)

    if isawaitable(data):
        data = await data

    cors._apply_error_cors(server.get('request'), server.get('response'))

    return data


class CORSMiddleware:
    """Cross-Origin Resource Sharing (CORS) middleware.

    It handles both phases of a CORS exchange:

    - the *preflight* (an ``OPTIONS`` request carrying ``Origin`` and
      ``Access-Control-Request-Method``), which is answered early -- before
      routing -- with the ``Access-Control-Allow-*`` headers. An invalid
      preflight (disallowed origin, method, or header) is rejected with a
      ``403 Forbidden`` and the route handler is never invoked;
    - the *actual request*, where the matching ``Access-Control-Allow-Origin``
      (and related) headers are added to the response. A disallowed origin is
      not rejected; the headers are simply omitted so the browser blocks it
      (the same behavior as flask-cors, expressjs/cors, and Starlette).

    The ``Access-Control-Allow-Origin`` header is also re-applied to error
    responses (e.g. 404 or 500), which the framework otherwise builds with the
    headers cleared. Without this, the browser would mask the real error with a
    misleading CORS failure.

    Usage::

        from tremolo import Application
        from tremolo.middlewares import CORSMiddleware

        app = Application()
        CORSMiddleware(app, allow_origins=['https://example.com'])
    """

    def __init__(self, app, *,
                 allow_origins=('*',),
                 allow_methods=('GET', 'HEAD', 'POST', 'OPTIONS'),
                 allow_headers=(),
                 expose_headers=(),
                 allow_credentials=False,
                 max_age=600,
                 priority=999,
                 prefix=()):
        self.app = app
        self.allow_credentials = bool(allow_credentials)

        origins = _normalize(allow_origins)
        self.allow_all_origins = b'*' in origins
        self._origins = set(origins)

        methods = _normalize(allow_methods, upper=True)
        self.allow_all_methods = b'*' in methods
        methods = [m for m in methods if m != b'*']
        self._allow_methods = b', '.join(methods)
        self._methods = set(methods)

        headers = _normalize(allow_headers)
        self.allow_all_headers = b'*' in headers
        headers = [h for h in headers if h != b'*']
        self._allow_headers = b', '.join(headers)
        self._headers = {h.lower() for h in headers}

        expose = _normalize(expose_headers)
        self.allow_all_expose = b'*' in expose
        self._expose_headers = b', '.join(e for e in expose if e != b'*')

        self._max_age = b'%d' % int(max_age)

        if isinstance(prefix, str):
            prefix = prefix.encode('latin-1')

        if isinstance(prefix, bytes):
            prefix = tuple(p for p in prefix.strip(b'/').split(b'/') if p)

        self.prefix = prefix

        app.add_middleware(self._preflight, 'request',
                           priority=priority, prefix=prefix)
        app.add_middleware(self._cors, 'response',
                           priority=priority, prefix=prefix)

        # the error path clears headers and skips response middlewares, so the
        # CORS headers are re-applied by wrapping the error handlers instead
        self._wrap_error_handlers(app)

    def _wrap_error_handlers(self, app):
        handlers = app.routes[0]

        for i, (code, func, kwargs, options) in enumerate(handlers):
            if func is None:
                continue

            handlers[i] = (code, self._on_error(func), kwargs, options)

    def _on_error(self, handler):
        wrapped = partial(_cors_error_handler, self, handler)
        # Tremolo prints the route table via ``func.__name__``; partial has
        # none by default, so copy the original handler's.
        wrapped.__name__ = getattr(handler, '__name__', 'cors_error_handler')

        return wrapped

    def _apply_error_cors(self, request, response):
        if request is None or response is None or response.headers_sent():
            return

        if not self._matches_prefix(request.path):
            return

        origin = request.headers.get(b'origin')

        if origin is None or not self._is_allowed_origin(origin[0]):
            return

        self._set_origin_headers(response, origin[0])

    def _matches_prefix(self, path):
        if not self.prefix:
            return True

        prefix = b'/' + b'/'.join(self.prefix)

        return path == prefix or path.startswith(prefix + b'/')

    def _is_allowed_origin(self, origin):
        return self.allow_all_origins or origin in self._origins

    def _is_allowed_method(self, method):
        return self.allow_all_methods or method.upper() in self._methods

    def _is_allowed_headers(self, acrh):
        if self.allow_all_headers or not acrh:
            return True

        for value in acrh:
            for header in value.split(b','):
                if header.strip().lower() not in self._headers:
                    return False

        return True

    def _set_origin_headers(self, response, origin):
        if self.allow_all_origins and not self.allow_credentials:
            response.set_header(b'Access-Control-Allow-Origin', b'*')
        else:
            # credentials cannot be used with a wildcard origin, so the
            # specific Origin is echoed back and varied upon
            response.set_header(b'Access-Control-Allow-Origin', origin)
            response.append_header(b'Vary', b'Origin')

        if self.allow_credentials:
            response.set_header(b'Access-Control-Allow-Credentials', b'true')

    async def _preflight(self, **server):
        request = server['request']
        response = server['response']

        origin = request.headers.get(b'origin')

        if origin is None:
            return

        if (request.method != b'OPTIONS' or
                b'access-control-request-method' not in request.headers):
            # an actual (non-preflight) request, handled by self._cors
            return

        origin = origin[0]
        acrm = request.headers[b'access-control-request-method'][0]
        acrh = request.headers.get(b'access-control-request-headers')

        # mark the request so self._cors won't add headers afterwards
        request.ctx.cors = True

        failures = []

        if not self._is_allowed_origin(origin):
            failures.append(b'origin')

        if not self._is_allowed_method(acrm):
            failures.append(b'method')

        if not self._is_allowed_headers(acrh):
            failures.append(b'headers')

        if failures:
            # reject the preflight; the route handler is never invoked
            response.set_status(403, b'Forbidden')
            response.set_content_type(b'text/plain')
            return b'Disallowed CORS ' + b', '.join(failures)

        self._set_origin_headers(response, origin)

        if self._allow_methods:
            methods = self._allow_methods
        elif self.allow_all_methods and not self.allow_credentials:
            methods = b'*'
        else:
            methods = acrm

        response.set_header(b'Access-Control-Allow-Methods', methods)

        if self._allow_headers:
            response.set_header(b'Access-Control-Allow-Headers',
                                self._allow_headers)
        elif self.allow_all_headers and not self.allow_credentials:
            response.set_header(b'Access-Control-Allow-Headers', b'*')
        elif acrh:
            response.set_header(b'Access-Control-Allow-Headers',
                                b', '.join(acrh))

        response.set_header(b'Access-Control-Max-Age', self._max_age)
        response.set_status(204, b'No Content')

        # ending the response here; routing is skipped
        return b''

    async def _cors(self, **server):
        request = server['request']
        response = server['response']

        if getattr(request.ctx, 'cors', False):
            # a preflight, already handled by self._preflight
            return

        origin = request.headers.get(b'origin')

        if origin is None:
            return

        origin = origin[0]

        if not self._is_allowed_origin(origin):
            return

        self._set_origin_headers(response, origin)

        if self._expose_headers:
            response.set_header(b'Access-Control-Expose-Headers',
                                self._expose_headers)
        elif self.allow_all_expose and not self.allow_credentials:
            response.set_header(b'Access-Control-Expose-Headers', b'*')
