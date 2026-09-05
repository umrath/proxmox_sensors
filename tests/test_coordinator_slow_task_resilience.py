"""
Resilienz gegen langsame/hängende API-Calls (v4.2.1).

Bug: Ein einziger hängender PVE-Call ließ den geteilten Outer-Timeout feuern,
der die gesamte gather() abbrach -> UpdateFailed -> alle ~120 Entitäten eines
Knotens gleichzeitig `unavailable`.

Fix 1: Per-Task-Timeout (`limited_task` mit eigenem `asyncio.timeout`) -> ein
hängender Call wird zu einer TimeoutError in `results`, die übrigen Calls
befüllen weiter.
Fix 2: `UpdateFailed` nur bei Totalausfall. Existieren Vorwerte
(`coordinator.data`), werden diese behalten statt zu flappen.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def _make_pve_client():
    client = MagicMock()
    client._server_type = "PVE"
    client.get_cluster_resources = AsyncMock(return_value=[])
    client.get_cluster_status = AsyncMock(return_value={})
    client.get_cluster_ha_status = AsyncMock(return_value={})
    client.get_cluster_firewall_options = AsyncMock(return_value={})
    client.get_node_status = AsyncMock(
        return_value={"data": {"status": "online", "cpu": 0.25}}
    )
    client.get_node_updates = AsyncMock(return_value=[])
    client.get_node_network = AsyncMock(return_value=[])
    client.get_cluster_tasks = AsyncMock(return_value=[])
    client.get_vms = AsyncMock(return_value=[])
    client.get_containers = AsyncMock(return_value=[])
    client.get_storages = AsyncMock(return_value=[])
    client.get_zfs_pools = AsyncMock(return_value=[])
    client.get_disks = AsyncMock(return_value=[])
    client.get_mounts = AsyncMock(return_value={})
    client.get_replication = AsyncMock(return_value=[])
    return client


def _make_entry():
    entry = MagicMock()
    entry.data = {
        "node": "node1",
        "platform_type": "PVE",
        "enable_lm_sensors": False,
        "enable_smart_monitoring": False,
        "enable_memory_monitoring": False,
        "enable_physical_disks": False,
    }
    entry.options = {"enable_memory_monitoring": False}
    return entry


async def _hang(*args, **kwargs):
    # Longer than any per-task timeout used in these tests.
    await asyncio.sleep(30)


# ===========================================================================
# Fix 1 — one hang must not discard the other results
# ===========================================================================

class TestPerTaskTimeoutIsolatesHang:

    @pytest.mark.asyncio
    async def test_hanging_call_does_not_fail_whole_update(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        client = _make_pve_client()
        client.get_storages = AsyncMock(side_effect=_hang)

        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _make_entry(), client
        )

        # Small per-task timeout so the hang fails fast; generous outer net.
        with patch.object(coord_mod, "_TASK_TIMEOUT", 0.05), patch.object(
            coord_mod, "_OUTER_TIMEOUT", 45
        ):
            result = await coordinator.update_method()

        # Update returned instead of raising, and the good results survived the
        # storage hang.
        assert isinstance(result, dict)
        assert result["node"]["status"] == "online"
        assert result["node"]["cpu"] == 0.25

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "method", ["get_storages", "get_vms", "get_containers", "get_disks"]
    )
    async def test_any_single_hang_is_isolated(self, method):
        """Each of the crash-prone result consumers (storages / vms / cts /
        disks) must tolerate a hung call without failing the whole update."""
        import custom_components.proxmox_sensors.coordinator as coord_mod

        client = _make_pve_client()
        setattr(client, method, AsyncMock(side_effect=_hang))

        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _make_entry(), client
        )

        with patch.object(coord_mod, "_TASK_TIMEOUT", 0.05), patch.object(
            coord_mod, "_OUTER_TIMEOUT", 45
        ):
            result = await coordinator.update_method()

        assert result["node"]["status"] == "online"
        # The hung endpoint degrades to an empty collection, not a crash.
        assert isinstance(result.get("vms"), dict)
        assert isinstance(result.get("cts"), dict)
        assert isinstance(result.get("storage"), dict)

    @pytest.mark.asyncio
    async def test_no_hang_still_works(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        client = _make_pve_client()
        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _make_entry(), client
        )
        result = await coordinator.update_method()
        assert result["node"]["status"] == "online"


# ===========================================================================
# Fix 2 — total-cycle failure keeps previous data instead of flapping
# ===========================================================================

class TestUpdateFailedOnlyOnTotalFailure:

    @pytest.mark.asyncio
    async def test_keeps_previous_data_when_outer_timeout_trips(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        client = _make_pve_client()
        client.get_storages = AsyncMock(side_effect=_hang)

        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _make_entry(), client
        )
        previous = {"server_type": "PVE", "node": {"status": "online"}, "vms": {}}
        coordinator.data = previous

        # Outer net trips before the per-task timeout -> whole gather cancelled.
        with patch.object(coord_mod, "_OUTER_TIMEOUT", 0.05), patch.object(
            coord_mod, "_TASK_TIMEOUT", 30
        ), patch.object(coord_mod._LOGGER, "warning") as mock_warn:
            result = await coordinator.update_method()

        assert result is previous, "previous data must be kept, not discarded"
        assert mock_warn.called

    @pytest.mark.asyncio
    async def test_raises_updatefailed_when_no_previous_data(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod
        from homeassistant.helpers.update_coordinator import UpdateFailed

        client = _make_pve_client()
        client.get_storages = AsyncMock(side_effect=_hang)

        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _make_entry(), client
        )
        coordinator.data = None  # first update, nothing has ever succeeded

        with patch.object(coord_mod, "_OUTER_TIMEOUT", 0.05), patch.object(
            coord_mod, "_TASK_TIMEOUT", 30
        ):
            with pytest.raises(UpdateFailed):
                await coordinator.update_method()


# ===========================================================================
# Cluster coordinator — bekam die 4.2.1-Behandlung erst in 5.0.0
# ===========================================================================

class TestClusterCoordinatorKeepsPreviousData:
    """Der Cluster-Coordinator warf bis 5.0.0 bedingungslos UpdateFailed.

    Erreicht wird der Pfad nur, wenn der Fehler NICHT von
    `gather(return_exceptions=True)` eingefangen wird — also beim äußeren
    Timeout oder einem Fehler in der Ergebnisverarbeitung.
    """

    @staticmethod
    def _client_failing_outside_gather():
        client = MagicMock()
        for name in (
            "get_cluster_status",
            "get_cluster_ha_status",
            "get_cluster_firewall_options",
            "get_backup_jobs",
            "get_cluster_tasks",
        ):
            setattr(client, name, AsyncMock(return_value={}))
        # Sync raise: happens while building the gather arguments, inside the try.
        client.get_cluster_resources = MagicMock(side_effect=RuntimeError("boom"))
        return client

    @staticmethod
    def _cluster_entry():
        entry = MagicMock()
        entry.data = {"cluster_name": "c1"}
        return entry

    @pytest.mark.asyncio
    async def test_keeps_previous_data_instead_of_flapping(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        coordinator = await coord_mod.create_cluster_coordinator(
            MagicMock(), self._cluster_entry(), self._client_failing_outside_gather()
        )
        previous = {"server_type": "CLUSTER", "cluster_status": {"quorate": 1}}
        coordinator.data = previous

        assert await coordinator.update_method() is previous

    @pytest.mark.asyncio
    async def test_raises_updatefailed_without_previous_data(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod
        from homeassistant.helpers.update_coordinator import UpdateFailed

        coordinator = await coord_mod.create_cluster_coordinator(
            MagicMock(), self._cluster_entry(), self._client_failing_outside_gather()
        )
        coordinator.data = None

        with pytest.raises(UpdateFailed):
            await coordinator.update_method()

    @pytest.mark.asyncio
    async def test_per_call_failures_degrade_without_touching_the_fallback(self):
        """Einzelne fehlschlagende Calls fängt gather() ab — der Zyklus liefert
        ein normales Ergebnis mit leeren Werten, kein UpdateFailed."""
        import custom_components.proxmox_sensors.coordinator as coord_mod

        client = MagicMock()
        for name in (
            "get_cluster_resources",
            "get_cluster_status",
            "get_cluster_ha_status",
            "get_cluster_firewall_options",
            "get_backup_jobs",
            "get_cluster_tasks",
        ):
            setattr(client, name, AsyncMock(side_effect=RuntimeError("down")))

        coordinator = await coord_mod.create_cluster_coordinator(
            MagicMock(), self._cluster_entry(), client
        )
        coordinator.data = None
        result = await coordinator.update_method()

        assert result["cluster_resources"] == []
        assert result["cluster_status"] == {}
