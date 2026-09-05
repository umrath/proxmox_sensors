"""
Regression für den gemeldeten Totalausfall (v5.0.0).

Symptom: ein schlecht erreichbarer PVE-Node ließ die *gesamte* HA-Instanz hängen.

Ursache: jeder API-Call lief über `hass.async_add_executor_job`. `asyncio.timeout`
bricht nur das await ab, nicht den Executor-Thread — die Threads blieben blockiert,
der HA-weite SyncWorker-Pool (64, von allen Integrationen geteilt) lief leer, und
jede andere Integration stand still.

Dieser Test fährt den echten `ProxmoxClient` durch den echten Coordinator gegen
einen hängenden Node und prüft, dass dabei *kein* Executor-Job entsteht.
"""

import asyncio
import threading

import pytest
from unittest.mock import MagicMock

import custom_components.proxmox_sensors.coordinator as coord_mod
from custom_components.proxmox_sensors.api import ProxmoxClient

from tests.aiohttp_fakes import attach, connect_error


class _TrackingHass:
    """Fails loudly if anything tries to use HA's shared SyncWorker pool."""

    def __init__(self):
        self.executor_calls = []

    def async_add_executor_job(self, func, *args):
        self.executor_calls.append(getattr(func, "__name__", repr(func)))
        raise AssertionError(
            "transport must not touch HA's executor pool — that is what hung HA"
        )


def _entry():
    entry = MagicMock()
    entry.data = {
        "node": "node1",
        "platform_type": "PVE",
        "host": "unreachable.local",
        "username": "root@pam",
        "enable_lm_sensors": True,
        "enable_smart_monitoring": True,
        "enable_memory_monitoring": True,
        "enable_physical_disks": True,
    }
    entry.options = {"enable_memory_monitoring": True}
    return entry


def _hanging_client():
    client = ProxmoxClient(
        host="unreachable.local",
        user="root@pam",
        token_id="ha",
        token_secret="sec",
        server_type="PVE",
    )
    # Every call behaves like a node that never answers: the transport's
    # ClientTimeout(total=...) has fired.
    attach(client, lambda m, u, k: TimeoutError())
    return client


@pytest.mark.asyncio
async def test_hung_node_uses_no_executor_threads():
    hass = _TrackingHass()
    coordinator = await coord_mod.create_proxmox_coordinator(
        hass, _entry(), _hanging_client()
    )

    threads_before = threading.active_count()
    result = await coordinator.update_method()
    threads_after = threading.active_count()

    assert hass.executor_calls == [], (
        f"executor was used for {hass.executor_calls} — the hang would come back"
    )
    assert threads_after == threads_before, "no worker threads may be left behind"
    assert isinstance(result, dict)


@pytest.mark.asyncio
async def test_hung_node_still_yields_a_usable_result():
    """Entities degrade to empty values instead of the whole update failing."""
    coordinator = await coord_mod.create_proxmox_coordinator(
        _TrackingHass(), _entry(), _hanging_client()
    )
    result = await coordinator.update_method()

    assert result["node"]["status"] == "unknown"
    assert result["vms"] == {} and result["cts"] == {}
    assert result["storage"] == {} and result["hardware"] == {}


@pytest.mark.asyncio
async def test_unreachable_node_is_not_slower_than_the_task_budget():
    """A dead node must not stretch the cycle — it fails fast, per call."""
    coordinator = await coord_mod.create_proxmox_coordinator(
        _TrackingHass(), _entry(), _hanging_client()
    )

    loop = asyncio.get_running_loop()
    start = loop.time()
    await coordinator.update_method()
    elapsed = loop.time() - start

    assert elapsed < 1.0, f"cycle took {elapsed:.2f}s — should fail fast"


@pytest.mark.asyncio
async def test_many_nodes_hanging_stay_independent():
    """Five hung nodes in parallel: still no executor use, still bounded."""
    hass = _TrackingHass()
    coordinators = [
        await coord_mod.create_proxmox_coordinator(hass, _entry(), _hanging_client())
        for _ in range(5)
    ]

    threads_before = threading.active_count()
    results = await asyncio.gather(*(c.update_method() for c in coordinators))

    assert hass.executor_calls == []
    assert threading.active_count() == threads_before
    assert all(isinstance(r, dict) for r in results)


@pytest.mark.asyncio
async def test_connection_refused_behaves_the_same_as_timeout():
    client = ProxmoxClient(
        host="unreachable.local",
        user="root@pam",
        token_id="ha",
        token_secret="sec",
        server_type="PVE",
    )
    attach(client, lambda m, u, k: connect_error())

    hass = _TrackingHass()
    coordinator = await coord_mod.create_proxmox_coordinator(hass, _entry(), client)
    result = await coordinator.update_method()

    assert hass.executor_calls == []
    assert result["node"]["status"] == "unknown"
