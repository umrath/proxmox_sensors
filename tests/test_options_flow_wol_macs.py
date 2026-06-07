"""
Test M8: WOL MACs survive options flow save.

The bug: async_update_entry sets options={"wol_macs": ...} but the subsequent
async_create_entry(data={}) overwrites options to {}.

Fix: pass wol_macs through async_create_entry(data={"wol_macs": ...}).
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch


def _make_options_flow(wol_mac_map=None, node="pve-node"):
    """Create a ProxmoxOptionsFlow instance with minimal mocks."""
    import sys
    # Ensure options_flow can be imported (conftest stubs HA modules)
    from custom_components.proxmox_sensors.options_flow import ProxmoxOptionsFlow

    flow = ProxmoxOptionsFlow.__new__(ProxmoxOptionsFlow)

    conf = {
        "host": "192.168.1.1",
        "username": "root@pam",
        "password": "secret",
        "node": node,
        "platform_type": "PVE",
        "verify_ssl": False,
    }
    entry = MagicMock()
    entry.data = conf
    entry.options = {"wol_macs": wol_mac_map or {}}
    entry.entry_id = "entry-1"

    flow.config_entry = entry
    flow._cluster_nodes = [node]

    hass = MagicMock()
    hass.data = {}
    flow.hass = hass

    # Capture calls
    flow._update_entry_calls = []
    flow._create_entry_calls = []

    def fake_update_entry(cfg_entry, **kwargs):
        flow._update_entry_calls.append(kwargs)

    hass.config_entries.async_update_entry.side_effect = fake_update_entry
    hass.config_entries.async_reload = AsyncMock()

    def fake_create_entry(**kwargs):
        flow._create_entry_calls.append(kwargs)
        return {"type": "create_entry", **kwargs}

    flow.async_create_entry = MagicMock(side_effect=fake_create_entry)

    return flow


class TestWolMacsNotWipedAfterOptionsSave:

    @pytest.mark.asyncio
    async def test_wol_macs_passed_to_create_entry_not_wiped(self):
        """WOL MACs must survive the options save — async_create_entry must
        include wol_macs in its data dict so HA stores them as options."""
        from custom_components.proxmox_sensors.options_flow import ProxmoxOptionsFlow

        flow = _make_options_flow(
            wol_mac_map={"pve-node": "aa:bb:cc:dd:ee:ff"},
            node="pve-node",
        )

        user_input = {
            "verify_ssl": False,
            "enable_lm_sensors": True,
            "enable_physical_disks": True,
            "enable_smart_monitoring": True,
            "enable_node_controls": False,
            "wol_mac_pve-node": "aa:bb:cc:dd:ee:ff",
        }

        with patch(
            "custom_components.proxmox_sensors.options_flow.ProxmoxClient"
        ) as MockClient:
            MockClient.return_value.get_vms = AsyncMock(return_value=[])
            MockClient.return_value.get_containers = AsyncMock(return_value=[])
            MockClient.return_value.get_storages = AsyncMock(return_value=[])
            MockClient.return_value.get_node_network = AsyncMock(return_value=[])

            await flow.async_step_pve(user_input)

        # The async_create_entry call must include wol_macs
        assert flow._create_entry_calls, "async_create_entry was never called"
        create_data = flow._create_entry_calls[-1].get("data", {})
        assert "wol_macs" in create_data, (
            f"async_create_entry data must include 'wol_macs'; got: {create_data}"
        )
        assert create_data["wol_macs"].get("pve-node") == "aa:bb:cc:dd:ee:ff", (
            f"MAC address not preserved: {create_data['wol_macs']}"
        )

    @pytest.mark.asyncio
    async def test_empty_wol_input_yields_empty_dict(self):
        """When user clears the MAC field, wol_macs should be empty dict,
        not a dict with empty-string values."""
        flow = _make_options_flow(node="pve-node")

        user_input = {
            "verify_ssl": False,
            "enable_lm_sensors": True,
            "enable_physical_disks": True,
            "enable_smart_monitoring": True,
            "enable_node_controls": False,
            "wol_mac_pve-node": "",  # cleared
        }

        with patch(
            "custom_components.proxmox_sensors.options_flow.ProxmoxClient"
        ) as MockClient:
            MockClient.return_value.get_vms = AsyncMock(return_value=[])
            MockClient.return_value.get_containers = AsyncMock(return_value=[])
            MockClient.return_value.get_storages = AsyncMock(return_value=[])
            MockClient.return_value.get_node_network = AsyncMock(return_value=[])

            await flow.async_step_pve(user_input)

        create_data = flow._create_entry_calls[-1].get("data", {})
        wol_macs = create_data.get("wol_macs", {})
        assert "pve-node" not in wol_macs, (
            f"Empty MAC must not be stored; got wol_macs={wol_macs}"
        )

    @pytest.mark.asyncio
    async def test_async_update_entry_does_not_set_options(self):
        """async_update_entry must not set options= (letting async_create_entry
        handle options is the correct HA pattern)."""
        flow = _make_options_flow(node="pve-node")

        user_input = {
            "verify_ssl": False,
            "enable_lm_sensors": True,
            "enable_physical_disks": True,
            "enable_smart_monitoring": True,
            "enable_node_controls": False,
            "wol_mac_pve-node": "11:22:33:44:55:66",
        }

        with patch(
            "custom_components.proxmox_sensors.options_flow.ProxmoxClient"
        ) as MockClient:
            MockClient.return_value.get_vms = AsyncMock(return_value=[])
            MockClient.return_value.get_containers = AsyncMock(return_value=[])
            MockClient.return_value.get_storages = AsyncMock(return_value=[])
            MockClient.return_value.get_node_network = AsyncMock(return_value=[])

            await flow.async_step_pve(user_input)

        for call_kwargs in flow._update_entry_calls:
            options_in_update = call_kwargs.get("options")
            if options_in_update is not None:
                # If options= is passed, it must NOT be {} (which would wipe wol_macs)
                assert options_in_update != {}, (
                    "async_update_entry must not pass options={} — it wipes wol_macs. "
                    "Pass wol_macs via async_create_entry(data=...) instead."
                )
