"""
Tests für K2 und K3:
K2: entry-Parameter wird in button.py:56 durch coordinator.config_entry überschrieben.
K3: ProxmoxNodeButton.async_press() für "wake" ruft execute_node_command auf,
    das "wake" nicht kennt → sendet nie WOL.

Fix K2: Zeile 56 entfernen, function-Parameter entry direkt nutzen.
Fix K3: async_press() in ProxmoxNodeButton behandelt "wake" separat via WOL.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.proxmox_sensors.button import ProxmoxNodeButton


def _make_node_button(command, wol_mac=None):
    coordinator = MagicMock()
    coordinator.config_entry.options = {"wol_macs": {"node1": wol_mac} if wol_mac else {}}
    coordinator.data = {}

    client = MagicMock()
    client.execute_node_command = AsyncMock(return_value=True)

    button = ProxmoxNodeButton(coordinator, client, "node1", "Node", command, "mdi:test")
    button.hass = MagicMock()
    button.hass.services = MagicMock()
    button.hass.services.async_call = AsyncMock()
    return button


class TestProxmoxNodeButtonWake:

    @pytest.mark.asyncio
    async def test_wake_sends_wol_packet(self):
        """Pressing the wake button must call wake_on_lan.send_magic_packet."""
        button = _make_node_button("wake", wol_mac="AA:BB:CC:DD:EE:FF")
        await button.async_press()
        button.hass.services.async_call.assert_called_once_with(
            "wake_on_lan",
            "send_magic_packet",
            {"mac": "AA:BB:CC:DD:EE:FF"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_wake_does_not_call_execute_node_command(self):
        """execute_node_command must NOT be called for wake (it doesn't handle it)."""
        button = _make_node_button("wake", wol_mac="AA:BB:CC:DD:EE:FF")
        await button.async_press()
        button._client.execute_node_command.assert_not_called()

    @pytest.mark.asyncio
    async def test_wake_without_mac_does_not_crash(self):
        """If no MAC is configured, wake must log an error and return cleanly."""
        button = _make_node_button("wake", wol_mac=None)
        # Must not raise
        await button.async_press()
        button.hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_reboot_uses_execute_node_command(self):
        """Non-wake commands must still go through execute_node_command."""
        button = _make_node_button("reboot")
        await button.async_press()
        button._client.execute_node_command.assert_called_once_with(
            button.hass, "node1", "reboot"
        )

    @pytest.mark.asyncio
    async def test_shutdown_uses_execute_node_command(self):
        button = _make_node_button("shutdown")
        await button.async_press()
        button._client.execute_node_command.assert_called_once_with(
            button.hass, "node1", "shutdown"
        )
