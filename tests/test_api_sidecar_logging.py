"""
Sidecar (:9000) Fehler waren stumm: `except Exception: return {}` erzeugte bei
nicht laufendem Dienst wortlos keine Entitäten (v4.2.2).

Fix: einmalige `LOGGER.warning` pro Host/Endpoint, unterschieden nach
"nicht erreichbar" (Verbindungsfehler) vs. "Anfrage fehlgeschlagen"; bei Erfolg
wird der Warn-Status zurückgesetzt (Recovery loggt erneut).

Seit v5.0.0 läuft auch der Sidecar über aiohttp mit hartem Gesamt-Timeout.
"""

import aiohttp
import pytest
from unittest.mock import MagicMock, patch

import custom_components.proxmox_sensors.api as api_mod
from custom_components.proxmox_sensors.api import ProxmoxClient

from tests.aiohttp_fakes import FakeResponse, attach, connect_error


def _client():
    return ProxmoxClient(
        host="pve.local",
        user="root@pam",
        token_id="ha",
        token_secret="sec",
        server_type="PVE",
    )


_connect_error = connect_error


@pytest.mark.asyncio
async def test_connection_error_warns_once_and_returns_empty():
    client = _client()
    attach(client, lambda m, u, k: _connect_error())
    with patch.object(api_mod.LOGGER, "warning") as warn:
        first = await client.get_lm_sensors_http(MagicMock(), "node1")
        second = await client.get_lm_sensors_http(MagicMock(), "node1")

    assert first == {} and second == {}
    assert warn.call_count == 1, "must warn once, not every poll"
    msg = warn.call_args[0][0] % warn.call_args[0][1:]
    assert "not reachable" in msg and "sensors" in msg


@pytest.mark.asyncio
async def test_http_error_uses_failed_message():
    client = _client()
    attach(client, lambda m, u, k: FakeResponse(status=500))
    with patch.object(api_mod.LOGGER, "warning") as warn:
        await client.get_smart_data_http(MagicMock(), "node1")

    assert warn.call_count == 1
    msg = warn.call_args[0][0] % warn.call_args[0][1:]
    assert "failed" in msg and "smart" in msg


@pytest.mark.asyncio
async def test_timeout_warns_and_returns_empty():
    client = _client()
    attach(client, lambda m, u, k: TimeoutError())
    with patch.object(api_mod.LOGGER, "warning") as warn:
        assert await client.get_mounts(MagicMock(), "node1") == {}
    assert warn.call_count == 1


@pytest.mark.asyncio
async def test_recovery_resets_and_rewarns():
    client = _client()
    state = {"down": True}

    def handler(method, url, kwargs):
        if state["down"]:
            return _connect_error()
        return FakeResponse(payload={"total_gb": 32})

    attach(client, handler)
    with patch.object(api_mod.LOGGER, "warning") as warn:
        await client.get_memory_http(MagicMock(), "node1")     # warn #1
        state["down"] = False
        recovered = await client.get_memory_http(MagicMock(), "node1")
        state["down"] = True
        await client.get_memory_http(MagicMock(), "node1")     # warn #2

    assert recovered == {"total_gb": 32}
    assert warn.call_count == 2, "recovery must re-arm the one-time warning"


@pytest.mark.asyncio
async def test_endpoints_warn_independently():
    client = _client()
    attach(client, lambda m, u, k: _connect_error())
    with patch.object(api_mod.LOGGER, "warning") as warn:
        await client.get_lm_sensors_http(MagicMock(), "node1")
        await client.get_mounts(MagicMock(), "node1")

    assert warn.call_count == 2  # sensors + mounts are distinct endpoints


@pytest.mark.asyncio
async def test_success_returns_payload_no_warning():
    client = _client()
    attach(client, lambda m, u, k: FakeResponse(payload={"disk": "nvme0"}))
    with patch.object(api_mod.LOGGER, "warning") as warn:
        result = await client.get_mounts(MagicMock(), "node1")

    assert result == {"disk": "nvme0"}
    assert not warn.called


@pytest.mark.asyncio
async def test_sidecar_uses_its_own_total_timeout():
    client = _client()
    session = attach(client, lambda m, u, k: FakeResponse(payload={}))
    await client.get_lm_sensors_http(MagicMock(), "node1")
    assert session.calls[0]["timeout"].total == 5      # sensors is the fast one
    assert ":9000/sensors" in session.calls[0]["url"]
