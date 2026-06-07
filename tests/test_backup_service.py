"""
Tests für services.py — backup_all und create_vzdump_backup.

L1: limited_task ist in services.py nicht definiert → NameError bei backup_all
R1: coordinator.data kann None sein → AttributeError / TypeError
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, call

from custom_components.proxmox_sensors.coordinator import _build_vms_dict, _build_cts_dict
from custom_components.proxmox_sensors.services import register_services
from custom_components.proxmox_sensors.const import DOMAIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass(coordinator_data, node="node1"):
    """Build a minimal hass mock with a coordinator that has data."""
    coordinator = MagicMock()
    coordinator.data = coordinator_data

    client = MagicMock()
    client.start_vzdump = AsyncMock(return_value="UPID:node1:backup1")

    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"node": node}

    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "test_entry": {
                "client": client,
                "coordinator": coordinator,
                "node": node,
            }
        }
    }

    registered = {}
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = lambda domain, name, handler: registered.__setitem__(
        name, handler
    )

    register_services(hass, entry)

    return hass, client, registered


def _call(data: dict):
    """Build a fake ServiceCall."""
    sc = MagicMock()
    sc.data = data
    return sc


# ---------------------------------------------------------------------------
# L1: limited_task NameError
# ---------------------------------------------------------------------------

class TestBackupAllL1Bug:
    """Bug L1: backup_all crashes with NameError because limited_task is undefined."""

    @pytest.mark.asyncio
    async def test_backup_all_does_not_crash_with_name_error(self):
        """Calling backup_all must not raise NameError."""
        vms = _build_vms_dict(
            [{"vmid": 101, "status": "running"}], [], ["101"], "node1"
        )
        _, client, registered = _make_hass({"vms": vms, "cts": {}})

        handler = registered["backup_all"]
        sc = _call({
            "node": "node1",
            "storage": "local",
            "include_vms": True,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        })

        # Must complete without NameError or any other unexpected exception
        await handler(sc)

    @pytest.mark.asyncio
    async def test_backup_all_calls_start_vzdump_for_each_vm(self):
        vms = _build_vms_dict(
            [{"vmid": 101, "status": "running"}, {"vmid": 102, "status": "running"}],
            [], ["101", "102"], "node1",
        )
        _, client, registered = _make_hass({"vms": vms, "cts": {}})

        await registered["backup_all"](_call({
            "node": "node1",
            "storage": "local",
            "include_vms": True,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }))

        assert client.start_vzdump.call_count == 2

    @pytest.mark.asyncio
    async def test_backup_all_calls_start_vzdump_for_cts(self):
        cts = _build_cts_dict(
            [{"vmid": 201, "status": "running"}], [], ["201"], "node1"
        )
        _, client, registered = _make_hass({"vms": {}, "cts": cts})

        await registered["backup_all"](_call({
            "node": "node1",
            "storage": "local",
            "include_vms": False,
            "include_cts": True,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }))

        assert client.start_vzdump.call_count == 1
        _, kwargs = client.start_vzdump.call_args
        assert str(kwargs.get("vmid", "")) == "201"

    @pytest.mark.asyncio
    async def test_backup_all_skips_migrated_vms(self):
        vms = _build_vms_dict(
            [],
            [{"type": "qemu", "vmid": 101, "node": "node2", "status": "running"}],
            ["101"], "node1",
        )
        _, client, registered = _make_hass({"vms": vms, "cts": {}})

        await registered["backup_all"](_call({
            "node": "node1",
            "storage": "local",
            "include_vms": True,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }))

        client.start_vzdump.assert_not_called()

    @pytest.mark.asyncio
    async def test_backup_all_no_targets_logs_warning_and_returns(self):
        """If no targets match, should log warning and not call vzdump."""
        _, client, registered = _make_hass({"vms": {}, "cts": {}})

        await registered["backup_all"](_call({
            "node": "node1",
            "storage": "local",
            "include_vms": True,
            "include_cts": True,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }))

        client.start_vzdump.assert_not_called()

    @pytest.mark.asyncio
    async def test_backup_all_missing_include_flags_returns_early(self):
        """backup_all without include_vms or include_cts must return silently."""
        vms = _build_vms_dict(
            [{"vmid": 101, "status": "running"}], [], ["101"], "node1"
        )
        _, client, registered = _make_hass({"vms": vms, "cts": {}})

        await registered["backup_all"](_call({
            "node": "node1",
            "storage": "local",
            "include_vms": False,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }))

        client.start_vzdump.assert_not_called()


# ---------------------------------------------------------------------------
# R1: coordinator.data is None
# ---------------------------------------------------------------------------

class TestBackupAllCoordinatorDataNone:
    """Bug R1: backup_all must not crash when coordinator.data is None."""

    @pytest.mark.asyncio
    async def test_backup_all_with_coordinator_data_none_does_not_crash(self):
        _, client, registered = _make_hass(coordinator_data=None)

        # Must not raise TypeError or AttributeError
        await registered["backup_all"](_call({
            "node": "node1",
            "storage": "local",
            "include_vms": True,
            "include_cts": True,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }))

        client.start_vzdump.assert_not_called()
