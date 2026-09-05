"""Shared aiohttp test doubles for the transport tests (v5.0.0).

`ProxmoxClient._session()` returns HA's shared aiohttp session; tests patch it
with a `FakeSession` that records every call and returns whatever the supplied
handler yields (a `FakeResponse`, or an exception instance to raise).
"""

from unittest.mock import MagicMock

import aiohttp


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status = status
        self._payload = {} if payload is None else payload
        self._text = text

    async def json(self, content_type=None):
        return self._payload

    async def text(self):
        return self._text

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(MagicMock(), (), status=self.status)


class _CM:
    """Stands in for aiohttp's request context manager."""

    def __init__(self, result):
        self._result = result

    async def __aenter__(self):
        if isinstance(self._result, Exception):
            raise self._result
        return self._result

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    """Records calls and returns whatever `handler(method, url, kwargs)` yields."""

    def __init__(self, handler):
        self._handler = handler
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return _CM(self._handler(method, url, kwargs))

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)


def attach(client, handler):
    """Point a ProxmoxClient at a FakeSession driven by `handler`."""
    session = FakeSession(handler)
    client._session = MagicMock(return_value=session)
    return session


def connect_error():
    return aiohttp.ClientConnectorError(MagicMock(), OSError("refused"))
