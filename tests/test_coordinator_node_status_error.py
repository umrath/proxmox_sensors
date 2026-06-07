"""
Test C2: a node_status fetch failure must be logged, not silently swallowed.

Bug: results[0] (node status) was only checked with isinstance(..., dict).
On an Exception the code fell through to result["node"] = {"status": "unknown"}
with no warning, masking the failure as if it were valid data.

Fix: detect the Exception case explicitly and log a warning.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def _make_pve_client():
    client = MagicMock()
    client._server_type = "PVE"
    # cluster_results
    client.get_cluster_resources = AsyncMock(return_value=[])
    client.get_cluster_status = AsyncMock(return_value={})
    client.get_cluster_ha_status = AsyncMock(return_value={})
    client.get_cluster_firewall_options = AsyncMock(return_value={})
    # parallel node tasks
    client.get_node_updates = AsyncMock(return_value=[])
    client.get_node_network = AsyncMock(return_value=[])
    client.get_cluster_tasks = AsyncMock(return_value=[])
    client.get_vms = AsyncMock(return_value=[])
    client.get_containers = AsyncMock(return_value=[])
    client.get_storages = AsyncMock(return_value=[])
    client.get_zfs_pools = AsyncMock(return_value=[])
    client.get_disks = AsyncMock(return_value=[])
    client.get_mounts = AsyncMock(return_value={})
    return client


def _make_entry():
    entry = MagicMock()
    entry.data = {
        "node": "node1",
        "platform_type": "PVE",
        # disable the optional sidecar tasks to keep the gather minimal
        "enable_lm_sensors": False,
        "enable_smart_monitoring": False,
        "enable_memory_monitoring": False,
        "enable_physical_disks": False,
    }
    entry.options = {
        "enable_memory_monitoring": False,
    }
    return entry


class TestNodeStatusErrorLogged:

    @pytest.mark.asyncio
    async def test_node_status_exception_sets_unknown_and_warns(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        client = _make_pve_client()
        client.get_node_status = AsyncMock(side_effect=RuntimeError("boom"))

        hass = MagicMock()
        entry = _make_entry()

        coordinator = await coord_mod.create_proxmox_coordinator(hass, entry, client)

        with patch.object(coord_mod._LOGGER, "warning") as mock_warn:
            result = await coordinator.update_method()

        assert result["node"]["status"] == "unknown"
        assert mock_warn.called, (
            "A node_status fetch failure must log a warning — C2 not fixed"
        )
        # The warning message must mention node status
        logged = " ".join(str(a) for call in mock_warn.call_args_list for a in call.args)
        assert "node status" in logged.lower()

    @pytest.mark.asyncio
    async def test_node_status_success_no_warning(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        client = _make_pve_client()
        client.get_node_status = AsyncMock(
            return_value={"data": {"status": "online", "cpu": 0.25}}
        )

        hass = MagicMock()
        entry = _make_entry()

        coordinator = await coord_mod.create_proxmox_coordinator(hass, entry, client)

        with patch.object(coord_mod._LOGGER, "warning") as mock_warn:
            result = await coordinator.update_method()

        assert result["node"]["status"] == "online"
        assert result["node"]["cpu"] == 0.25
        assert not mock_warn.called
