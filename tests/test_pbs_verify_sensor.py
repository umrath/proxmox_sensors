"""
Test C1: ProxmoxPBSVerifySensor reads the wrong coordinator key.

Bug: _get_value read data.get("last_backup_time") which never exists;
the coordinator stores "last_backup" (a snapshot dict with a "backup-time"
epoch). The Pending-when-backup-newer-than-verify branch was therefore dead.

Fix: read last_backup["backup-time"] and compare against the verify endtime.
"""

import pytest
from unittest.mock import MagicMock


def _make_sensor(verify_task, last_backup):
    from custom_components.proxmox_sensors.sensor.pbs import ProxmoxPBSVerifySensor

    coord = MagicMock()
    coord.data = {
        "pbs_tasks": [verify_task] if verify_task else [],
        "pbs_datastores": {
            "main": {"last_backup": last_backup},
        },
    }
    s = ProxmoxPBSVerifySensor.__new__(ProxmoxPBSVerifySensor)
    s.coordinator = coord
    s._server_id = "pbs1"
    s._store = "main"
    return s


def _verify_task(endtime, status="OK"):
    return {
        "worker_type": "verify",
        "store": "main",
        "upid": "UPID:n:1:1:1:verify:main:root@pam",
        "endtime": endtime,
        "status": status,
    }


class TestPBSVerifySensorValue:

    def test_verify_after_backup_is_ok(self):
        """Verify ran after the last backup → OK."""
        s = _make_sensor(
            verify_task=_verify_task(endtime=5000),
            last_backup={"backup-time": 4000, "size": 123},
        )
        assert s.native_value == "OK"

    def test_backup_newer_than_verify_is_pending(self):
        """A backup happened after the last verify → Pending.

        This is the branch the bug killed: with last_backup_time always None,
        this used to wrongly return OK.
        """
        s = _make_sensor(
            verify_task=_verify_task(endtime=4000),
            last_backup={"backup-time": 5000, "size": 123},
        )
        assert s.native_value == "Pending", (
            "Backup newer than verify must yield Pending — C1 not fixed"
        )

    def test_no_verify_task_is_pending(self):
        s = _make_sensor(verify_task=None, last_backup={"backup-time": 5000})
        assert s.native_value == "Pending"

    def test_running_verify(self):
        task = _verify_task(endtime=0, status="running")
        task["endtime"] = None
        s = _make_sensor(verify_task=task, last_backup={"backup-time": 1000})
        assert s.native_value == "Running"

    def test_no_last_backup_but_verify_done_is_ok(self):
        """If there's no backup info at all but a verify completed → OK (not Pending)."""
        s = _make_sensor(verify_task=_verify_task(endtime=5000), last_backup=None)
        assert s.native_value == "OK"
