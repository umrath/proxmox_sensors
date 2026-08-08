"""
Sidecar (:9000) Fehler waren stumm: `except Exception: return {}` erzeugte bei
nicht laufendem Dienst wortlos keine Entitäten (v4.2.2).

Fix: einmalige `LOGGER.warning` pro Host/Endpoint, unterschieden nach
"nicht erreichbar" (ConnectionError) vs. "Anfrage fehlgeschlagen"; bei Erfolg
wird der Warn-Status zurückgesetzt (Recovery loggt erneut).
"""

import pytest
import requests
from unittest.mock import MagicMock, patch

import custom_components.proxmox_sensors.api as api_mod
from custom_components.proxmox_sensors.api import ProxmoxClient


class _Hass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _client():
    return ProxmoxClient(
        host="pve.local",
        user="root@pam",
        token_id="t",
        token_secret="s",
        server_type="PVE",
    )


def _ok_response(payload):
    r = MagicMock()
    r.raise_for_status.return_value = None
    r.json.return_value = payload
    return r


@pytest.mark.asyncio
async def test_connection_error_warns_once_and_returns_empty():
    client = _client()
    hass = _Hass()
    with patch.object(
        api_mod.requests, "get",
        side_effect=requests.exceptions.ConnectionError("refused"),
    ), patch.object(api_mod.LOGGER, "warning") as warn:
        first = await client.get_lm_sensors_http(hass, "node1")
        second = await client.get_lm_sensors_http(hass, "node1")

    assert first == {} and second == {}
    assert warn.call_count == 1, "must warn once, not every poll"
    msg = warn.call_args[0][0] % warn.call_args[0][1:]
    assert "not reachable" in msg and "sensors" in msg


@pytest.mark.asyncio
async def test_http_error_uses_failed_message():
    client = _client()
    hass = _Hass()
    resp = MagicMock()
    resp.raise_for_status.side_effect = requests.exceptions.HTTPError("500")
    with patch.object(api_mod.requests, "get", return_value=resp), patch.object(
        api_mod.LOGGER, "warning"
    ) as warn:
        await client.get_smart_data_http(hass, "node1")

    assert warn.call_count == 1
    msg = warn.call_args[0][0] % warn.call_args[0][1:]
    assert "failed" in msg and "smart" in msg


@pytest.mark.asyncio
async def test_recovery_resets_and_rewarns():
    client = _client()
    hass = _Hass()
    with patch.object(api_mod.LOGGER, "warning") as warn:
        with patch.object(
            api_mod.requests, "get",
            side_effect=requests.exceptions.ConnectionError("down"),
        ):
            await client.get_memory_http(hass, "node1")  # warn #1
        with patch.object(
            api_mod.requests, "get", return_value=_ok_response({"total_gb": 32})
        ):
            recovered = await client.get_memory_http(hass, "node1")  # recovers
        with patch.object(
            api_mod.requests, "get",
            side_effect=requests.exceptions.ConnectionError("down again"),
        ):
            await client.get_memory_http(hass, "node1")  # warn #2

    assert recovered == {"total_gb": 32}
    assert warn.call_count == 2, "recovery must re-arm the one-time warning"


@pytest.mark.asyncio
async def test_endpoints_warn_independently():
    client = _client()
    hass = _Hass()
    with patch.object(
        api_mod.requests, "get",
        side_effect=requests.exceptions.ConnectionError("refused"),
    ), patch.object(api_mod.LOGGER, "warning") as warn:
        await client.get_lm_sensors_http(hass, "node1")
        await client.get_mounts(hass, "node1")

    assert warn.call_count == 2  # sensors + mounts are distinct endpoints


@pytest.mark.asyncio
async def test_success_returns_payload_no_warning():
    client = _client()
    hass = _Hass()
    with patch.object(
        api_mod.requests, "get", return_value=_ok_response({"disk": "nvme0"})
    ), patch.object(api_mod.LOGGER, "warning") as warn:
        result = await client.get_mounts(hass, "node1")

    assert result == {"disk": "nvme0"}
    assert not warn.called
