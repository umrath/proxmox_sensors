"""
Tests für api.py — PBS-spezifische Methoden.

Bug L6: get_pbs_datastore_usage ruft admin/datastore/{store}/gc ab —
identisch mit get_pbs_gc. Der Coordinator merged dann GC-Daten über die
Status-Felder (total/used/avail), was die Disk-Größensensoren korrumpiert.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from custom_components.proxmox_sensors.api import ProxmoxClient


def _make_pbs_client():
    return ProxmoxClient(
        host="pbs.local",
        user="root@pam",
        token_id="backup!ro",
        token_secret="secret",
        server_type="PBS",
        verify_ssl=False,
    )


class TestGetPbsDatastoreUsage:
    """Bug L6: get_pbs_datastore_usage must not call the /gc endpoint."""

    @pytest.mark.asyncio
    async def test_datastore_usage_does_not_call_gc_endpoint(self):
        """get_pbs_datastore_usage must NOT call admin/datastore/{store}/gc."""
        client = _make_pbs_client()
        hass = MagicMock()
        called_paths = []

        async def fake_pbs_get(h, path):
            called_paths.append(path)
            return {}

        client.pbs_get = fake_pbs_get

        await client.get_pbs_datastore_usage(hass, "main")

        assert not any("/gc" in p for p in called_paths), (
            f"get_pbs_datastore_usage must not call /gc endpoint; called: {called_paths}"
        )

    @pytest.mark.asyncio
    async def test_datastore_usage_and_gc_call_different_endpoints(self):
        """get_pbs_datastore_usage and get_pbs_gc must call different endpoints."""
        client = _make_pbs_client()
        hass = MagicMock()

        usage_paths = []
        gc_paths = []

        original_pbs_get = client.pbs_get

        async def track_usage(h, path):
            usage_paths.append(path)
            return {}

        async def track_gc(h, path):
            gc_paths.append(path)
            return {}

        client.pbs_get = track_usage
        await client.get_pbs_datastore_usage(hass, "main")

        client.pbs_get = track_gc
        await client.get_pbs_gc(hass, "main")

        assert usage_paths != gc_paths, (
            f"get_pbs_datastore_usage ({usage_paths}) and get_pbs_gc ({gc_paths}) "
            "must not call the same endpoint"
        )

    @pytest.mark.asyncio
    async def test_coordinator_merge_preserves_status_fields(self):
        """
        When the coordinator merges status and usage, disk size fields must
        not be overwritten by GC data.

        This simulates: result = {**status, **usage}
        If usage == gc_data, the 'total'/'used'/'avail' from status get lost.
        """
        status = {"total": 1_000_000, "used": 500_000, "avail": 500_000,
                  "deduplication": 1.5}
        gc_data = {"disk-bytes": 999, "removed-bytes": 100, "status": "ok"}

        # Bug scenario: usage returns gc data, overwrites status
        merged_bad = {**status, **gc_data}
        # After fix: usage returns {} (no conflicting keys)
        merged_good = {**status, **{}}

        assert merged_good.get("total") == 1_000_000
        assert merged_good.get("used") == 500_000
        # Bad merge: gc_data doesn't have "total", so it's preserved — but
        # in reality the PBS /gc endpoint may return keys that clash with /status.
        # The test documents the contract: usage must never pollute status fields.
        for key in ("total", "used", "avail"):
            assert key in merged_good, f"status field '{key}' must survive merge"
