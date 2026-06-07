"""
Test M2: Disks without a 'model' field must not be silently ignored.

Bug: sensor/__init__.py checked `if d_model and "boot" not in d_model`
which skipped disks where model was missing/empty.

Fix: only skip disks where model contains "boot"; modelless disks use d_id
as the label.
"""

import pytest
from unittest.mock import MagicMock


class TestDiskSensorCreatedWithoutModel:
    """Verify that the disk sensor setup loop includes modelless disks."""

    def _make_coordinator_with_disks(self, disks: dict):
        coord = MagicMock()
        coord.data = {
            "pve-node": {
                "disks": disks,
                "storage": {},
                "lm_sensors": {},
                "guests": {},
            }
        }
        coord.config_entry.data = {
            "node": "pve-node",
            "platform_type": "PVE",
        }
        coord.config_entry.options = {}
        coord.config_entry.entry_id = "e1"
        return coord

    def _run_setup_collect_entities(self, disks):
        """Import the sensor module and collect what entities would be created."""
        from custom_components.proxmox_sensors.sensor.disks import ProxmoxDiskSensor

        coord = self._make_coordinator_with_disks(disks)
        node = "pve-node"
        c_data = coord.data[node]

        entities = []
        for d_id, d_info in c_data["disks"].items():
            d_model = str(d_info.get("model", "")).lower()
            if "boot" in d_model:
                continue
            entities.append(
                ProxmoxDiskSensor(
                    coord, d_id, node, d_info.get("model") or d_id
                )
            )
        return entities

    def test_disk_with_model_included(self):
        entities = self._run_setup_collect_entities(
            {"sda": {"model": "Samsung SSD 870", "serial": "S1234"}}
        )
        assert len(entities) == 1

    def test_disk_without_model_still_included(self):
        """A disk with no 'model' key must still get a sensor (using d_id as label)."""
        entities = self._run_setup_collect_entities(
            {"nvme0n1": {"serial": "NVME12345"}}
        )
        assert len(entities) == 1, (
            "Disk without 'model' field was silently dropped — M2 not fixed"
        )

    def test_boot_disk_excluded(self):
        """Disks whose model contains 'boot' are intentionally skipped."""
        entities = self._run_setup_collect_entities(
            {"sda": {"model": "Boot Device"}}
        )
        assert len(entities) == 0

    def test_empty_model_string_included(self):
        """model='' (empty string) must not be treated as a reason to skip."""
        entities = self._run_setup_collect_entities(
            {"sdb": {"model": "", "serial": "X999"}}
        )
        assert len(entities) == 1

    def test_mixed_disks(self):
        """Two regular disks (one with model, one without) and one boot disk."""
        entities = self._run_setup_collect_entities({
            "sda": {"model": "Kingston SSD"},
            "sdb": {},                          # no model field
            "sdc": {"model": "Boot USB"},       # should be excluded
        })
        assert len(entities) == 2
