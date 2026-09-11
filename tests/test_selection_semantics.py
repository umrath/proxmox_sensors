"""
None vs. [] bei den Auswahl-Listen (v5.0.3).

Bug: `if not selected_values` warf zwei Zustände zusammen —
"nichts gespeichert" (Altbestand) und "bewusst alles abgewählt". Wer in den
Optionen alle VMs abwählte, sah sie trotzdem alle.

Zusätzlich widersprachen sich die Ebenen beim Storage: der Coordinator
behandelte `[]` als "alle", die Entity-Erstellung als "keine".

Semantik jetzt einheitlich:
* None        -> nichts gespeichert (Altbestand): alles anzeigen
* []          -> bewusst abgewählt: nichts anzeigen
* Liste       -> nur das Gewählte
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.proxmox_sensors.logic.guest_keys import matches_selected_guest


# ===========================================================================
# Zentrale Semantik
# ===========================================================================

class TestThreeStateSemantics:

    @pytest.mark.parametrize("vmid", [101, "101"])
    def test_none_shows_everything(self, vmid):
        assert matches_selected_guest(None, "node1", vmid)

    @pytest.mark.parametrize("vmid", [101, "101"])
    def test_empty_shows_nothing(self, vmid):
        assert not matches_selected_guest([], "node1", vmid)

    def test_explicit_list_still_filters(self):
        assert matches_selected_guest(["node1:101"], "node1", 101)
        assert not matches_selected_guest(["node1:101"], "node1", 202)

    def test_legacy_raw_vmid_selection_still_works(self):
        """Altbestand speicherte nur die VMID, nicht den node:vmid-Key."""
        assert matches_selected_guest(["101"], "node1", 101)
        assert not matches_selected_guest(["101"], "node1", 202)


# ===========================================================================
# Storage-Filter im Coordinator (war gegenläufig zur Entity-Erstellung)
# ===========================================================================

def _pve_client(storages):
    client = MagicMock()
    client._server_type = "PVE"
    client.get_cluster_resources = AsyncMock(return_value=[])
    client.get_cluster_status = AsyncMock(return_value={})
    client.get_cluster_ha_status = AsyncMock(return_value={})
    client.get_cluster_firewall_options = AsyncMock(return_value={})
    client.get_node_status = AsyncMock(return_value={"data": {"status": "online"}})
    client.get_node_updates = AsyncMock(return_value=[])
    client.get_node_network = AsyncMock(return_value=[])
    client.get_cluster_tasks = AsyncMock(return_value=[])
    client.get_vms = AsyncMock(return_value=[])
    client.get_containers = AsyncMock(return_value=[])
    client.get_storages = AsyncMock(return_value=storages)
    client.get_zfs_pools = AsyncMock(return_value=[])
    client.get_disks = AsyncMock(return_value=[])
    client.get_mounts = AsyncMock(return_value={})
    client.get_replication = AsyncMock(return_value=[])
    return client


def _entry(**extra):
    entry = MagicMock()
    entry.data = {
        "node": "node1",
        "platform_type": "PVE",
        "enable_lm_sensors": False,
        "enable_smart_monitoring": False,
        "enable_memory_monitoring": False,
        "enable_physical_disks": False,
        **extra,
    }
    entry.options = {"enable_memory_monitoring": False}
    return entry


STORAGES = [{"storage": "local"}, {"storage": "nvme-pool"}]


class TestCoordinatorStorageSelection:

    @pytest.mark.asyncio
    async def test_no_selection_keeps_all_storages(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _entry(), _pve_client(STORAGES)
        )
        result = await coordinator.update_method()
        assert set(result["storage"]) == {"local", "nvme-pool"}

    @pytest.mark.asyncio
    async def test_empty_selection_keeps_no_storage(self):
        """Vorher: `not selected_storage` -> alle. Die Entity-Erstellung
        filterte sie danach wieder weg — die Ebenen widersprachen sich."""
        import custom_components.proxmox_sensors.coordinator as coord_mod

        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _entry(selected_storage=[]), _pve_client(STORAGES)
        )
        result = await coordinator.update_method()
        assert result["storage"] == {}

    @pytest.mark.asyncio
    async def test_explicit_selection_filters(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _entry(selected_storage=["local"]), _pve_client(STORAGES)
        )
        result = await coordinator.update_method()
        assert set(result["storage"]) == {"local"}


# ===========================================================================
# Gäste-Filter im Coordinator
# ===========================================================================

class TestCoordinatorGuestSelection:

    @staticmethod
    def _client_with_vms():
        client = _pve_client([])
        client.get_vms = AsyncMock(
            return_value=[
                {"vmid": 101, "name": "a", "status": "running"},
                {"vmid": 202, "name": "b", "status": "running"},
            ]
        )
        return client

    @pytest.mark.asyncio
    async def test_no_selection_keeps_all_vms(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _entry(), self._client_with_vms()
        )
        result = await coordinator.update_method()
        assert set(result["vms"]) == {"node1:101", "node1:202"}

    @pytest.mark.asyncio
    async def test_empty_selection_keeps_no_vms(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _entry(selected_vms=[]), self._client_with_vms()
        )
        result = await coordinator.update_method()
        assert result["vms"] == {}

    @pytest.mark.asyncio
    async def test_explicit_selection_filters_vms(self):
        import custom_components.proxmox_sensors.coordinator as coord_mod

        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _entry(selected_vms=["node1:101"]), self._client_with_vms()
        )
        result = await coordinator.update_method()
        assert set(result["vms"]) == {"node1:101"}
