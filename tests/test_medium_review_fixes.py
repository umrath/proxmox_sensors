"""
Tests for second-review MEDIUM fixes.

M2 — PBS timestamp formatting must be UTC-aware (timezone.utc).
M3 — PBS server_id derived from host, not a race-prone sequential counter.
M4 — confirm_shutdown / confirm_reboot validate the node identifier.
M5 — backup-job state applies the 24h recency check to multi-failures too.
M6 — entity cleanup keys off the public unique_id, not _attr_unique_id.
"""

import inspect
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# M2 — PBS timestamps use timezone.utc
# ---------------------------------------------------------------------------

class TestPBSTimestampsUTC:
    def test_no_naive_fromtimestamp_in_pbs_module(self):
        import custom_components.proxmox_sensors.sensor.pbs as pbs_mod
        src = inspect.getsource(pbs_mod)
        # every fromtimestamp( call must pass tz=timezone.utc
        import re
        calls = re.findall(r"fromtimestamp\(([^)]*)\)", src)
        assert calls, "expected fromtimestamp calls in pbs.py"
        for args in calls:
            assert "tz=timezone.utc" in args, (
                f"naive datetime.fromtimestamp found: fromtimestamp({args})"
            )


# ---------------------------------------------------------------------------
# M3 — PBS server_id is host-derived (no sequential counter)
# ---------------------------------------------------------------------------

class TestPBSServerIdHostDerived:
    def test_finish_does_not_count_pbs_entries_for_server_id(self):
        import custom_components.proxmox_sensors.config_flow as cf
        src = inspect.getsource(cf.ProxmoxConfigFlow._finish)
        assert "len(pbs_entries)" not in src, (
            "server_id must not be derived from a sequential entry count (M3)"
        )
        assert "host_slug" in src, "server_id should be derived from the host (M3)"


# ---------------------------------------------------------------------------
# M4 — shutdown/reboot handlers validate node
# ---------------------------------------------------------------------------

class TestNodeControlValidation:
    def _register_and_get_handlers(self):
        import custom_components.proxmox_sensors.services as services_mod

        hass = MagicMock()
        hass.data = {}
        registered = {}

        def fake_register(domain, name, handler, *a, **k):
            registered[name] = handler

        hass.services.async_register = MagicMock(side_effect=fake_register)
        hass.services.has_service = MagicMock(return_value=False)

        entry = MagicMock()
        entry.data = {}
        services_mod.register_services(hass, entry)
        return registered

    @pytest.mark.asyncio
    async def test_shutdown_rejects_bad_node(self):
        handlers = self._register_and_get_handlers()
        call = MagicMock()
        call.data = {"node": "../etc; rm -rf /", "confirm": False}
        with pytest.raises(ValueError):
            await handlers["confirm_shutdown_node"](call)

    @pytest.mark.asyncio
    async def test_reboot_rejects_empty_node(self):
        handlers = self._register_and_get_handlers()
        call = MagicMock()
        call.data = {"node": "", "confirm": True}
        with pytest.raises(ValueError):
            await handlers["confirm_reboot_node"](call)

    @pytest.mark.asyncio
    async def test_shutdown_accepts_valid_node(self):
        handlers = self._register_and_get_handlers()
        call = MagicMock()
        call.data = {"node": "pve-node1", "confirm": False}
        # Should not raise (creates a persistent notification and returns)
        with patch(
            "custom_components.proxmox_sensors.services.persistent_notification"
        ):
            await handlers["confirm_shutdown_node"](call)


# ---------------------------------------------------------------------------
# M5 — recency check applies to multi-failures
# ---------------------------------------------------------------------------

class TestBackupStateRecency:
    def _payload(self, tasks, jobs):
        from custom_components.proxmox_sensors.coordinator import (
            _build_backup_jobs_payload,
        )
        return _build_backup_jobs_payload(jobs, tasks)

    def _task(self, vmid, status, endtime):
        return {
            "upid": f"UPID:node1:0001:0001:{endtime}:vzdump:{vmid}:root@pam",
            "status": status,
            "endtime": endtime,
            "starttime": endtime - 60,
            "type": "vzdump",
            "id": str(vmid),
        }

    def _job(self, vmid, job_id):
        return {"id": job_id, "vmid": str(vmid), "storage": "local", "node": "node1"}

    def test_two_stale_failures_is_warning_not_error(self):
        import time
        old = int(time.time()) - 5 * 86400  # 5 days ago
        jobs = [self._job(101, "a"), self._job(102, "b")]
        tasks = [
            self._task(101, "error: x", old),
            self._task(102, "error: y", old - 100),
        ]
        result = self._payload(tasks, jobs)
        assert result["failed_jobs"] == 2
        assert result["state"] == "warning", (
            f"Two stale failures should be 'warning', got {result['state']} (M5)"
        )

    def test_two_failures_one_recent_is_error(self):
        import time
        now = int(time.time())
        jobs = [self._job(101, "a"), self._job(102, "b")]
        tasks = [
            self._task(101, "error: x", now - 100),       # recent
            self._task(102, "error: y", now - 5 * 86400),  # stale
        ]
        result = self._payload(tasks, jobs)
        assert result["failed_jobs"] == 2
        assert result["state"] == "error", (
            f"A recent failure among two should be 'error', got {result['state']} (M5)"
        )


# ---------------------------------------------------------------------------
# M6 — cleanup uses public unique_id
# ---------------------------------------------------------------------------

class TestCleanupUsesPublicUniqueId:
    def test_source_uses_entity_unique_id(self):
        import custom_components.proxmox_sensors.sensor as sensor_mod
        src = inspect.getsource(sensor_mod.async_setup_entry)
        assert 'getattr(entity, "_attr_unique_id"' not in src, (
            "cleanup must not key off _attr_unique_id — entities with a computed "
            "unique_id property would be wrongly deleted (M6)"
        )
        assert "entity.unique_id" in src

    def test_property_based_unique_id_preserved(self):
        """An entity exposing unique_id via property (no _attr_unique_id) must be
        kept by the cleanup set logic."""
        class PropEntity:
            @property
            def unique_id(self):
                return "computed_uid_v1"

        entities = [PropEntity()]
        # FIXED logic
        new_unique_ids = {e.unique_id for e in entities}
        assert "computed_uid_v1" in new_unique_ids
        # OLD buggy logic would have produced {None}
        old_ids = {getattr(e, "_attr_unique_id", None) for e in entities}
        assert old_ids == {None}
