"""
Tests für H3: Operator-Precedence-Bug in sensor/disks.py Zeile 74.

  if smart_model and clean_model in smart_model or smart_model in clean_model:

wird ausgewertet als:

  (smart_model and (clean_model in smart_model)) or (smart_model in clean_model)

Da `"" in any_string` immer True ist, matcht ein SMART-Eintrag mit leerem
model-Feld jede Disk. Die korrekte Klammerung ist:

  if smart_model and (clean_model in smart_model or smart_model in clean_model):
"""

import pytest


def _match_old(smart_model, clean_model):
    """Buggy version — operator precedence not fixed."""
    return smart_model and clean_model in smart_model or smart_model in clean_model


def _match_fixed(smart_model, clean_model):
    """Fixed version."""
    return smart_model and (clean_model in smart_model or smart_model in clean_model)


class TestSmartModelMatchingBug:

    def test_bug_empty_smart_model_matches_any_disk(self):
        """Old code: '' in 'samsung_870_evo' == True → false positive."""
        assert _match_old("", "samsung_870_evo") is True  # demonstrates the bug

    def test_fix_empty_smart_model_does_not_match(self):
        assert not _match_fixed("", "samsung_870_evo")

    def test_fix_empty_smart_model_does_not_match_empty_disk(self):
        assert not _match_fixed("", "")

    def test_fix_exact_match(self):
        assert _match_fixed("samsung_870_evo", "samsung_870_evo")

    def test_fix_partial_match_smart_in_disk(self):
        assert _match_fixed("samsung", "samsung_870_evo")

    def test_fix_partial_match_disk_in_smart(self):
        assert _match_fixed("samsung_870_evo_500gb", "samsung_870_evo")

    def test_fix_no_match(self):
        assert not _match_fixed("wdc_wds500", "samsung_870_evo")


class TestDiskSensorSmartLookup:
    """Integration: ProxmoxDiskSensor._find_smart_data must use fixed logic."""

    def _make_sensor(self, disk_id, model, serial=None, node="node1"):
        """Build a minimal ProxmoxDiskSensor-like object for testing."""
        from unittest.mock import MagicMock
        from custom_components.proxmox_sensors.sensor.disks import ProxmoxDiskSensor

        coordinator = MagicMock()
        sensor = ProxmoxDiskSensor.__new__(ProxmoxDiskSensor)
        sensor.coordinator = coordinator
        sensor._disk_id = disk_id
        sensor._model = model
        sensor._serial = serial
        sensor._node = node
        return sensor

    def _with_smart(self, sensor, smart_data):
        sensor.coordinator.data = {"smart": {sensor._node: smart_data}}
        return sensor

    def test_empty_smart_model_does_not_match_real_disk(self):
        sensor = self._make_sensor("sda", "Samsung 870 EVO", serial="S999")
        self._with_smart(sensor, {"nvme0": {"model": "", "serial": "XX123"}})
        result = sensor._find_smart_data_by_serial()
        assert result is None

    def test_matching_model_is_found(self):
        sensor = self._make_sensor("sda", "Samsung 870 EVO", serial="S1234")
        self._with_smart(sensor, {"sda": {"model": "Samsung_870_EVO", "serial": "S1234"}})
        result = sensor._find_smart_data_by_serial()
        assert result is not None
        assert result["serial"] == "S1234"
