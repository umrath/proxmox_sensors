"""
Tests für H2: ProxmoxConfigFlow.VERSION muss ENTRY_VERSION entsprechen.
VERSION=1 vs ENTRY_VERSION=2 → neue Einträge lösen nach jedem Start Migration aus.
"""

from custom_components.proxmox_sensors.config_flow import ProxmoxConfigFlow
from custom_components.proxmox_sensors.__init__ import ENTRY_VERSION


class TestConfigFlowVersion:

    def test_config_flow_version_matches_entry_version(self):
        assert ProxmoxConfigFlow.VERSION == ENTRY_VERSION

    def test_config_flow_version_is_2(self):
        assert ProxmoxConfigFlow.VERSION == 2
