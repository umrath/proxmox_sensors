"""
Tests für _async_manage_cluster_entry() in __init__.py.

Bug L3: Die Funktion baut cluster_data zusammen, ruft aber nie
hass.config_entries.flow.async_init() auf — der CLUSTER-Entry wird
also nie angelegt.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, call

from custom_components.proxmox_sensors import _async_manage_cluster_entry
from custom_components.proxmox_sensors.const import (
    DOMAIN,
    CONF_HOST,
    CONF_USER,
    CONF_PASSWORD,
    CONF_TOKEN_ID,
    CONF_TOKEN_SECRET,
    CONF_NODE,
    CONF_PLATFORM_TYPE,
    CONF_VERIFY_SSL,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_pve_entry(host="10.0.0.1", user="root@pam", node="pve1",
                    token_id="mytoken", token_secret="secret"):
    entry = MagicMock()
    entry.entry_id = "pve_entry_id"
    entry.data = {
        CONF_HOST: host,
        CONF_USER: user,
        CONF_NODE: node,
        CONF_TOKEN_ID: token_id,
        CONF_TOKEN_SECRET: token_secret,
        CONF_VERIFY_SSL: False,
    }
    return entry


def _make_hass(existing_cluster_entries=None):
    hass = MagicMock()
    hass.config_entries = MagicMock()
    hass.config_entries.async_entries = MagicMock(
        return_value=existing_cluster_entries or []
    )
    hass.config_entries.async_remove = AsyncMock()
    hass.config_entries.flow = MagicMock()
    hass.config_entries.flow.async_init = AsyncMock(return_value=MagicMock())
    hass.async_create_task = MagicMock()
    return hass


# ---------------------------------------------------------------------------
# L3: CLUSTER Entry niemals erstellt
# ---------------------------------------------------------------------------

class TestClusterEntryCreation:
    """Bug L3: _async_manage_cluster_entry must schedule creation of a CLUSTER entry."""

    @pytest.mark.asyncio
    async def test_creates_cluster_entry_when_none_exists(self):
        """If no CLUSTER entry exists and enable_cluster=True, one must be created."""
        hass = _make_hass(existing_cluster_entries=[])
        pve = _make_pve_entry()

        await _async_manage_cluster_entry(hass, pve, "my-cluster", enable_cluster=True)

        # Must schedule entry creation
        hass.async_create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_cluster_data_contains_correct_fields(self):
        """Created entry must carry all credentials and the cluster_name."""
        hass = _make_hass()
        pve = _make_pve_entry(host="10.0.0.1", user="root@pam", node="pve1",
                               token_id="tok", token_secret="sec")

        await _async_manage_cluster_entry(hass, pve, "alpha", enable_cluster=True)

        hass.async_create_task.assert_called_once()
        # The coroutine passed to async_create_task wraps flow.async_init —
        # we verify flow.async_init is called with the right domain and data.
        # async_create_task receives a coroutine; we call it here to inspect.
        coro = hass.async_create_task.call_args[0][0]
        await coro

        _, kwargs = hass.config_entries.flow.async_init.call_args
        data = kwargs.get("data") or hass.config_entries.flow.async_init.call_args[0][1] if len(hass.config_entries.flow.async_init.call_args[0]) > 1 else hass.config_entries.flow.async_init.call_args[1].get("data")

        # The init is called as async_init(DOMAIN, context=..., data=...)
        assert hass.config_entries.flow.async_init.called
        init_call = hass.config_entries.flow.async_init.call_args
        passed_domain = init_call[0][0]
        passed_data = init_call[1].get("data", {})

        assert passed_domain == DOMAIN
        assert passed_data.get(CONF_PLATFORM_TYPE) == "CLUSTER"
        assert passed_data.get("cluster_name") == "alpha"
        assert passed_data.get(CONF_HOST) == "10.0.0.1"
        assert passed_data.get(CONF_USER) == "root@pam"
        assert passed_data.get("parent_entry_id") == "pve_entry_id"

    @pytest.mark.asyncio
    async def test_does_not_create_entry_when_already_exists(self):
        """If a CLUSTER entry for this cluster already exists, skip creation."""
        existing = MagicMock()
        existing.data = {CONF_PLATFORM_TYPE: "CLUSTER", "cluster_name": "my-cluster"}
        hass = _make_hass(existing_cluster_entries=[existing])
        pve = _make_pve_entry()

        await _async_manage_cluster_entry(hass, pve, "my-cluster", enable_cluster=True)

        hass.async_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_does_not_create_entry_when_enable_cluster_false(self):
        hass = _make_hass()
        pve = _make_pve_entry()

        await _async_manage_cluster_entry(hass, pve, "my-cluster", enable_cluster=False)

        hass.async_create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_removes_existing_entry_when_enable_cluster_false(self):
        """Disabling cluster must remove the existing CLUSTER entry."""
        existing = MagicMock()
        existing.entry_id = "cluster_entry_id"
        existing.data = {
            CONF_PLATFORM_TYPE: "CLUSTER",
            "cluster_name": "my-cluster",
            "parent_entry_id": "pve_entry_id",
        }
        hass = _make_hass(existing_cluster_entries=[existing])
        pve = _make_pve_entry()

        await _async_manage_cluster_entry(hass, pve, "my-cluster", enable_cluster=False)

        hass.config_entries.async_remove.assert_called_once_with("cluster_entry_id")
