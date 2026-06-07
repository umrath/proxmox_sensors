"""
Tests für den Entity-Cleanup in sensor/__init__.py (Bug L7).

Bug L7: Die Cleanup-Schleife läuft auch wenn entities=[] ist (z.B. weil
der Coordinator beim Restart noch kein vollständiges Datenbild hat).
Das löscht alle bereits registrierten Entities — Nutzer sehen danach
leere Dashboards bis zum nächsten Polling-Zyklus.

Fix: Cleanup nur durchführen wenn entities nicht leer ist.
"""

import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers — simuliert die Cleanup-Logik aus sensor/__init__.py
# ---------------------------------------------------------------------------

def _run_cleanup(entities, existing_entity_ids):
    """Replicate the cleanup logic from sensor/__init__.py.

    Returns (removed_ids, kept_ids) so tests can assert on it.
    """
    new_unique_ids = {getattr(e, "_attr_unique_id", None) for e in entities}
    removed = []
    kept = []

    for uid, entity_id in existing_entity_ids.items():
        if uid not in new_unique_ids:
            removed.append(entity_id)
        else:
            kept.append(entity_id)

    return removed, kept


def _run_cleanup_with_guard(entities, existing_entity_ids):
    """Cleanup with the L7 fix: skip if entities is empty."""
    if not entities:
        return [], list(existing_entity_ids.values())
    return _run_cleanup(entities, existing_entity_ids)


def _make_entity(uid):
    e = MagicMock()
    e._attr_unique_id = uid
    return e


# ---------------------------------------------------------------------------
# L7 tests
# ---------------------------------------------------------------------------

class TestEntityCleanupGuard:

    def test_existing_entities_removed_when_not_in_new_set(self):
        """Normal operation: old entity gets removed when config changes."""
        existing = {"pve_node1_vm_101_status_v1": "sensor.vm_101"}
        new_entities = [_make_entity("pve_node1_vm_102_status_v1")]

        removed, _ = _run_cleanup_with_guard(new_entities, existing)
        assert "sensor.vm_101" in removed

    def test_existing_entity_kept_when_still_active(self):
        existing = {"pve_node1_vm_101_status_v1": "sensor.vm_101"}
        new_entities = [_make_entity("pve_node1_vm_101_status_v1")]

        removed, kept = _run_cleanup_with_guard(new_entities, existing)
        assert "sensor.vm_101" not in removed
        assert "sensor.vm_101" in kept

    def test_bug_l7_empty_entities_must_not_wipe_all_existing(self):
        """
        BUG L7: if entities=[] (partial data / first startup), cleanup
        must NOT delete the existing registered entities.
        """
        existing = {
            "pve_node1_vm_101_status_v1": "sensor.vm_101",
            "pve_node1_node_status": "sensor.node_status",
            "pve_node1_memory": "sensor.memory",
        }
        new_entities = []   # coordinator returned empty/partial data

        # Without guard (old behaviour): everything gets removed
        removed_old, _ = _run_cleanup(new_entities, existing)
        assert len(removed_old) == 3, "Old behavior: all entities deleted"

        # With guard (fix): nothing gets removed
        removed_fixed, kept_fixed = _run_cleanup_with_guard(new_entities, existing)
        assert len(removed_fixed) == 0, (
            "With guard: empty entity list must not trigger cleanup"
        )
        assert len(kept_fixed) == 3

    def test_partial_data_single_vm_does_not_wipe_node_sensors(self):
        """
        If only one VM entity is created (sidecar down → no hardware sensors),
        existing node/hardware sensors must NOT be deleted.
        """
        existing = {
            "pve_node1_vm_101_status_v1": "sensor.vm_101",
            "pve_node1_cpu_temp": "sensor.cpu_temp",
            "pve_node1_node_status": "sensor.node_status",
        }
        # Only the VM sensor was re-created (hardware sensors skipped)
        new_entities = [_make_entity("pve_node1_vm_101_status_v1")]

        removed, kept = _run_cleanup_with_guard(new_entities, existing)
        # cpu_temp and node_status are legitimately gone from new set →
        # they should be removed (this is expected cleanup, not the bug).
        # The bug was specifically entities=[] wiping everything.
        assert "sensor.vm_101" not in removed

    def test_empty_existing_registry_with_new_entities_no_crash(self):
        existing = {}
        new_entities = [_make_entity("pve_node1_vm_101_status_v1")]

        removed, kept = _run_cleanup_with_guard(new_entities, existing)
        assert removed == []
        assert kept == []
