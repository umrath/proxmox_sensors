"""
Auswahl-Semantik auf Entity-Ebene (v5.0.3).

Die Coverage-Messung zeigte: `sensor/__init__.py` und `button.py` waren bei den
in 5.0.3 geänderten Zeilen praktisch ungetestet. Kritisch ist dort
`st_name not in selected_storage` — mit `selected_storage = None` (neuer
Default) wäre das ohne Guard ein `TypeError` beim Setup und es entstünde
**keine einzige** Entität.

Diese Tests fahren `async_setup_entry` echt und zählen die Entitäten.
"""

import pytest
from unittest.mock import MagicMock

from custom_components.proxmox_sensors.const import DOMAIN
import custom_components.proxmox_sensors.sensor as sensor_mod
import custom_components.proxmox_sensors.button as button_mod


STORAGES = {
    "local": {
        "storage": "local",
        "type": "dir",
        "active": 1,
        "total": 100,
        "used": 10,
        "avail": 90,
    },
    "nvme-pool": {
        "storage": "nvme-pool",
        "type": "zfspool",
        "active": 1,
        "total": 200,
        "used": 20,
        "avail": 180,
    },
}

VMS = {
    "node1:101": {"vmid": 101, "name": "vm-a", "status": "running"},
    "node1:202": {"vmid": 202, "name": "vm-b", "status": "running"},
}

CTS = {
    "node1:301": {"vmid": 301, "name": "ct-a", "status": "running"},
}


def _coordinator():
    coord = MagicMock()
    coord.config_entry.data = {"server_id": "node1"}
    coord.data = {
        "server_type": "PVE",
        "node": {"status": "online"},
        "storage": STORAGES,
        "vms": VMS,
        "cts": CTS,
        "hardware": {},
        "smart": {},
        "memory": {},
        "node_disks": [],
        "disks": {},
        "mounts": {},
        "zfs_pools": {},
        "tasks": [],
        "cluster_resources": [],
        "replication": {},
        "node_updates": {"available": False, "count": 0, "packages": []},
    }
    return coord


def _hass(coordinator, client=None):
    hass = MagicMock()
    hass.data = {
        DOMAIN: {
            "entry1": {
                "coordinator": coordinator,
                "client": client or MagicMock(),
            }
        }
    }
    return hass


def _entry(**overrides):
    entry = MagicMock()
    entry.entry_id = "entry1"
    entry.data = {
        "node": "node1",
        "platform_type": "PVE",
        "server_id": "node1",
        "enable_lm_sensors": False,
        "enable_smart_monitoring": False,
        "enable_memory_monitoring": False,
        "enable_physical_disks": False,
        **overrides,
    }
    entry.options = {}
    return entry


async def _run_sensor_setup(entry):
    coord = _coordinator()
    added = []
    await sensor_mod.async_setup_entry(
        _hass(coord), entry, lambda entities, *a, **kw: added.extend(entities)
    )
    return added


def _storage_names(entities):
    """Names of the per-storage entities (not the aggregate list sensor)."""
    return {
        getattr(e, "_storage_name", None) or getattr(e, "_sensor_id", None)
        for e in entities
        if type(e).__name__ == "ProxmoxStorageSensor"
    }


# ===========================================================================
# Storage auf Entity-Ebene
# ===========================================================================

class TestStorageEntitySelection:

    @pytest.mark.asyncio
    async def test_no_selection_creates_entities_for_all_storages(self):
        """Der None-Default darf keinen TypeError auslösen und muss alles zeigen."""
        entities = await _run_sensor_setup(_entry())
        ids = _storage_names(entities)
        assert "local" in ids and "nvme-pool" in ids

    @pytest.mark.asyncio
    async def test_empty_selection_creates_no_storage_entities(self):
        entities = await _run_sensor_setup(_entry(selected_storage=[]))
        ids = _storage_names(entities)
        assert "local" not in ids and "nvme-pool" not in ids

    @pytest.mark.asyncio
    async def test_explicit_selection_creates_only_chosen_storage(self):
        entities = await _run_sensor_setup(_entry(selected_storage=["local"]))
        ids = _storage_names(entities)
        assert "local" in ids
        assert "nvme-pool" not in ids


# ===========================================================================
# Gäste auf Entity-Ebene
# ===========================================================================

class TestGuestEntitySelection:

    @pytest.mark.asyncio
    async def test_no_selection_creates_entities_for_all_guests(self):
        entities = await _run_sensor_setup(_entry())
        vm_ids = {getattr(e, "_vm_id", None) for e in entities}
        assert 101 in vm_ids and 202 in vm_ids

    @pytest.mark.asyncio
    async def test_empty_selection_creates_no_guest_entities(self):
        entities = await _run_sensor_setup(
            _entry(selected_vms=[], selected_cts=[])
        )
        vm_ids = {getattr(e, "_vm_id", None) for e in entities}
        ct_ids = {getattr(e, "_ct_id", None) for e in entities}
        assert vm_ids <= {None}, f"unexpected VM entities: {vm_ids}"
        assert ct_ids <= {None}, f"unexpected CT entities: {ct_ids}"

    @pytest.mark.asyncio
    async def test_explicit_selection_creates_only_chosen_guest(self):
        entities = await _run_sensor_setup(_entry(selected_vms=["node1:101"]))
        vm_ids = {getattr(e, "_vm_id", None) for e in entities}
        assert 101 in vm_ids
        assert 202 not in vm_ids


# ===========================================================================
# Buttons (war 0 % abgedeckt)
# ===========================================================================

class TestButtonSelection:

    @staticmethod
    async def _run(entry):
        coord = _coordinator()
        added = []
        await button_mod.async_setup_entry(
            _hass(coord), entry, lambda entities, *a, **kw: added.extend(entities)
        )
        return added

    @pytest.mark.asyncio
    async def test_no_selection_creates_buttons_for_all_guests(self):
        entities = await self._run(_entry())
        ids = {getattr(e, "_vmid", None) for e in entities}
        assert 101 in ids and 202 in ids

    @pytest.mark.asyncio
    async def test_empty_selection_creates_no_guest_buttons(self):
        entities = await self._run(_entry(selected_vms=[], selected_cts=[]))
        ids = {getattr(e, "_vmid", None) for e in entities}
        assert ids <= {None}, f"unexpected guest buttons: {ids}"

    @pytest.mark.asyncio
    async def test_explicit_selection_creates_only_chosen_guest_buttons(self):
        entities = await self._run(_entry(selected_vms=["node1:101"], selected_cts=[]))
        ids = {getattr(e, "_vmid", None) for e in entities}
        assert 101 in ids
        assert 202 not in ids
