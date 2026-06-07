"""
Tests für services.py — Multi-Entry-Probleme (A2).

Bug A2: Jedes PVE-Entry registriert denselben Service-Namen (z.B. "backup_all").
Der zuletzt registrierte Handler gewinnt. Bei 2 PVE-Entries (node1 + node2)
überschreibt Entry 2 die Handler von Entry 1 — Backup-Aufrufe für node1
laufen dann gegen den Client von node2.

Der Service-Call enthält bereits den Ziel-Node als Parameter. Die Lösung:
Beim Service-Aufruf den richtigen Entry anhand des übergebenen `node`-Parameters
suchen, statt den Client aus dem Entry zu nehmen, das den Handler registriert hat.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.proxmox_sensors.services import register_services
from custom_components.proxmox_sensors.coordinator import _build_vms_dict
from custom_components.proxmox_sensors.const import DOMAIN


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entry(entry_id, node, vms=None):
    coordinator = MagicMock()
    coordinator.data = {"vms": vms or {}, "cts": {}}

    client = MagicMock()
    client.start_vzdump = AsyncMock(return_value="UPID:backup")

    entry = MagicMock()
    entry.entry_id = entry_id
    entry.data = {"node": node}
    return entry, client, coordinator


def _register_both(hass, entry1, client1, coord1, entry2, client2, coord2):
    """Register services for two PVE entries, simulating multi-node setup.

    The node field is stored in hass.data[DOMAIN] so _find_entry_for_node()
    can dispatch to the right client at call time.
    hass.data must be a real dict so that .get() works correctly.
    """
    # Use a real dict so hass.data.get(DOMAIN, {}) returns our data
    hass.data = {
        DOMAIN: {
            entry1.entry_id: {"client": client1, "coordinator": coord1,
                              "node": entry1.data["node"]},
            entry2.entry_id: {"client": client2, "coordinator": coord2,
                              "node": entry2.data["node"]},
        }
    }

    registered = {}
    hass.services = MagicMock()
    # has_service returns True after first registration (simulates HA's service registry)
    hass.services.has_service = lambda domain, name: name in registered
    hass.services.async_register = lambda domain, name, handler: registered.__setitem__(
        name, handler
    )

    register_services(hass, entry1)   # registers all handlers
    register_services(hass, entry2)   # skips (has_service → True)
    return registered


# ---------------------------------------------------------------------------
# A2: Service-Handler überschreiben sich gegenseitig
# ---------------------------------------------------------------------------

class TestMultiEntryServiceDispatch:

    @pytest.mark.asyncio
    async def test_backup_all_uses_correct_client_for_node1(self):
        """
        With two PVE entries (node1, node2), calling backup_all for node1
        must use the client of the node1 entry, not the node2 client.
        """
        vms1 = _build_vms_dict(
            [{"vmid": 101, "status": "running"}], [], ["101"], "node1"
        )
        vms2 = _build_vms_dict(
            [{"vmid": 201, "status": "running"}], [], ["201"], "node2"
        )

        hass = MagicMock()
        entry1, client1, coord1 = _make_entry("entry1", "node1", vms1)
        entry2, client2, coord2 = _make_entry("entry2", "node2", vms2)

        registered = _register_both(hass, entry1, client1, coord1, entry2, client2, coord2)

        sc = MagicMock()
        sc.data = {
            "node": "node1",
            "storage": "local",
            "include_vms": True,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }

        await registered["backup_all"](sc)

        # node1's client must have been called — not node2's
        assert client1.start_vzdump.call_count == 1, (
            "backup_all for node1 must use the node1 client"
        )
        client2.start_vzdump.assert_not_called()

    @pytest.mark.asyncio
    async def test_backup_all_uses_correct_client_for_node2(self):
        """Calling backup_all for node2 must use the node2 client."""
        vms1 = _build_vms_dict(
            [{"vmid": 101, "status": "running"}], [], ["101"], "node1"
        )
        vms2 = _build_vms_dict(
            [{"vmid": 201, "status": "running"}], [], ["201"], "node2"
        )

        hass = MagicMock()
        entry1, client1, coord1 = _make_entry("entry1", "node1", vms1)
        entry2, client2, coord2 = _make_entry("entry2", "node2", vms2)

        registered = _register_both(hass, entry1, client1, coord1, entry2, client2, coord2)

        sc = MagicMock()
        sc.data = {
            "node": "node2",
            "storage": "local",
            "include_vms": True,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }

        await registered["backup_all"](sc)

        client1.start_vzdump.assert_not_called()
        assert client2.start_vzdump.call_count == 1, (
            "backup_all for node2 must use the node2 client"
        )

    @pytest.mark.asyncio
    async def test_backup_all_unknown_node_does_nothing(self):
        """If node is not found in any entry, backup_all should not crash."""
        hass = MagicMock()
        entry1, client1, coord1 = _make_entry("entry1", "node1")
        entry2, client2, coord2 = _make_entry("entry2", "node2")

        registered = _register_both(hass, entry1, client1, coord1, entry2, client2, coord2)

        sc = MagicMock()
        sc.data = {
            "node": "node99",
            "storage": "local",
            "include_vms": True,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }

        await registered["backup_all"](sc)

        client1.start_vzdump.assert_not_called()
        client2.start_vzdump.assert_not_called()
