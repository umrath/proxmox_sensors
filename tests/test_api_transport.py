"""
Transport-Tests für den aiohttp-Umbau (v5.0.0).

Vorher lief jeder API-Call über `hass.async_add_executor_job` (proxmoxer/requests).
`asyncio.timeout` bricht dabei nur das await ab, nicht den Executor-Thread — ein
schlecht erreichbarer Node hat so den HA-weiten SyncWorker-Pool leergelaufen und
die ganze Instanz blockiert.

Jetzt: reiner aiohttp-Transport mit `ClientTimeout(total=…)` — hartes
Gesamtlimit, keine Threads, kein Leck.
"""

import asyncio
import aiohttp
import pytest
from unittest.mock import MagicMock, patch

import custom_components.proxmox_sensors.api as api_mod
from custom_components.proxmox_sensors.api import (
    ProxmoxClient,
    AuthenticationError,
    PermissionError as ProxmoxPermissionError,
    CannotConnect,
)


from tests.aiohttp_fakes import FakeResponse, attach, connect_error


def make_client(**kw):
    params = dict(
        host="pve.local",
        user="root@pam",
        token_id="ha",
        token_secret="sec",
        server_type="PVE",
        verify_ssl=False,
    )
    params.update(kw)
    return ProxmoxClient(**params)


# ===========================================================================
# URL / host handling
# ===========================================================================

class TestHostAndUrl:

    @pytest.mark.parametrize(
        "host,expected_host,expected_port",
        [
            ("pve.local", "pve.local", None),
            ("pve.local:8006", "pve.local", 8006),
            ("https://pve.local:8006", "pve.local", 8006),
            ("192.168.1.10", "192.168.1.10", None),
            ("[fe80::1]:8006", "[fe80::1]", 8006),
            ("[fe80::1]", "[fe80::1]", None),
            ("fe80::1", "[fe80::1]", None),  # bare IPv6 gets bracketed for the URL
        ],
    )
    def test_split_host_port(self, host, expected_host, expected_port):
        client = make_client(host=host)
        assert client._split_host_port() == (expected_host, expected_port)

    def test_pve_default_port(self):
        assert make_client()._api_base() == "https://pve.local:8006/api2/json"

    def test_pbs_default_port(self):
        client = make_client(server_type="PBS")
        assert client._api_base() == "https://pve.local:8007/api2/json"

    def test_embedded_port_wins_over_default(self):
        client = make_client(host="pve.local:9999")
        assert client._api_base() == "https://pve.local:9999/api2/json"

    def test_explicit_port_wins_over_embedded(self):
        client = make_client(host="pve.local:9999", port=8006)
        assert client._api_base() == "https://pve.local:8006/api2/json"


# ===========================================================================
# Auth
# ===========================================================================

class TestAuth:

    @pytest.mark.asyncio
    async def test_pve_token_header(self):
        client = make_client()
        session = attach(client, lambda m, u, k: FakeResponse(payload={"data": []}))
        await client.get(MagicMock(), "nodes")
        assert (
            session.calls[0]["headers"]["Authorization"]
            == "PVEAPIToken=root@pam!ha=sec"
        )

    @pytest.mark.asyncio
    async def test_pve_token_id_with_embedded_user_not_doubled(self):
        client = make_client(token_id="root@pam!ha")
        session = attach(client, lambda m, u, k: FakeResponse(payload={"data": []}))
        await client.get(MagicMock(), "nodes")
        assert (
            session.calls[0]["headers"]["Authorization"]
            == "PVEAPIToken=root@pam!ha=sec"
        )

    @pytest.mark.asyncio
    async def test_pbs_token_header_format_preserved(self):
        client = make_client(server_type="PBS")
        session = attach(client, lambda m, u, k: FakeResponse(payload={"data": []}))
        await client.pbs_get(MagicMock(), "admin/datastore")
        # Unchanged from the pre-5.0.0 implementation on purpose.
        assert (
            session.calls[0]["headers"]["Authorization"] == "PBSAPIToken root@pam!ha:sec"
        )

    @pytest.mark.asyncio
    async def test_password_auth_fetches_ticket_and_sends_cookie(self):
        client = make_client(token_id=None, token_secret=None, password="pw")

        def handler(method, url, kwargs):
            if "access/ticket" in url:
                return FakeResponse(
                    payload={"data": {"ticket": "PVE:tkt", "CSRFPreventionToken": "csrf"}}
                )
            return FakeResponse(payload={"data": [{"node": "n1"}]})

        session = attach(client, handler)
        result = await client.get(MagicMock(), "nodes")

        assert result == [{"node": "n1"}]
        ticket_call, data_call = session.calls[0], session.calls[1]
        assert "access/ticket" in ticket_call["url"]
        assert ticket_call["data"] == {"username": "root@pam", "password": "pw"}
        assert data_call["cookies"] == {"PVEAuthCookie": "PVE:tkt"}

    @pytest.mark.asyncio
    async def test_password_auth_sends_csrf_on_write_only(self):
        client = make_client(token_id=None, token_secret=None, password="pw")

        def handler(method, url, kwargs):
            if "access/ticket" in url:
                return FakeResponse(
                    payload={"data": {"ticket": "t", "CSRFPreventionToken": "csrf"}}
                )
            return FakeResponse(payload={"data": "ok"})

        session = attach(client, handler)
        await client.get(MagicMock(), "nodes")
        await client.post(MagicMock(), "nodes/n1/status", {"command": "reboot"})

        get_call = [c for c in session.calls if c["method"] == "GET"][0]
        write_call = [
            c for c in session.calls if c["method"] == "POST" and "status" in c["url"]
        ][0]
        assert "CSRFPreventionToken" not in get_call["headers"]
        assert write_call["headers"]["CSRFPreventionToken"] == "csrf"

    @pytest.mark.asyncio
    async def test_ticket_is_reused_across_calls(self):
        client = make_client(token_id=None, token_secret=None, password="pw")

        def handler(method, url, kwargs):
            if "access/ticket" in url:
                return FakeResponse(payload={"data": {"ticket": "t", "CSRFPreventionToken": "c"}})
            return FakeResponse(payload={"data": []})

        session = attach(client, handler)
        for _ in range(5):
            await client.get(MagicMock(), "nodes")

        logins = [c for c in session.calls if "access/ticket" in c["url"]]
        assert len(logins) == 1, "ticket must be cached, not re-fetched per call"

    @pytest.mark.asyncio
    async def test_concurrent_calls_trigger_exactly_one_login(self):
        """The auth lock must collapse a burst of parallel calls into one login."""
        client = make_client(token_id=None, token_secret=None, password="pw")

        def handler(method, url, kwargs):
            if "access/ticket" in url:
                return FakeResponse(payload={"data": {"ticket": "t", "CSRFPreventionToken": "c"}})
            return FakeResponse(payload={"data": []})

        session = attach(client, handler)
        await asyncio.gather(*(client.get(MagicMock(), "nodes") for _ in range(10)))

        logins = [c for c in session.calls if "access/ticket" in c["url"]]
        assert len(logins) == 1

    @pytest.mark.asyncio
    async def test_expired_ticket_is_refreshed(self):
        client = make_client(token_id=None, token_secret=None, password="pw")

        def handler(method, url, kwargs):
            if "access/ticket" in url:
                return FakeResponse(payload={"data": {"ticket": "t", "CSRFPreventionToken": "c"}})
            return FakeResponse(payload={"data": []})

        session = attach(client, handler)
        await client.get(MagicMock(), "nodes")
        client._ticket_expires = 0.0  # simulate expiry
        await client.get(MagicMock(), "nodes")

        logins = [c for c in session.calls if "access/ticket" in c["url"]]
        assert len(logins) == 2

    @pytest.mark.asyncio
    async def test_401_clears_ticket_so_next_call_relogins(self):
        client = make_client(token_id=None, token_secret=None, password="pw")

        def handler(method, url, kwargs):
            if "access/ticket" in url:
                return FakeResponse(payload={"data": {"ticket": "t", "CSRFPreventionToken": "c"}})
            return FakeResponse(status=401)

        attach(client, handler)
        assert await client.get(MagicMock(), "nodes") is None
        assert client._ticket is None

    @pytest.mark.asyncio
    async def test_bad_password_raises_authentication_error(self):
        client = make_client(token_id=None, token_secret=None, password="wrong")
        attach(client, lambda m, u, k: FakeResponse(status=401))
        with pytest.raises(AuthenticationError):
            await client.get(MagicMock(), "nodes", raise_errors=True)

    @pytest.mark.asyncio
    async def test_login_failure_does_not_raise_during_polling(self):
        """Polling contract is 'return None, never raise' — a failed login must
        degrade, not take the whole update cycle down."""
        client = make_client(token_id=None, token_secret=None, password="wrong")
        attach(client, lambda m, u, k: FakeResponse(status=401))
        assert await client.get(MagicMock(), "nodes") is None

    @pytest.mark.asyncio
    async def test_login_network_blip_does_not_raise_during_polling(self):
        client = make_client(token_id=None, token_secret=None, password="pw")
        attach(client, lambda m, u, k: connect_error())
        assert await client.get(MagicMock(), "nodes") is None

    @pytest.mark.asyncio
    async def test_failed_login_is_not_retried_once_per_call(self):
        """Regression: the auth lock only collapsed *successful* logins. On an
        unreachable node every call of a cycle queued on the lock and retried the
        login — 14 serialized attempts for one node."""
        client = make_client(token_id=None, token_secret=None, password="pw")
        logins = {"n": 0}

        def handler(method, url, kwargs):
            if "access/ticket" in url:
                logins["n"] += 1
            return connect_error()

        attach(client, handler)
        await asyncio.gather(
            *(client.get(MagicMock(), f"nodes/{i}") for i in range(14))
        )
        assert logins["n"] == 1, f"{logins['n']} login attempts for one cycle"

    @pytest.mark.asyncio
    async def test_login_is_retried_after_the_cooldown(self):
        client = make_client(token_id=None, token_secret=None, password="pw")
        logins = {"n": 0}

        def handler(method, url, kwargs):
            if "access/ticket" in url:
                logins["n"] += 1
            return connect_error()

        attach(client, handler)
        await client.get(MagicMock(), "nodes")
        client._auth_retry_after = 0.0  # cooldown elapsed
        await client.get(MagicMock(), "nodes")
        assert logins["n"] == 2

    @pytest.mark.asyncio
    async def test_successful_login_clears_the_cooldown(self):
        client = make_client(token_id=None, token_secret=None, password="pw")
        state = {"down": True}

        def handler(method, url, kwargs):
            if "access/ticket" in url:
                if state["down"]:
                    return connect_error()
                return FakeResponse(
                    payload={"data": {"ticket": "t", "CSRFPreventionToken": "c"}}
                )
            return FakeResponse(payload={"data": []})

        attach(client, handler)
        await client.get(MagicMock(), "nodes")          # fails, arms cooldown
        state["down"] = False
        client._auth_retry_after = 0.0
        assert await client.get(MagicMock(), "nodes") == []
        assert client._auth_retry_after == 0.0, "cooldown must be cleared on success"

    @pytest.mark.asyncio
    async def test_csrf_token_is_paired_with_its_own_ticket(self):
        """A concurrent refresh must not pair a fresh ticket with a stale CSRF."""
        client = make_client(token_id=None, token_secret=None, password="pw")
        issued = {"n": 0}

        def handler(method, url, kwargs):
            if "access/ticket" in url:
                issued["n"] += 1
                return FakeResponse(
                    payload={
                        "data": {
                            "ticket": f"tkt-{issued['n']}",
                            "CSRFPreventionToken": f"csrf-{issued['n']}",
                        }
                    }
                )
            return FakeResponse(payload={"data": "ok"})

        session = attach(client, handler)
        await client.post(MagicMock(), "nodes/n1/status", {"command": "reboot"})

        write = [c for c in session.calls if "status" in c["url"]][0]
        n = write["cookies"]["PVEAuthCookie"].split("-")[1]
        assert write["headers"]["CSRFPreventionToken"] == f"csrf-{n}"

    @pytest.mark.asyncio
    async def test_concurrent_401_cannot_produce_a_none_cookie(self):
        """A parallel 401 clears the cached ticket; the in-flight call must still
        send the ticket it obtained, never `PVEAuthCookie: None`."""
        client = make_client(token_id=None, token_secret=None, password="pw")

        def handler(method, url, kwargs):
            if "access/ticket" in url:
                return FakeResponse(payload={"data": {"ticket": "t", "CSRFPreventionToken": "c"}})
            client._ticket = None  # concurrent 401 wipes the cache mid-flight
            return FakeResponse(payload={"data": []})

        session = attach(client, handler)
        await asyncio.gather(*(client.get(MagicMock(), "nodes") for _ in range(5)))

        for call in session.calls:
            if call.get("cookies") is not None:
                assert call["cookies"]["PVEAuthCookie"] is not None


# ===========================================================================
# Timeout / no executor threads
# ===========================================================================

class TestTimeouts:

    @pytest.mark.asyncio
    async def test_every_request_carries_a_total_timeout(self):
        client = make_client()
        session = attach(client, lambda m, u, k: FakeResponse(payload={"data": []}))
        await client.get(MagicMock(), "nodes")

        timeout = session.calls[0]["timeout"]
        assert isinstance(timeout, aiohttp.ClientTimeout)
        assert timeout.total == api_mod.REQUEST_TIMEOUT

    @pytest.mark.asyncio
    async def test_timeout_returns_none_without_raising(self):
        client = make_client()
        attach(client, lambda m, u, k: asyncio.TimeoutError())
        assert await client.get(MagicMock(), "nodes") is None

    @pytest.mark.asyncio
    async def test_connect_error_returns_none(self):
        client = make_client()
        attach(client, lambda m, u, k: aiohttp.ClientConnectorError(MagicMock(), OSError("down")))
        assert await client.get(MagicMock(), "nodes") is None

    @pytest.mark.asyncio
    async def test_timeout_maps_to_cannot_connect_when_validating(self):
        client = make_client()
        attach(client, lambda m, u, k: asyncio.TimeoutError())
        with pytest.raises(CannotConnect):
            await client.get(MagicMock(), "nodes", raise_errors=True)

    @pytest.mark.asyncio
    async def test_no_executor_job_is_used(self):
        """The whole point of 5.0.0: no work is handed to HA's SyncWorker pool."""
        client = make_client()
        attach(client, lambda m, u, k: FakeResponse(payload={"data": []}))
        hass = MagicMock()
        await client.get(MagicMock(), "nodes")
        hass.async_add_executor_job.assert_not_called()


# ===========================================================================
# Response handling
# ===========================================================================

class TestResponses:

    @pytest.mark.asyncio
    async def test_data_envelope_is_unwrapped(self):
        client = make_client()
        attach(client, lambda m, u, k: FakeResponse(payload={"data": {"status": "online"}}))
        assert await client.get(MagicMock(), "nodes/n1/status") == {"status": "online"}

    @pytest.mark.asyncio
    async def test_payload_without_envelope_passes_through(self):
        client = make_client()
        attach(client, lambda m, u, k: FakeResponse(payload={"status": "online"}))
        assert await client.get(MagicMock(), "x") == {"status": "online"}

    @pytest.mark.asyncio
    async def test_403_returns_none(self):
        client = make_client()
        attach(client, lambda m, u, k: FakeResponse(status=403))
        assert await client.get(MagicMock(), "nodes") is None

    @pytest.mark.asyncio
    async def test_403_raises_permission_error_when_validating(self):
        client = make_client()
        attach(client, lambda m, u, k: FakeResponse(status=403))
        with pytest.raises(ProxmoxPermissionError):
            await client.get(MagicMock(), "nodes", raise_errors=True)

    @pytest.mark.asyncio
    async def test_500_returns_none_and_logs(self):
        client = make_client()
        attach(client, lambda m, u, k: FakeResponse(status=500, text="boom"))
        with patch.object(api_mod.LOGGER, "error") as err:
            assert await client.get(MagicMock(), "nodes") is None
        assert err.called

    @pytest.mark.asyncio
    async def test_pve_post_sends_form_encoded_body(self):
        client = make_client()
        session = attach(client, lambda m, u, k: FakeResponse(payload={"data": "ok"}))
        await client.post(MagicMock(), "nodes/n1/status", {"command": "reboot"})
        call = session.calls[0]
        assert call["data"] == {"command": "reboot"}  # form, like proxmoxer sent
        assert "json" not in call

    @pytest.mark.asyncio
    async def test_pbs_post_sends_json_body(self):
        client = make_client(server_type="PBS")
        session = attach(client, lambda m, u, k: FakeResponse(payload={"data": "ok"}))
        await client.pbs_post(MagicMock(), "admin/datastore/x/gc", {"a": 1})
        assert session.calls[0]["json"] == {"a": 1}


# ===========================================================================
# TLS verification (replaces the old urllib3-scoping test)
# ===========================================================================

class TestTlsVerification:

    def test_verify_ssl_false_is_passed_to_session_factory(self):
        client = make_client(verify_ssl=False)
        with patch.object(api_mod, "async_get_clientsession") as factory:
            client._session(MagicMock())
        assert factory.call_args.kwargs["verify_ssl"] is False

    def test_verify_ssl_true_is_passed_to_session_factory(self):
        client = make_client(verify_ssl=True)
        with patch.object(api_mod, "async_get_clientsession") as factory:
            client._session(MagicMock())
        assert factory.call_args.kwargs["verify_ssl"] is True
