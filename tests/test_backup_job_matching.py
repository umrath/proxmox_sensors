"""
Tests für K4: _build_backup_jobs_payload weist allen Jobs denselben latest_task zu.

Fix: Tasks werden per VMID auf Jobs gemappt. Jeder Job bekommt den
aktuellsten Task, der eine seiner konfigurierten VMIDs gesichert hat.
"""

import pytest
from custom_components.proxmox_sensors.coordinator import _build_backup_jobs_payload


def _make_task(vmid, status="OK", endtime=1000):
    return {
        "upid": f"UPID:node1:0001:0001:{endtime}:vzdump:{vmid}:root@pam",
        "status": status,
        "endtime": endtime,
        "starttime": endtime - 60,
        "type": "vzdump",
        "id": str(vmid),
    }


def _make_job(vmid, job_id="backup-1"):
    return {"id": job_id, "vmid": str(vmid), "storage": "local", "node": "node1"}


class TestBuildBackupJobsPayloadPerJobMatching:

    def test_job_gets_its_own_task_status(self):
        """Job A (VM 101) must get the OK task; Job B (VM 102) must get the error task."""
        jobs = [_make_job(101, "backup-a"), _make_job(102, "backup-b")]
        tasks = [
            _make_task(101, status="OK", endtime=2000),
            _make_task(102, status="error: disk full", endtime=1800),
        ]

        result = _build_backup_jobs_payload(jobs, tasks)

        job_a = next(j for j in result["jobs"] if j["id"] == "backup-a")
        job_b = next(j for j in result["jobs"] if j["id"] == "backup-b")

        assert job_a["last_status"] == "OK", f"Job A should be OK, got: {job_a['last_status']}"
        assert job_b["last_status"] == "error", f"Job B should be error, got: {job_b['last_status']}"

    def test_two_jobs_same_status_different_times(self):
        """Both jobs OK but different timestamps — each gets its own run time."""
        jobs = [_make_job(101, "job-a"), _make_job(102, "job-b")]
        tasks = [
            _make_task(101, status="OK", endtime=5000),
            _make_task(102, status="OK", endtime=3000),
        ]

        result = _build_backup_jobs_payload(jobs, tasks)
        job_a = next(j for j in result["jobs"] if j["id"] == "job-a")
        job_b = next(j for j in result["jobs"] if j["id"] == "job-b")

        assert job_a["last_run"] != job_b["last_run"], (
            "Jobs with different backup times must report different last_run"
        )

    def test_job_without_matching_task_gets_no_status(self):
        """If no task matches a job's VMID, last_status must be None (not another job's status)."""
        jobs = [_make_job(101, "job-101"), _make_job(999, "job-999")]
        tasks = [_make_task(101, status="OK", endtime=2000)]

        result = _build_backup_jobs_payload(jobs, tasks)
        job_999 = next(j for j in result["jobs"] if j["id"] == "job-999")

        assert job_999["last_status"] is None or job_999["last_status"] == "unknown", (
            "Job with no matching task must not inherit another job's status"
        )

    def test_job_with_multiple_vmids_uses_most_recent_task(self):
        """A job covering VMs 101,102 should get the most recent of both tasks."""
        job = {"id": "multi", "vmid": "101,102", "storage": "local", "node": "node1"}
        tasks = [
            _make_task(101, status="OK", endtime=1000),
            _make_task(102, status="OK", endtime=3000),  # newer
        ]

        result = _build_backup_jobs_payload([job], tasks)
        # endtime=3000 → ISO timestamp > endtime=1000 ISO timestamp
        from custom_components.proxmox_sensors.coordinator import _to_iso_timestamp
        assert result["jobs"][0]["last_run"] == _to_iso_timestamp(3000)

    def test_empty_jobs_returns_empty(self):
        result = _build_backup_jobs_payload([], [])
        assert result["jobs"] == []

    def test_empty_tasks_all_jobs_have_no_status(self):
        jobs = [_make_job(101), _make_job(102)]
        result = _build_backup_jobs_payload(jobs, [])
        for job in result["jobs"]:
            assert job["last_status"] is None or job["last_status"] == "unknown"
