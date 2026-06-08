"""
Tests für die Replikations-Statusermittlung.

`_build_replication_payload` normalisiert die Jobs aus
`GET /nodes/{node}/replication` und leitet einen Gesamtzustand ab:
- keine Jobs        -> "unknown"
- alle Jobs ok      -> "ok"
- mindestens 1 Fehler (fail_count > 0 oder error gesetzt) -> "error"
"""

import pytest
from custom_components.proxmox_sensors.coordinator import (
    _build_replication_payload,
    _to_iso_timestamp,
)


def _make_job(job_id, guest=101, target="node2", fail_count=0, error=None,
              last_sync=1000, next_sync=2000, duration=5, schedule="*/15"):
    return {
        "id": job_id,
        "guest": guest,
        "target": target,
        "fail_count": fail_count,
        "error": error,
        "last_sync": last_sync,
        "next_sync": next_sync,
        "duration": duration,
        "schedule": schedule,
    }


class TestBuildReplicationPayload:

    def test_empty_jobs_returns_unknown(self):
        result = _build_replication_payload([])
        assert result["state"] == "unknown"
        assert result["total_jobs"] == 0
        assert result["failed_jobs"] == 0
        assert result["jobs"] == []

    def test_non_list_input_is_safe(self):
        result = _build_replication_payload(None)
        assert result["state"] == "unknown"
        assert result["jobs"] == []

    def test_all_ok_jobs_state_ok(self):
        jobs = [_make_job("101-0"), _make_job("102-0", guest=102)]
        result = _build_replication_payload(jobs)
        assert result["state"] == "ok"
        assert result["total_jobs"] == 2
        assert result["failed_jobs"] == 0

    def test_fail_count_marks_error(self):
        jobs = [_make_job("101-0", fail_count=3)]
        result = _build_replication_payload(jobs)
        assert result["state"] == "error"
        assert result["failed_jobs"] == 1
        assert result["jobs"][0]["status"] == "error"

    def test_error_field_marks_error(self):
        jobs = [_make_job("101-0", error="connection refused")]
        result = _build_replication_payload(jobs)
        assert result["state"] == "error"
        assert result["jobs"][0]["error"] == "connection refused"

    def test_mixed_jobs_state_error(self):
        jobs = [_make_job("101-0"), _make_job("102-0", guest=102, fail_count=1)]
        result = _build_replication_payload(jobs)
        assert result["state"] == "error"
        assert result["failed_jobs"] == 1
        assert result["total_jobs"] == 2

    def test_last_sync_is_most_recent(self):
        jobs = [
            _make_job("101-0", last_sync=1000),
            _make_job("102-0", guest=102, last_sync=5000),
        ]
        result = _build_replication_payload(jobs)
        assert result["last_sync"] == _to_iso_timestamp(5000)

    def test_timestamps_converted_to_iso(self):
        jobs = [_make_job("101-0", last_sync=1000, next_sync=2000)]
        job = _build_replication_payload(jobs)["jobs"][0]
        assert job["last_sync"] == _to_iso_timestamp(1000)
        assert job["next_sync"] == _to_iso_timestamp(2000)

    def test_guest_normalized_to_string(self):
        jobs = [_make_job("101-0", guest=101)]
        job = _build_replication_payload(jobs)["jobs"][0]
        assert job["guest"] == "101"

    def test_invalid_fail_count_defaults_zero(self):
        jobs = [_make_job("101-0", fail_count="not-a-number")]
        result = _build_replication_payload(jobs)
        assert result["jobs"][0]["fail_count"] == 0
        assert result["state"] == "ok"

    def test_missing_last_sync_is_none(self):
        jobs = [_make_job("101-0", last_sync=None)]
        job = _build_replication_payload(jobs)["jobs"][0]
        assert job["last_sync"] is None

    def test_non_dict_jobs_skipped(self):
        jobs = ["garbage", None, _make_job("101-0")]
        result = _build_replication_payload(jobs)
        assert result["total_jobs"] == 1

    def test_job_without_id_falls_back_to_guest(self):
        jobs = [{"guest": 105, "fail_count": 0}]
        job = _build_replication_payload(jobs)["jobs"][0]
        assert job["id"] == "105"
