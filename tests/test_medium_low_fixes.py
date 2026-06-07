"""
Tests für M1/N2, M4, M6, M7, M8, N4.

M1/N2 — Dead Code: limited_task_func referenziert nicht-existente globale SEM.
M4    — PBS size=None → TypeError (explicit or-0 fallback).
M6    — ProxmoxFailedTasksSensor liest 'cluster_tasks', das nicht im Coordinator gespeichert wird.
M7    — naive datetime.now() ohne UTC in coordinator.py.
M8    — WOL-MACs werden nach Options-Speicherung gelöscht.
N4    — self.state statt self.native_value in ProxmoxBackupHealthSensor.icon.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import timezone


# ---------------------------------------------------------------------------
# M1/N2 — limited_task_func dead code
# ---------------------------------------------------------------------------

class TestLimitedTaskFuncRemoved:
    def test_limited_task_func_does_not_exist_at_module_level(self):
        """limited_task_func must be removed — it referenced a non-existent global SEM."""
        import custom_components.proxmox_sensors.coordinator as coord_mod
        assert not hasattr(coord_mod, "limited_task_func"), (
            "limited_task_func is dead code with a broken SEM reference — remove it"
        )


# ---------------------------------------------------------------------------
# M4 — PBS size=None
# ---------------------------------------------------------------------------

class TestPBSLastBackupSizeSensor:
    def _make_sensor(self, size_value):
        from custom_components.proxmox_sensors.sensor.pbs import ProxmoxPBSLastBackupSizeSensor
        coord = MagicMock()
        coord.data = {
            "pbs_datastores": {
                "main": {"last_backup": {"size": size_value, "endtime": 1000}}
            }
        }
        s = ProxmoxPBSLastBackupSizeSensor.__new__(ProxmoxPBSLastBackupSizeSensor)
        s.coordinator = coord
        s._server_id = "pbs1"
        s._store = "main"  # attribute is _store, not _store_id
        return s

    def test_size_none_returns_none_not_type_error(self):
        """When size is None the sensor must return None, not raise TypeError."""
        s = self._make_sensor(None)
        # Must not raise
        result = s.native_value
        assert result is None or result == 0

    def test_size_zero_returns_zero(self):
        s = self._make_sensor(0)
        result = s.native_value
        assert result == 0.0 or result is None

    def test_size_normal_returns_gb(self):
        s = self._make_sensor(1024 ** 3)  # 1 GiB
        result = s.native_value
        assert result == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# M6 — cluster_tasks stored in cluster coordinator
# ---------------------------------------------------------------------------

class TestClusterCoordinatorStoresClusterTasks:
    @pytest.mark.asyncio
    async def test_cluster_tasks_key_present_in_result(self):
        """The cluster coordinator must store 'cluster_tasks' so
        ProxmoxFailedTasksSensor doesn't always return 0."""
        from unittest.mock import AsyncMock
        import custom_components.proxmox_sensors.coordinator as coord_mod

        client = MagicMock()
        client.get_cluster_resources = AsyncMock(return_value=[])
        client.get_cluster_status = AsyncMock(return_value={})
        client.get_cluster_ha_status = AsyncMock(return_value={})
        client.get_cluster_firewall_options = AsyncMock(return_value={})
        client.get_backup_jobs = AsyncMock(return_value=[])
        client.get_cluster_tasks = AsyncMock(return_value=[
            {"upid": "UPID:n:1:1:1:task:id:root", "status": "error", "endtime": 9999999999}
        ])

        hass = MagicMock()
        entry = MagicMock()
        entry.data = {"cluster_name": "test"}

        coordinator = await coord_mod.create_cluster_coordinator(hass, entry, client)
        result = await coordinator.update_method()

        assert "cluster_tasks" in result, (
            "cluster coordinator must store 'cluster_tasks' — "
            "ProxmoxFailedTasksSensor reads this key"
        )


# ---------------------------------------------------------------------------
# M7 — datetime.now() must use UTC
# ---------------------------------------------------------------------------

class TestCoordinatorDatetimeUTC:
    def test_last_update_is_utc_aware(self):
        """'last_update' stored by coordinator must be UTC-aware (not naive)."""
        import custom_components.proxmox_sensors.coordinator as coord_mod
        import ast, inspect

        source = inspect.getsource(coord_mod)
        # Check that datetime.now() without tz= is NOT used for last_update
        assert "datetime.now().strftime" not in source, (
            "datetime.now().strftime produces a naive local-time string — "
            "use datetime.now(tz=timezone.utc)"
        )


# ---------------------------------------------------------------------------
# N4 — self.state → self.native_value in ProxmoxBackupHealthSensor.icon
# ---------------------------------------------------------------------------

class TestBackupHealthSensorIcon:
    def _make_sensor(self, native_val):
        from custom_components.proxmox_sensors.sensor.cluster import ProxmoxBackupHealthSensor
        coord = MagicMock()
        coord.data = {}
        s = ProxmoxBackupHealthSensor.__new__(ProxmoxBackupHealthSensor)
        s.coordinator = coord
        s._entry_id = "e1"
        s._node = "node1"
        s._attr_unique_id = "test"

        # Patch native_value to return the desired value
        type(s).native_value = property(lambda self: native_val)
        # If the bug exists, self.state returns "unavailable" when sensor is
        # not yet in HA registry. Patch self.state to return something different
        # to prove icon uses native_value not state.
        type(s).state = property(lambda self: "unavailable")  # simulate unregistered sensor
        return s

    def test_icon_uses_native_value_not_state(self):
        """When native_value='healthy' but state='unavailable' (unregistered),
        icon must return the healthy icon based on native_value."""
        s = self._make_sensor("healthy")
        # With the bug: self.state = "unavailable" → icon = "mdi:shield-off"
        # With the fix: self.native_value = "healthy" → icon = "mdi:shield-check"
        assert s.icon == "mdi:shield-check", (
            f"icon must use native_value='healthy', got: {s.icon}"
        )
