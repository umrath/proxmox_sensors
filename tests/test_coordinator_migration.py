"""
Tests für _build_vms_dict() und _build_cts_dict() im Coordinator.

Diese Tests SCHEITERN vor dem Fix (die Funktionen existieren noch nicht),
und werden GRÜN nach Fix 2 (Extraktion + Cluster-Resources-Enrichment).
"""

import pytest
from custom_components.proxmox_sensors.coordinator import _build_vms_dict, _build_cts_dict


# ---------------------------------------------------------------------------
# Hilfsdaten
# ---------------------------------------------------------------------------

def vm_resource(vmid, node, status="running", **extra):
    """Minimaler cluster/resources-Eintrag für eine VM."""
    return {"type": "qemu", "vmid": vmid, "node": node, "status": status,
            "cpu": 0.1, "mem": 512 * 1024**2, "maxmem": 2 * 1024**3,
            "disk": 0, "maxdisk": 10 * 1024**3, "uptime": 3600,
            "netin": 0, "netout": 0, **extra}


def ct_resource(vmid, node, status="running", **extra):
    """Minimaler cluster/resources-Eintrag für einen Container."""
    return {"type": "lxc", "vmid": vmid, "node": node, "status": status,
            "cpu": 0.05, "mem": 256 * 1024**2, "maxmem": 1 * 1024**3,
            "disk": 0, "maxdisk": 5 * 1024**3, "uptime": 1800,
            "netin": 0, "netout": 0, **extra}


def vm_local(vmid, name="test-vm", status="running", **extra):
    """Minimaler nodes/{node}/qemu-Eintrag."""
    return {"vmid": vmid, "name": name, "status": status,
            "cpu": 0.1, "mem": 512 * 1024**2, "maxmem": 2 * 1024**3,
            "disk": 0, "maxdisk": 10 * 1024**3, "uptime": 3600,
            "netin": 0, "netout": 0, **extra}


def ct_local(vmid, name="test-ct", status="running", **extra):
    """Minimaler nodes/{node}/lxc-Eintrag."""
    return {"vmid": vmid, "name": name, "status": status,
            "cpu": 0.05, "mem": 256 * 1024**2, "maxmem": 1 * 1024**3,
            "disk": 0, "maxdisk": 5 * 1024**3, "uptime": 1800,
            "netin": 0, "netout": 0, **extra}


# ===========================================================================
# _build_vms_dict
# ===========================================================================

class TestBuildVmsDictLocalVMs:
    """VMs, die noch auf dem konfigurierten Node laufen."""

    def test_local_vm_is_included(self):
        result = _build_vms_dict([vm_local(101)], [], ["101"], "node1")
        assert "node1:101" in result

    def test_local_vm_status_preserved(self):
        result = _build_vms_dict([vm_local(101, status="stopped")], [], ["101"], "node1")
        assert result["node1:101"]["status"] == "stopped"

    def test_local_vm_has_correct_current_node(self):
        result = _build_vms_dict([vm_local(101)], [], ["101"], "node1")
        assert result["node1:101"]["current_node"] == "node1"

    def test_local_vm_migrated_flag_is_false(self):
        """migrated muss explizit False sein (nicht None) — Sensor-Tests und services.py verlassen sich darauf."""
        result = _build_vms_dict([vm_local(101)], [], ["101"], "node1")
        assert result["node1:101"].get("migrated") is False

    def test_unselected_local_vm_excluded(self):
        result = _build_vms_dict([vm_local(101)], [], ["999"], "node1")
        assert "node1:101" not in result

    def test_empty_selection_includes_all_local_vms(self):
        vms = [vm_local(101), vm_local(202)]
        result = _build_vms_dict(vms, [], [], "node1")
        assert "node1:101" in result
        assert "node1:202" in result

    def test_multiple_local_vms(self):
        vms = [vm_local(101), vm_local(202), vm_local(303)]
        result = _build_vms_dict(vms, [], ["101", "202", "303"], "node1")
        assert len(result) == 3

    def test_vm_without_vmid_skipped(self):
        result = _build_vms_dict([{"name": "no-id"}], [], [], "node1")
        assert len(result) == 0

    def test_default_fields_set_for_missing_keys(self):
        """cpu/mem/etc. sollen auf 0 defaulten wenn nicht vorhanden."""
        result = _build_vms_dict([{"vmid": 101, "status": "running"}], [], ["101"], "node1")
        entry = result["node1:101"]
        for field in ("cpu", "mem", "maxmem", "disk", "maxdisk", "uptime", "netin", "netout"):
            assert field in entry, f"Feld '{field}' fehlt"
            assert entry[field] == 0


class TestBuildVmsDictMigratedVMs:
    """VMs, die auf einen anderen Node migriert wurden (das Hauptproblem)."""

    def test_migrated_vm_included_from_cluster_resources(self):
        """Kernanforderung: migrierte VM muss über cluster_resources gefunden werden."""
        result = _build_vms_dict(
            vms=[],  # VM nicht mehr auf node1
            cluster_resources=[vm_resource(101, "node2")],
            selected_vms=["101"],
            node="node1",
        )
        assert "node1:101" in result, (
            "Migrierte VM (101) muss unter ihrem Original-Key node1:101 "
            "im Ergebnis stehen — der Sensor sucht immer nach diesem Key."
        )

    def test_migrated_vm_current_node_reflects_actual_location(self):
        result = _build_vms_dict([], [vm_resource(101, "node2")], ["101"], "node1")
        assert result["node1:101"]["current_node"] == "node2"

    def test_migrated_vm_has_migrated_flag(self):
        result = _build_vms_dict([], [vm_resource(101, "node2")], ["101"], "node1")
        assert result["node1:101"]["migrated"] is True

    def test_migrated_vm_status_from_cluster_resources(self):
        result = _build_vms_dict(
            [], [vm_resource(101, "node2", status="running")], ["101"], "node1"
        )
        assert result["node1:101"]["status"] == "running"

    def test_migrated_vm_cpu_from_cluster_resources(self):
        res = vm_resource(101, "node2")
        res["cpu"] = 0.42
        result = _build_vms_dict([], [res], ["101"], "node1")
        assert result["node1:101"]["cpu"] == pytest.approx(0.42)

    def test_unselected_migrated_vm_excluded(self):
        result = _build_vms_dict([], [vm_resource(101, "node2")], ["999"], "node1")
        assert "node1:101" not in result

    def test_empty_selection_includes_migrated_vm(self):
        result = _build_vms_dict([], [vm_resource(101, "node2")], [], "node1")
        assert "node1:101" in result

    def test_lxc_type_not_included_in_vms_dict(self):
        """Container-Ressourcen dürfen nicht in den VM-Dict wandern."""
        result = _build_vms_dict([], [ct_resource(200, "node2")], ["200"], "node1")
        assert "node1:200" not in result

    def test_storage_type_not_included_in_vms_dict(self):
        result = _build_vms_dict(
            [], [{"type": "storage", "vmid": 101, "node": "node2"}], ["101"], "node1"
        )
        assert "node1:101" not in result

    def test_local_vm_takes_precedence_over_cluster_resources(self):
        """Wenn VM lokal vorhanden ist, darf cluster_resources sie nicht überschreiben."""
        local = vm_local(101, name="local-name", status="running")
        cluster = vm_resource(101, "node1", status="stopped")  # abweichender Status
        cluster["name"] = "cluster-name"

        result = _build_vms_dict([local], [cluster], ["101"], "node1")
        assert result["node1:101"]["name"] == "local-name"
        assert result["node1:101"]["status"] == "running"
        assert result["node1:101"].get("migrated") is False

    def test_migrated_vm_node_field_uses_configured_node_for_entity_id_stability(self):
        """
        KRITISCH: Das 'node'-Feld migrierter VMs muss den konfigurierten Node enthalten,
        nicht den aktuellen Aufenthaltsort.

        sensor/__init__.py liest vm_data.get('node', node) um die Entity zu bauen:
          uid = f"proxmox_vm_{node}_{vm_id}_status_v1"
        Wenn 'node' auf 'node2' zeigt, entsteht eine andere unique_id als vor der Migration
        und HA legt eine neue Entity an / löscht die alte.
        """
        result = _build_vms_dict(
            vms=[],
            cluster_resources=[vm_resource(101, "node2")],
            selected_vms=["101"],
            node="node1",
        )
        assert result["node1:101"]["node"] == "node1", (
            "base['node'] muss 'node1' (configured node) sein, "
            "nicht 'node2' (current_node) — sonst ändert sich die unique_id."
        )
        assert result["node1:101"]["current_node"] == "node2"

    def test_migrated_vm_default_fields_set(self):
        """Fehlende Felder werden auch bei migrierten VMs auf 0 gesetzt."""
        result = _build_vms_dict(
            [], [{"type": "qemu", "vmid": 101, "node": "node2", "status": "running"}],
            ["101"], "node1"
        )
        entry = result["node1:101"]
        for field in ("cpu", "mem", "maxmem", "disk", "maxdisk", "uptime", "netin", "netout"):
            assert field in entry, f"Feld '{field}' fehlt bei migrierter VM"


class TestBuildVmsDictEdgeCases:
    def test_empty_inputs(self):
        result = _build_vms_dict([], [], [], "node1")
        assert result == {}

    def test_none_vms_treated_as_empty(self):
        result = _build_vms_dict(None, [], [], "node1")
        assert result == {}

    def test_none_cluster_resources_treated_as_empty(self):
        result = _build_vms_dict([vm_local(101)], None, ["101"], "node1")
        assert "node1:101" in result

    def test_cluster_resource_without_vmid_skipped(self):
        result = _build_vms_dict([], [{"type": "qemu", "node": "node2"}], [], "node1")
        assert len(result) == 0

    def test_non_dict_in_cluster_resources_skipped(self):
        result = _build_vms_dict([], ["not-a-dict", None, 42], [], "node1")
        assert result == {}


# ===========================================================================
# _build_cts_dict (analoges Muster für Container)
# ===========================================================================

class TestBuildCtsDictLocalCTs:
    def test_local_ct_is_included(self):
        result = _build_cts_dict([ct_local(201)], [], ["201"], "node1")
        assert "node1:201" in result

    def test_local_ct_has_correct_current_node(self):
        result = _build_cts_dict([ct_local(201)], [], ["201"], "node1")
        assert result["node1:201"]["current_node"] == "node1"

    def test_local_ct_migrated_flag_is_false(self):
        result = _build_cts_dict([ct_local(201)], [], ["201"], "node1")
        assert result["node1:201"].get("migrated") is False

    def test_unselected_local_ct_excluded(self):
        result = _build_cts_dict([ct_local(201)], [], ["999"], "node1")
        assert "node1:201" not in result


class TestBuildCtsDictMigratedCTs:
    def test_migrated_ct_included_from_cluster_resources(self):
        result = _build_cts_dict(
            cts=[],
            cluster_resources=[ct_resource(201, "node2")],
            selected_cts=["201"],
            node="node1",
        )
        assert "node1:201" in result

    def test_migrated_ct_current_node_reflects_actual_location(self):
        result = _build_cts_dict([], [ct_resource(201, "node2")], ["201"], "node1")
        assert result["node1:201"]["current_node"] == "node2"

    def test_migrated_ct_has_migrated_flag(self):
        result = _build_cts_dict([], [ct_resource(201, "node2")], ["201"], "node1")
        assert result["node1:201"]["migrated"] is True

    def test_qemu_type_not_included_in_cts_dict(self):
        result = _build_cts_dict([], [vm_resource(101, "node2")], ["101"], "node1")
        assert "node1:101" not in result

    def test_local_ct_takes_precedence_over_cluster_resources(self):
        local = ct_local(201, name="local-ct", status="running")
        cluster = ct_resource(201, "node1", status="stopped")
        cluster["name"] = "cluster-ct"

        result = _build_cts_dict([local], [cluster], ["201"], "node1")
        assert result["node1:201"]["name"] == "local-ct"
        assert result["node1:201"].get("migrated") is False

    def test_migrated_ct_node_field_uses_configured_node_for_entity_id_stability(self):
        result = _build_cts_dict(
            cts=[],
            cluster_resources=[ct_resource(201, "node2")],
            selected_cts=["201"],
            node="node1",
        )
        assert result["node1:201"]["node"] == "node1"
        assert result["node1:201"]["current_node"] == "node2"
