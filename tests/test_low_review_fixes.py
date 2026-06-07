"""
Tests for second-review LOW fixes.

L1 — PBSLastActionSensor exposes its value via native_value (not state).
L2 — sidecar (port 9000) URLs strip an embedded API port from the host.
L3 — WOL MAC validation rejects non-hex characters, not just wrong length.
L4 — pbs_auth_status keys off an actual version, not dict truthiness.
"""

import inspect
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# L1 — native_value instead of state
# ---------------------------------------------------------------------------

class TestLastActionNativeValue:
    def test_uses_native_value_not_state(self):
        import custom_components.proxmox_sensors.sensor.sensor_last_action as mod

        assert hasattr(mod.PBSLastActionSensor, "native_value")
        src = inspect.getsource(mod.PBSLastActionSensor)
        assert "def native_value" in src
        assert "def state" not in src, (
            "SensorEntity must expose its value via native_value, not state (L1)"
        )


# ---------------------------------------------------------------------------
# L2 — sidecar URL strips embedded port
# ---------------------------------------------------------------------------

class TestSidecarHost:
    def _client(self, host):
        from custom_components.proxmox_sensors.api import ProxmoxClient

        return ProxmoxClient(host=host, user="u", password="p")

    def test_plain_host_unchanged(self):
        assert self._client("pve.local")._sidecar_host() == "pve.local"

    def test_ipv4_unchanged(self):
        assert self._client("192.168.1.10")._sidecar_host() == "192.168.1.10"

    def test_host_with_port_is_stripped(self):
        assert self._client("pve.local:8006")._sidecar_host() == "pve.local"

    def test_ipv4_with_port_is_stripped(self):
        assert self._client("192.168.1.10:8006")._sidecar_host() == "192.168.1.10"

    def test_bracketed_ipv6_with_port_is_stripped(self):
        assert self._client("[fe80::1]:8006")._sidecar_host() == "[fe80::1]"

    def test_bracketed_ipv6_without_port_unchanged(self):
        assert self._client("[fe80::1]")._sidecar_host() == "[fe80::1]"


# ---------------------------------------------------------------------------
# L3 — MAC hex validation
# ---------------------------------------------------------------------------

class TestMacHexValidation:
    def _get_wake_handler(self):
        import custom_components.proxmox_sensors.services as services_mod

        registered = {}

        hass = MagicMock()
        hass.data = {}
        hass.services.async_register = MagicMock(
            side_effect=lambda domain, name, handler, *a, **k: registered.__setitem__(
                name, handler
            )
        )
        hass.services.has_service = MagicMock(return_value=False)

        entry = MagicMock()
        entry.data = {}
        services_mod.register_services(hass, entry)
        return registered["wake_node"], hass

    @pytest.mark.asyncio
    async def test_non_hex_mac_rejected(self):
        handler, _ = self._get_wake_handler()
        call = MagicMock()
        # 12 chars after stripping separators, but not hex
        call.data = {"node": "pve", "mac": "gg:hh:ii:jj:kk:ll"}
        with pytest.raises(ValueError):
            await handler(call)

    @pytest.mark.asyncio
    async def test_valid_mac_accepted(self):
        handler, hass = self._get_wake_handler()
        hass.services.async_call = MagicMock(return_value=_async_none())
        call = MagicMock()
        call.data = {"node": "pve", "mac": "AA:BB:CC:DD:EE:FF"}
        # Should not raise on validation (the WOL call itself is mocked)
        await handler(call)


def _async_none():
    async def _coro():
        return None

    return _coro()


# ---------------------------------------------------------------------------
# L4 — pbs_auth_status keys off version presence
# ---------------------------------------------------------------------------

class TestPbsAuthStatusSource:
    def test_auth_status_checks_version_field(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        src = inspect.getsource(coord_mod)
        assert 'version_info.get("version")' in src, (
            "pbs_auth_status must key off an actual version, not dict truthiness (L4)"
        )
        assert '"OK" if version_info else "ERROR"' not in src, (
            "dict-truthiness auth check should be gone (L4)"
        )
