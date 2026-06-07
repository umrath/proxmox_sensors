"""
Tests für H4: PBSLastActionSensor._attr_unique_id fehlt server_id-Präfix.
Zwei PBS-Instanzen mit gleichnamigem Datastore ("main") erzeugen identische
unique_ids → Entity-Konflikt in HA.
Fix: unique_id = f"pbs_{server_id}_{datastore.lower()}_last_action"
"""

from unittest.mock import MagicMock
from custom_components.proxmox_sensors.sensor.sensor_last_action import PBSLastActionSensor


def _make_sensor(server_id, datastore):
    coordinator = MagicMock()
    coordinator.data = {}
    return PBSLastActionSensor(coordinator, server_id, datastore)


class TestPBSLastActionUniqueId:

    def test_unique_id_contains_server_id(self):
        s = _make_sensor("pbs1", "main")
        assert "pbs1" in s._attr_unique_id

    def test_unique_id_contains_datastore(self):
        s = _make_sensor("pbs1", "main")
        assert "main" in s._attr_unique_id

    def test_unique_id_starts_with_pbs_prefix(self):
        s = _make_sensor("pbs1", "main")
        assert s._attr_unique_id.startswith("pbs_")

    def test_two_instances_same_datastore_different_server_have_different_ids(self):
        s1 = _make_sensor("pbs1", "main")
        s2 = _make_sensor("pbs2", "main")
        assert s1._attr_unique_id != s2._attr_unique_id

    def test_two_instances_same_server_different_datastore_have_different_ids(self):
        s1 = _make_sensor("pbs1", "main")
        s2 = _make_sensor("pbs1", "offsite")
        assert s1._attr_unique_id != s2._attr_unique_id

    def test_exact_format(self):
        s = _make_sensor("mypbs", "backup-store")
        assert s._attr_unique_id == "pbs_mypbs_backup-store_last_action"
