"""
Tests für K1: run_prune sendet keep-last=1 ohne Konfigurationsmöglichkeit.
Fix: prune-datastore-Endpoint nutzen (verwendet die konfigurierten Retention-Settings des Datastores).

Tests für K3-nahe: run_gc, run_verify rufen die richtigen Endpoints auf.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.proxmox_sensors.pbs_actions import (
    run_gc, run_prune, run_verify, run_sync,
)


def _make_client(snapshots=None, remotes=None):
    client = MagicMock()
    client.pbs_get = AsyncMock()
    client.pbs_post = AsyncMock(return_value={"upid": "UPID:ok"})
    if snapshots is not None:
        client.pbs_get.return_value = snapshots
    if remotes is not None:
        client.pbs_get.return_value = remotes
    return client


class TestRunPrune:

    @pytest.mark.asyncio
    async def test_prune_calls_prune_datastore_endpoint(self):
        """run_prune must use prune-datastore (not per-group prune with keep-last=1)."""
        client = _make_client()
        hass = MagicMock()

        await run_prune(client, hass, "main")

        client.pbs_post.assert_called_once()
        args, kwargs = client.pbs_post.call_args
        endpoint = args[1] if len(args) > 1 else kwargs.get("endpoint", args[0])
        assert "prune-datastore" in endpoint, (
            f"Expected prune-datastore endpoint, got: {endpoint}"
        )

    @pytest.mark.asyncio
    async def test_prune_does_not_send_keep_last_1(self):
        """run_prune must NOT hardcode keep-last=1."""
        client = _make_client()
        hass = MagicMock()

        await run_prune(client, hass, "main")

        for call in client.pbs_post.call_args_list:
            args, kwargs = call
            # Check positional and keyword data arguments
            for arg in args:
                if isinstance(arg, dict):
                    assert arg.get("keep-last") != 1, "keep-last=1 is destructive!"
            data = kwargs.get("data", {})
            if isinstance(data, dict):
                assert data.get("keep-last") != 1

    @pytest.mark.asyncio
    async def test_prune_uses_correct_datastore(self):
        """run_prune endpoint must contain the datastore name."""
        client = _make_client()
        hass = MagicMock()

        await run_prune(client, hass, "offsite-backup")

        args, _ = client.pbs_post.call_args
        endpoint = args[1] if len(args) > 1 else args[0]
        assert "offsite-backup" in endpoint

    @pytest.mark.asyncio
    async def test_prune_does_not_call_pbs_get(self):
        """prune-datastore needs no prior snapshot listing."""
        client = _make_client()
        hass = MagicMock()

        await run_prune(client, hass, "main")

        client.pbs_get.assert_not_called()


class TestRunGc:

    @pytest.mark.asyncio
    async def test_gc_calls_gc_endpoint(self):
        client = _make_client()
        hass = MagicMock()
        await run_gc(client, hass, "main")
        args, _ = client.pbs_post.call_args
        endpoint = args[1] if len(args) > 1 else args[0]
        assert "gc" in endpoint

    @pytest.mark.asyncio
    async def test_gc_uses_correct_datastore(self):
        client = _make_client()
        hass = MagicMock()
        await run_gc(client, hass, "offsite")
        args, _ = client.pbs_post.call_args
        endpoint = args[1] if len(args) > 1 else args[0]
        assert "offsite" in endpoint
