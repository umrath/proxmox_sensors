"""
Tests for second-review HIGH fixes.

H1 — PBSBaseButton must not write raw HA state via hass.states.async_set;
     it relies on a coordinator refresh so PBSLastActionSensor recomputes.
H3 — run_sync must not iterate over the characters of a string 'store' field.
H4 — services are unregistered when the last config entry is unloaded.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# H1 — PBS maintenance buttons no longer poke raw state
# ---------------------------------------------------------------------------

class TestPBSButtonNoRawStateWrite:

    def _make_gc_button(self):
        from custom_components.proxmox_sensors.button import PBSGCButton

        coordinator = MagicMock()
        coordinator.async_request_refresh = AsyncMock()
        client = MagicMock()
        button = PBSGCButton(coordinator, client, "main")
        button.hass = MagicMock()
        return button

    def test_base_button_has_no_update_last_action(self):
        """The raw-state-write helper must be gone entirely."""
        from custom_components.proxmox_sensors.button import PBSBaseButton
        assert not hasattr(PBSBaseButton, "_update_last_action"), (
            "_update_last_action wrote raw HA state and must be removed (H1)"
        )

    @pytest.mark.asyncio
    async def test_gc_press_does_not_set_state_and_refreshes(self):
        from custom_components.proxmox_sensors import pbs_actions

        button = self._make_gc_button()
        with patch.object(pbs_actions, "run_gc", new=AsyncMock(return_value=None)):
            # button.async_press imports run_gc at module import time; patch the
            # reference used inside button.py instead
            import custom_components.proxmox_sensors.button as btn_mod
            with patch.object(btn_mod, "run_gc", new=AsyncMock(return_value=None)):
                await button.async_press()

        button.hass.states.async_set.assert_not_called()
        button.coordinator.async_request_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# H3 — run_sync handles a string 'store' field without char iteration
# ---------------------------------------------------------------------------

class TestRunSyncStoreField:

    @pytest.mark.asyncio
    async def test_string_store_not_iterated_char_by_char(self):
        from custom_components.proxmox_sensors.pbs_actions import run_sync

        client = MagicMock()
        # one remote whose 'store' is a single string (PBS default for one store)
        client.pbs_get = AsyncMock(
            return_value=[{"name": "remote1", "store": "backups"}]
        )
        client.pbs_post = AsyncMock(return_value={"ok": True})

        await run_sync(client, MagicMock(), "main")

        # Exactly one sync POST, with remote-store == the whole string "backups"
        assert client.pbs_post.await_count == 1, (
            f"Expected 1 sync call, got {client.pbs_post.await_count} — "
            "string store was iterated character-by-character (H3)"
        )
        _, kwargs = None, None
        call = client.pbs_post.await_args
        # data is passed positionally as third arg: pbs_post(hass, endpoint, data)
        data = call.args[2]
        assert data["remote-store"] == "backups"

    @pytest.mark.asyncio
    async def test_list_store_still_works(self):
        from custom_components.proxmox_sensors.pbs_actions import run_sync

        client = MagicMock()
        client.pbs_get = AsyncMock(
            return_value=[{"name": "remote1", "store": ["a", "b"]}]
        )
        client.pbs_post = AsyncMock(return_value={"ok": True})

        await run_sync(client, MagicMock(), "main")
        assert client.pbs_post.await_count == 2

    @pytest.mark.asyncio
    async def test_missing_store_yields_no_calls(self):
        from custom_components.proxmox_sensors.pbs_actions import run_sync

        client = MagicMock()
        client.pbs_get = AsyncMock(return_value=[{"name": "remote1"}])
        client.pbs_post = AsyncMock(return_value={"ok": True})

        await run_sync(client, MagicMock(), "main")
        assert client.pbs_post.await_count == 0


# ---------------------------------------------------------------------------
# H4 — services unregistered when last entry unloads
# ---------------------------------------------------------------------------

class TestServicesUnregisteredOnUnload:

    @pytest.mark.asyncio
    async def test_last_entry_unload_removes_services(self):
        import custom_components.proxmox_sensors as comp

        hass = MagicMock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        # Real dict so the empty-check works
        entry = MagicMock()
        entry.entry_id = "e1"
        entry.data = {"platform_type": "PVE"}
        hass.data = {comp.DOMAIN: {"e1": {"client": MagicMock()}}}

        removed = []
        hass.services.has_service = MagicMock(return_value=True)
        hass.services.async_remove = MagicMock(side_effect=lambda d, s: removed.append(s))

        ok = await comp.async_unload_entry(hass, entry)

        assert ok is True
        assert set(removed) == {
            "backup_all",
            "create_vzdump_backup",
            "confirm_shutdown_node",
            "confirm_reboot_node",
            "wake_node",
        }, f"Not all services were removed: {removed}"

    @pytest.mark.asyncio
    async def test_other_entries_remain_keep_services(self):
        import custom_components.proxmox_sensors as comp

        hass = MagicMock()
        hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

        entry = MagicMock()
        entry.entry_id = "e1"
        entry.data = {"platform_type": "PVE"}
        # Two entries — removing one leaves the other, so services stay
        hass.data = {comp.DOMAIN: {"e1": {}, "e2": {}}}

        hass.services.has_service = MagicMock(return_value=True)
        hass.services.async_remove = MagicMock()

        await comp.async_unload_entry(hass, entry)

        hass.services.async_remove.assert_not_called()
