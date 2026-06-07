"""
Tests für Migrations-Verhalten der VM-Sensoren.

Sensor-Tests sind in zwei Gruppen:
- "bug_": dokumentieren das aktuelle Fehlverhalten (laufen DURCH, aber zeigen den Bug)
- "fix_": beschreiben das erwünschte Verhalten nach Fix 2 + 4 (SCHEITERN vor dem Fix)
"""

import pytest
from unittest.mock import MagicMock
from custom_components.proxmox_sensors.sensor.vm import (
    ProxmoxVMSensor,
    ProxmoxVMAttributeSensor,
)


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def make_coordinator(vms_dict=None, cluster_resources=None):
    coord = MagicMock()
    coord.config_entry.data = {"server_id": "node1"}
    coord.data = {
        "vms": vms_dict if vms_dict is not None else {},
        "cluster_resources": cluster_resources if cluster_resources is not None else [],
    }
    return coord


def vm_entry(vmid=101, status="running", current_node="node1", migrated=False, **extra):
    return {
        "vmid": vmid, "status": status, "name": "test-vm",
        "cpu": 0.25, "mem": 512 * 1024**2, "maxmem": 2 * 1024**3,
        "disk": 0, "maxdisk": 10 * 1024**3, "uptime": 7200,
        "netin": 1024**3, "netout": 512 * 1024**2,
        "cpus": 4,
        "current_node": current_node, "migrated": migrated,
        **extra,
    }


# ===========================================================================
# Bug-Dokumentation: Verhalten VOR dem Fix
# ===========================================================================

class TestVMSensorBugDocumentation:
    """
    Diese Tests beschreiben das aktuelle Fehlverhalten.
    Sie laufen durch (assert ist korrekt für den Bug),
    dienen aber als Dokumentation was repariert wird.
    """

    def test_bug_status_shows_unknown_when_vm_migrated(self):
        """BUG: Sensor liefert 'Unknown' wenn VM aus dem vms-Dict verschwunden ist."""
        coord = make_coordinator(vms_dict={})  # VM weg nach Migration
        sensor = ProxmoxVMSensor(coord, 101, "node1", "test-vm", guest_key="node1:101")
        assert sensor.native_value == "Unknown"  # ← das ist der Bug

    def test_bug_attribute_sensor_returns_none_when_vm_migrated(self):
        """BUG: Attribut-Sensor liefert None wenn VM migriert."""
        coord = make_coordinator(vms_dict={})
        sensor = ProxmoxVMAttributeSensor(
            coord, 101, "node1", "test-vm", "cpu_usage", "%", "mdi:cpu",
            guest_key="node1:101"
        )
        assert sensor.native_value is None  # ← das ist der Bug


# ===========================================================================
# Fix-Verifikation: Verhalten NACH Fix 2 + Task 4
# ===========================================================================

class TestVMSensorWithEnrichedCoordinatorData:
    """
    Nach Fix 2 stellt der Coordinator migrierte VMs im vms-Dict bereit.
    Diese Tests verifizieren, dass der Sensor die angereicherten Daten korrekt liest.
    """

    def test_status_shows_running_for_migrated_vm(self):
        coord = make_coordinator(
            vms_dict={"node1:101": vm_entry(status="running", current_node="node2", migrated=True)}
        )
        sensor = ProxmoxVMSensor(coord, 101, "node1", "test-vm", guest_key="node1:101")
        assert sensor.native_value == "Running"

    def test_status_shows_stopped_for_migrated_vm(self):
        coord = make_coordinator(
            vms_dict={"node1:101": vm_entry(status="stopped", current_node="node2", migrated=True)}
        )
        sensor = ProxmoxVMSensor(coord, 101, "node1", "test-vm", guest_key="node1:101")
        assert sensor.native_value == "Stopped"

    def test_cpu_attribute_sensor_works_for_migrated_vm(self):
        coord = make_coordinator(
            vms_dict={"node1:101": vm_entry(cpu=0.5, current_node="node2", migrated=True)}
        )
        sensor = ProxmoxVMAttributeSensor(
            coord, 101, "node1", "test-vm", "cpu_usage", "%", "mdi:cpu",
            guest_key="node1:101"
        )
        assert sensor.native_value == pytest.approx(50.0)

    def test_memory_attribute_sensor_works_for_migrated_vm(self):
        coord = make_coordinator(
            vms_dict={"node1:101": vm_entry(
                mem=1 * 1024**3, current_node="node2", migrated=True
            )}
        )
        sensor = ProxmoxVMAttributeSensor(
            coord, 101, "node1", "test-vm", "memory_used", "GB", "mdi:memory",
            guest_key="node1:101"
        )
        assert sensor.native_value == pytest.approx(1.0)

    def test_uptime_attribute_sensor_works_for_migrated_vm(self):
        coord = make_coordinator(
            vms_dict={"node1:101": vm_entry(uptime=3600, current_node="node2", migrated=True)}
        )
        sensor = ProxmoxVMAttributeSensor(
            coord, 101, "node1", "test-vm", "uptime", "h", "mdi:timer",
            guest_key="node1:101"
        )
        assert sensor.native_value == pytest.approx(1.0)

    def test_network_rx_sensor_works_for_migrated_vm(self):
        coord = make_coordinator(
            vms_dict={"node1:101": vm_entry(netin=1024**3, current_node="node2", migrated=True)}
        )
        sensor = ProxmoxVMAttributeSensor(
            coord, 101, "node1", "test-vm", "network_rx", "GB", "mdi:download",
            guest_key="node1:101"
        )
        assert sensor.native_value == pytest.approx(1.0)


# ===========================================================================
# Task 4: current_node + migrated in extra_state_attributes
# ===========================================================================

class TestVMSensorMigrationAttributes:
    """
    Tests für die neuen current_node + migrated Attribute.
    SCHEITERN vor Task 4 (ProxmoxVMSensor hat kein extra_state_attributes).
    """

    def test_status_sensor_exposes_current_node_when_migrated(self):
        coord = make_coordinator(
            vms_dict={"node1:101": vm_entry(current_node="node2", migrated=True)}
        )
        sensor = ProxmoxVMSensor(coord, 101, "node1", "test-vm", guest_key="node1:101")
        attrs = sensor.extra_state_attributes
        assert attrs.get("current_node") == "node2", (
            "current_node muss im extra_state_attributes stehen damit "
            "HA-Automationen auf die Migrations-Information reagieren können."
        )

    def test_status_sensor_exposes_migrated_true_when_migrated(self):
        coord = make_coordinator(
            vms_dict={"node1:101": vm_entry(current_node="node2", migrated=True)}
        )
        sensor = ProxmoxVMSensor(coord, 101, "node1", "test-vm", guest_key="node1:101")
        assert sensor.extra_state_attributes.get("migrated") is True

    def test_status_sensor_exposes_current_node_when_local(self):
        coord = make_coordinator(
            vms_dict={"node1:101": vm_entry(current_node="node1", migrated=False)}
        )
        sensor = ProxmoxVMSensor(coord, 101, "node1", "test-vm", guest_key="node1:101")
        attrs = sensor.extra_state_attributes
        assert attrs.get("current_node") == "node1"

    def test_status_sensor_exposes_migrated_false_when_local(self):
        coord = make_coordinator(
            vms_dict={"node1:101": vm_entry(current_node="node1", migrated=False)}
        )
        sensor = ProxmoxVMSensor(coord, 101, "node1", "test-vm", guest_key="node1:101")
        assert sensor.extra_state_attributes.get("migrated") is False

    def test_status_sensor_empty_attrs_when_no_vm_data(self):
        """Wenn keine VM-Daten vorhanden, keine Exception im extra_state_attributes."""
        coord = make_coordinator(vms_dict={})
        sensor = ProxmoxVMSensor(coord, 101, "node1", "test-vm", guest_key="node1:101")
        attrs = sensor.extra_state_attributes
        assert isinstance(attrs, dict)

    def test_status_sensor_no_current_node_when_data_missing(self):
        coord = make_coordinator(vms_dict={})
        sensor = ProxmoxVMSensor(coord, 101, "node1", "test-vm", guest_key="node1:101")
        assert "current_node" not in sensor.extra_state_attributes
