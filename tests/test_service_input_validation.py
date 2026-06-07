"""
Tests für Input-Validierung in services.py (S4/S5).

S4: `storage` wird nur whitespace-bereinigt, aber nicht auf erlaubte Zeichen geprüft.
S5: `node` aus dem Service-Call wird gar nicht validiert — landet direkt in API-Pfaden.

Proxmox-Node-Namen und Storage-Namen sind strikt alphanumerisch mit Bindestrich/Unterstrich.
Ein Service-Call mit `node: "../../cluster/backup"` würde sonst zu einem Path-Traversal-Versuch.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.proxmox_sensors.services import register_services, _validate_identifier
from custom_components.proxmox_sensors.const import DOMAIN


def _make_hass(node="node1"):
    coordinator = MagicMock()
    coordinator.data = {"vms": {}, "cts": {}}
    client = MagicMock()
    client.start_vzdump = AsyncMock(return_value="UPID:ok")
    entry = MagicMock()
    entry.entry_id = "test_entry"
    entry.data = {"node": node}
    hass = MagicMock()
    hass.data = {
        DOMAIN: {"test_entry": {"client": client, "coordinator": coordinator, "node": node}}
    }
    registered = {}
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = lambda domain, name, handler: registered.__setitem__(
        name, handler
    )
    register_services(hass, entry)
    return hass, client, registered


# ---------------------------------------------------------------------------
# Unit tests for _validate_identifier
# ---------------------------------------------------------------------------

class TestValidateIdentifier:
    def test_valid_alphanumeric(self):
        _validate_identifier("node1", "node")   # must not raise

    def test_valid_with_dash(self):
        _validate_identifier("pve-node-01", "node")

    def test_valid_with_underscore(self):
        _validate_identifier("local_storage", "storage")

    def test_valid_with_dot(self):
        _validate_identifier("pbs.backup", "storage")

    def test_rejects_slash(self):
        with pytest.raises(ValueError, match="node"):
            _validate_identifier("../../etc/passwd", "node")

    def test_rejects_space(self):
        with pytest.raises(ValueError, match="storage"):
            _validate_identifier("local storage", "storage")

    def test_rejects_newline(self):
        with pytest.raises(ValueError, match="node"):
            _validate_identifier("node1\n", "node")

    def test_rejects_semicolon(self):
        with pytest.raises(ValueError, match="node"):
            _validate_identifier("node1;reboot", "node")

    def test_rejects_empty_string(self):
        with pytest.raises(ValueError):
            _validate_identifier("", "node")


# ---------------------------------------------------------------------------
# Integration: service handlers reject bad identifiers
# ---------------------------------------------------------------------------

class TestServiceInputValidation:

    @pytest.mark.asyncio
    async def test_backup_all_rejects_path_traversal_in_node(self):
        """backup_all must raise ValueError for a node like '../../etc'."""
        _, client, registered = _make_hass()
        sc = MagicMock()
        sc.data = {
            "node": "../../etc/proxmox",
            "storage": "local",
            "include_vms": True,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }
        with pytest.raises(ValueError, match="node"):
            await registered["backup_all"](sc)
        client.start_vzdump.assert_not_called()

    @pytest.mark.asyncio
    async def test_backup_all_rejects_injection_in_storage(self):
        """backup_all must raise ValueError for a storage containing special chars."""
        _, client, registered = _make_hass()
        sc = MagicMock()
        sc.data = {
            "node": "node1",
            "storage": "local;rm -rf /",
            "include_vms": True,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }
        with pytest.raises(ValueError, match="storage"):
            await registered["backup_all"](sc)
        client.start_vzdump.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_vzdump_backup_rejects_bad_node(self):
        _, client, registered = _make_hass()
        sc = MagicMock()
        sc.data = {
            "node": "node1 && reboot",
            "guests": "101",
            "storage": "local",
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }
        with pytest.raises(ValueError, match="node"):
            await registered["create_vzdump_backup"](sc)
        client.start_vzdump.assert_not_called()

    @pytest.mark.asyncio
    async def test_valid_node_and_storage_pass_through(self):
        """Valid identifiers must not be rejected."""
        _, client, registered = _make_hass(node="pve-node-01")
        sc = MagicMock()
        sc.data = {
            "node": "pve-node-01",
            "storage": "local_backup",
            "include_vms": True,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 0,
        }
        # Should not raise (even if no VMs found)
        await registered["backup_all"](sc)
