"""
Tests für Migrations-Verhalten der CT-Sensoren (analog zu VM-Tests).
"""

import pytest
from unittest.mock import MagicMock
from custom_components.proxmox_sensors.sensor.ct import (
    ProxmoxContainerSensor,
    ProxmoxContainerAttributeSensor,
)


def make_coordinator(cts_dict=None, cluster_resources=None):
    coord = MagicMock()
    coord.config_entry.data = {"server_id": "node1"}
    coord.data = {
        "cts": cts_dict if cts_dict is not None else {},
        "cluster_resources": cluster_resources if cluster_resources is not None else [],
    }
    return coord


def ct_entry(vmid=201, status="running", current_node="node1", migrated=False, **extra):
    return {
        "vmid": vmid, "status": status, "name": "test-ct",
        "cpu": 0.1, "mem": 256 * 1024**2, "maxmem": 1 * 1024**3,
        "disk": 1 * 1024**3, "maxdisk": 5 * 1024**3, "uptime": 3600,
        "netin": 512 * 1024**2, "netout": 256 * 1024**2,
        "cpus": 2,
        "current_node": current_node, "migrated": migrated,
        **extra,
    }


class TestCTSensorBugDocumentation:
    def test_bug_status_shows_unknown_when_ct_migrated(self):
        coord = make_coordinator(cts_dict={})
        sensor = ProxmoxContainerSensor(coord, 201, "node1", "test-ct", guest_key="node1:201")
        assert sensor.native_value == "Unknown"

    def test_bug_attribute_sensor_returns_none_when_ct_migrated(self):
        coord = make_coordinator(cts_dict={})
        sensor = ProxmoxContainerAttributeSensor(
            coord, 201, "node1", "test-ct", "cpu_usage", "%", "mdi:cpu",
            guest_key="node1:201"
        )
        assert sensor.native_value is None


class TestCTSensorWithEnrichedCoordinatorData:
    def test_status_shows_running_for_migrated_ct(self):
        coord = make_coordinator(
            cts_dict={"node1:201": ct_entry(status="running", current_node="node2", migrated=True)}
        )
        sensor = ProxmoxContainerSensor(coord, 201, "node1", "test-ct", guest_key="node1:201")
        assert sensor.native_value == "Running"

    def test_cpu_attribute_sensor_works_for_migrated_ct(self):
        coord = make_coordinator(
            cts_dict={"node1:201": ct_entry(cpu=0.4, current_node="node2", migrated=True)}
        )
        sensor = ProxmoxContainerAttributeSensor(
            coord, 201, "node1", "test-ct", "cpu_usage", "%", "mdi:cpu",
            guest_key="node1:201"
        )
        assert sensor.native_value == pytest.approx(40.0)

    def test_disk_used_attribute_works_for_migrated_ct(self):
        coord = make_coordinator(
            cts_dict={"node1:201": ct_entry(disk=2 * 1024**3, current_node="node2", migrated=True)}
        )
        sensor = ProxmoxContainerAttributeSensor(
            coord, 201, "node1", "test-ct", "disk_used", "GB", "mdi:harddisk",
            guest_key="node1:201"
        )
        assert sensor.native_value == pytest.approx(2.0)


class TestCTSensorMigrationAttributes:
    def test_status_sensor_exposes_current_node_when_migrated(self):
        coord = make_coordinator(
            cts_dict={"node1:201": ct_entry(current_node="node2", migrated=True)}
        )
        sensor = ProxmoxContainerSensor(coord, 201, "node1", "test-ct", guest_key="node1:201")
        attrs = sensor.extra_state_attributes
        assert attrs.get("current_node") == "node2"

    def test_status_sensor_exposes_migrated_true_when_migrated(self):
        coord = make_coordinator(
            cts_dict={"node1:201": ct_entry(current_node="node2", migrated=True)}
        )
        sensor = ProxmoxContainerSensor(coord, 201, "node1", "test-ct", guest_key="node1:201")
        assert sensor.extra_state_attributes.get("migrated") is True

    def test_status_sensor_exposes_current_node_when_local(self):
        coord = make_coordinator(
            cts_dict={"node1:201": ct_entry(current_node="node1", migrated=False)}
        )
        sensor = ProxmoxContainerSensor(coord, 201, "node1", "test-ct", guest_key="node1:201")
        assert sensor.extra_state_attributes.get("current_node") == "node1"

    def test_status_sensor_exposes_migrated_false_when_local(self):
        coord = make_coordinator(
            cts_dict={"node1:201": ct_entry(current_node="node1", migrated=False)}
        )
        sensor = ProxmoxContainerSensor(coord, 201, "node1", "test-ct", guest_key="node1:201")
        assert sensor.extra_state_attributes.get("migrated") is False

    def test_status_sensor_safe_when_no_ct_data(self):
        coord = make_coordinator(cts_dict={})
        sensor = ProxmoxContainerSensor(coord, 201, "node1", "test-ct", guest_key="node1:201")
        attrs = sensor.extra_state_attributes
        assert isinstance(attrs, dict)
        assert "current_node" not in attrs
