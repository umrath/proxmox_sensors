"""
Transport gegen einen ECHTEN aiohttp-Server (v5.0.0).

Die übrigen Transport-Tests arbeiten mit einer FakeSession — die bestätigt die
Logik, aber nicht, dass die aiohttp-Aufrufe selbst korrekt sind (Signaturen,
Context-Manager-Protokoll, `ClientTimeout`). Diese Tests fahren den echten
`ProxmoxClient` mit einer echten `ClientSession` gegen einen lokalen Server.

Insbesondere wird hier bewiesen, dass `ClientTimeout(total=…)` einen hängenden
Endpunkt wirklich abbricht — der Kern des 5.0.0-Fixes.
"""

import asyncio
import time

import aiohttp
import pytest
from aiohttp import web
from unittest.mock import MagicMock, patch

import custom_components.proxmox_sensors.api as api_mod
from custom_components.proxmox_sensors.api import ProxmoxClient


@pytest.fixture
async def server():
    """Minimal stand-in for the Proxmox API."""
    seen = {"requests": []}

    async def record(request):
        seen["requests"].append(
            {
                "path": request.path,
                "method": request.method,
                "headers": dict(request.headers),
                "cookies": dict(request.cookies),
                "body": await request.text(),
            }
        )

    async def nodes(request):
        await record(request)
        return web.json_response({"data": [{"node": "n1", "status": "online"}]})

    async def ticket(request):
        await record(request)
        return web.json_response(
            {"data": {"ticket": "PVE:tkt", "CSRFPreventionToken": "csrf-abc"}}
        )

    async def command(request):
        await record(request)
        return web.json_response({"data": "UPID:x"})

    async def slow(request):
        await asyncio.sleep(3)  # never answers within the test's budget
        return web.json_response({"data": "too late"})

    async def boom(request):
        return web.json_response({"errors": "nope"}, status=500)

    async def denied(request):
        return web.json_response({}, status=403)

    async def unauthorized(request):
        return web.json_response({}, status=401)

    app = web.Application()
    app.router.add_get("/api2/json/nodes", nodes)
    app.router.add_post("/api2/json/access/ticket", ticket)
    app.router.add_post("/api2/json/nodes/n1/status", command)
    app.router.add_get("/api2/json/slow", slow)
    app.router.add_get("/api2/json/boom", boom)
    app.router.add_get("/api2/json/denied", denied)
    app.router.add_get("/api2/json/unauthorized", unauthorized)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]

    async with aiohttp.ClientSession() as session:
        yield {"port": port, "session": session, "seen": seen}

    await runner.cleanup()


def _client(server, **kw):
    params = dict(
        host="127.0.0.1",
        user="root@pam",
        token_id="ha",
        token_secret="sec",
        server_type="PVE",
    )
    params.update(kw)
    client = ProxmoxClient(**params)
    # Real session; plain-HTTP base so no TLS setup is needed for the local server.
    client._session = MagicMock(return_value=server["session"])
    client._api_base = MagicMock(
        return_value=f"http://127.0.0.1:{server['port']}/api2/json"
    )
    return client


@pytest.mark.asyncio
async def test_token_auth_reaches_the_server_and_unwraps_data(server):
    client = _client(server)
    result = await client.get(MagicMock(), "nodes")

    assert result == [{"node": "n1", "status": "online"}]
    req = server["seen"]["requests"][-1]
    assert req["headers"]["Authorization"] == "PVEAPIToken=root@pam!ha=sec"


@pytest.mark.asyncio
async def test_password_ticket_flow_end_to_end(server):
    client = _client(server, token_id=None, token_secret=None, password="pw")

    assert await client.get(MagicMock(), "nodes") == [{"node": "n1", "status": "online"}]
    await client.post(MagicMock(), "nodes/n1/status", {"command": "reboot"})

    login = [r for r in server["seen"]["requests"] if r["path"].endswith("ticket")][0]
    read = [r for r in server["seen"]["requests"] if r["path"].endswith("nodes")][0]
    write = [r for r in server["seen"]["requests"] if r["path"].endswith("status")][0]

    assert "username=root%40pam" in login["body"] and "password=pw" in login["body"]
    assert read["cookies"]["PVEAuthCookie"] == "PVE:tkt"
    assert write["headers"]["CSRFPreventionToken"] == "csrf-abc"
    assert write["body"] == "command=reboot"  # form-encoded, like proxmoxer sent


@pytest.mark.asyncio
async def test_total_timeout_really_aborts_a_hanging_endpoint(server):
    """The heart of 5.0.0: a node that never answers is cut off, fast."""
    client = _client(server)

    with patch.object(api_mod, "REQUEST_TIMEOUT", 0.3):
        start = time.monotonic()
        result = await client.get(MagicMock(), "slow")
        elapsed = time.monotonic() - start

    assert result is None
    assert elapsed < 2.0, f"timeout did not fire (took {elapsed:.2f}s)"


@pytest.mark.asyncio
async def test_hanging_endpoint_does_not_block_other_calls(server):
    """A wedged endpoint must not delay healthy ones running alongside it."""
    client = _client(server)

    with patch.object(api_mod, "REQUEST_TIMEOUT", 0.3):
        start = time.monotonic()
        slow_result, good_result = await asyncio.gather(
            client.get(MagicMock(), "slow"),
            client.get(MagicMock(), "nodes"),
        )
        elapsed = time.monotonic() - start

    assert slow_result is None
    assert good_result == [{"node": "n1", "status": "online"}]
    assert elapsed < 2.0


@pytest.mark.asyncio
async def test_http_error_codes_over_the_wire(server):
    client = _client(server)
    assert await client.get(MagicMock(), "denied") is None        # 403
    assert await client.get(MagicMock(), "unauthorized") is None  # 401
    assert await client.get(MagicMock(), "boom") is None          # 500


@pytest.mark.asyncio
async def test_connection_refused_to_a_dead_port_returns_none():
    """Nothing listening at all — the powered-off-node case."""
    client = ProxmoxClient(
        host="127.0.0.1", user="root@pam", token_id="ha", token_secret="sec"
    )
    async with aiohttp.ClientSession() as session:
        client._session = MagicMock(return_value=session)
        # Port 1 is reserved and never listening.
        client._api_base = MagicMock(return_value="http://127.0.0.1:1/api2/json")
        assert await client.get(MagicMock(), "nodes") is None
