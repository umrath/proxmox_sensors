"""
Tests für services.py: migrierte VMs/CTs dürfen nicht in den Mass-Backup aufgenommen werden.

Das Mass-Backup (backup_all) ruft nodes/{node}/vzdump auf — das funktioniert nur für
Guests, die tatsächlich auf diesem Node laufen. Eine migrierte VM liegt auf einem
anderen Node und kann so nicht gesichert werden.
"""

import pytest
from custom_components.proxmox_sensors.coordinator import _build_vms_dict, _build_cts_dict


def vm_resource(vmid, node, status="running"):
    return {"type": "qemu", "vmid": vmid, "node": node, "status": status}


def ct_resource(vmid, node, status="running"):
    return {"type": "lxc", "vmid": vmid, "node": node, "status": status}


def vm_local(vmid, status="running"):
    return {"vmid": vmid, "status": status}


def ct_local(vmid, status="running"):
    return {"vmid": vmid, "status": status}


# ---------------------------------------------------------------------------
# Hilfsfunktion: simuliert den services.py-Filter (backup_all)
# ---------------------------------------------------------------------------

def collect_backup_targets(vms_dict, cts_dict, node):
    """Replicates the filter logic in services.py handle_backup_all."""
    vm_list = []
    for vm_data in vms_dict.values():
        if not isinstance(vm_data, dict):
            continue
        if vm_data.get("migrated"):
            continue   # Bug-Fix: migrierte VMs überspringen
        if vm_data.get("node") != node:
            continue
        vmid = vm_data.get("vmid")
        if vmid is not None:
            vm_list.append(str(vmid))

    ct_list = []
    for ct_data in cts_dict.values():
        if not isinstance(ct_data, dict):
            continue
        if ct_data.get("migrated"):
            continue
        if ct_data.get("node") != node:
            continue
        ctid = ct_data.get("vmid")
        if ctid is not None:
            ct_list.append(str(ctid))

    return vm_list + ct_list


class TestBackupServiceMigrationFilter:

    def test_local_vm_included_in_backup(self):
        vms = _build_vms_dict([vm_local(101)], [], ["101"], "node1")
        targets = collect_backup_targets(vms, {}, "node1")
        assert "101" in targets

    def test_migrated_vm_excluded_from_backup(self):
        """
        VM 101 ist auf node2 migriert.
        backup_all auf node1 darf sie NICHT aufnehmen —
        nodes/node1/vzdump kann node2-VMs nicht sichern.
        """
        vms = _build_vms_dict(
            vms=[],
            cluster_resources=[vm_resource(101, "node2")],
            selected_vms=["101"],
            node="node1",
        )
        targets = collect_backup_targets(vms, {}, "node1")
        assert "101" not in targets, (
            "Migrierte VM 101 (aktuell auf node2) muss aus dem "
            "backup_all auf node1 ausgeschlossen sein."
        )

    def test_local_ct_included_in_backup(self):
        cts = _build_cts_dict([ct_local(201)], [], ["201"], "node1")
        targets = collect_backup_targets({}, cts, "node1")
        assert "201" in targets

    def test_migrated_ct_excluded_from_backup(self):
        cts = _build_cts_dict(
            cts=[],
            cluster_resources=[ct_resource(201, "node2")],
            selected_cts=["201"],
            node="node1",
        )
        targets = collect_backup_targets({}, cts, "node1")
        assert "201" not in targets

    def test_mix_local_and_migrated(self):
        """Lokale VMs werden gesichert, migrierte nicht."""
        vms = _build_vms_dict(
            vms=[vm_local(100), vm_local(101)],  # beide lokal
            cluster_resources=[vm_resource(102, "node2")],  # eine migriert
            selected_vms=["100", "101", "102"],
            node="node1",
        )
        targets = collect_backup_targets(vms, {}, "node1")
        assert "100" in targets
        assert "101" in targets
        assert "102" not in targets
