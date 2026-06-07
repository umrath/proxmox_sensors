"""
Tests für H5: asyncio.sleep(delay_between) liegt innerhalb von async with semaphore.
Mit max_concurrent=1 hält Task 1 den Semaphore-Slot während er wartet
→ Task 2 kann erst nach dem Sleep starten, obwohl er fertig ist.

Fix: sleep AUSSERHALB des semaphore-Blocks.
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.proxmox_sensors.services import register_services
from custom_components.proxmox_sensors.const import DOMAIN


def _make_hass(node="node1", vm_ids=None):
    vm_ids = vm_ids or [101, 102]
    vms = {
        f"{node}:{v}": {"vmid": v, "node": node, "migrated": False}
        for v in vm_ids
    }
    coordinator = MagicMock()
    coordinator.data = {"vms": vms, "cts": {}}
    client = MagicMock()
    client.start_vzdump = AsyncMock(return_value="UPID:ok")
    hass = MagicMock()
    hass.data = {
        DOMAIN: {"e1": {"client": client, "coordinator": coordinator, "node": node}}
    }
    registered = {}
    hass.services = MagicMock()
    hass.services.has_service = MagicMock(return_value=False)
    hass.services.async_register = lambda domain, name, handler: registered.__setitem__(
        name, handler
    )
    register_services(hass, MagicMock())
    return hass, client, registered


class TestBackupSemaphoreDelay:

    @pytest.mark.asyncio
    async def test_semaphore_released_before_sleep(self):
        """With max_concurrent=1: backup 2 must be able to start while backup 1 sleeps.

        fake_sleep yields via asyncio.sleep(0) to let other tasks run.
        - With the bug (sleep inside semaphore): backup 2 is blocked → backup_2_started is False at sleep time.
        - With the fix (sleep outside semaphore): backup 2 already acquired semaphore → True.
        """
        _, client, registered = _make_hass(vm_ids=[101, 102])

        backup_2_started = asyncio.Event()
        call_count = 0

        async def tracking_vzdump(hass, node, vmid, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                backup_2_started.set()
            return "UPID:ok"

        client.start_vzdump = tracking_vzdump

        backup_2_ran_before_sleep_finished = []
        _real_sleep = asyncio.sleep

        async def fake_sleep(seconds):
            await _real_sleep(0)  # yield to event loop without recursing into fake_sleep
            backup_2_ran_before_sleep_finished.append(backup_2_started.is_set())

        sc = MagicMock()
        sc.data = {
            "node": "node1",
            "storage": "local",
            "include_vms": True,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 5,
        }

        with patch("custom_components.proxmox_sensors.services.asyncio.sleep", fake_sleep):
            await registered["backup_all"](sc)

        assert call_count == 2, "Both backups must have run"
        assert backup_2_ran_before_sleep_finished == [True], (
            "Backup 2 must start before sleep of backup 1 finishes "
            "(semaphore must be released before sleep)"
        )

    @pytest.mark.asyncio
    async def test_no_sleep_after_last_backup(self):
        """Sleep must NOT be called after the last backup."""
        _, client, registered = _make_hass(vm_ids=[101])

        sleep_calls = []

        async def fake_sleep(seconds):
            sleep_calls.append(seconds)

        sc = MagicMock()
        sc.data = {
            "node": "node1",
            "storage": "local",
            "include_vms": True,
            "include_cts": False,
            "mode": "snapshot",
            "compress": "zstd",
            "max_concurrent": 1,
            "delay_between": 10,
        }

        with patch("custom_components.proxmox_sensors.services.asyncio.sleep", fake_sleep):
            await registered["backup_all"](sc)

        assert sleep_calls == [], "sleep must not be called after the last backup"
