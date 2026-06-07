"""Regression tests for logic/guest_keys.py — pure Python, no HA stubs needed."""

import pytest
from custom_components.proxmox_sensors.logic.guest_keys import (
    make_guest_key,
    matches_selected_guest,
)


class TestMakeGuestKey:
    def test_format_is_node_colon_vmid(self):
        assert make_guest_key("node1", 101) == "node1:101"

    def test_node_is_lowercased(self):
        assert make_guest_key("NODE1", 101) == "node1:101"

    def test_vmid_as_string(self):
        assert make_guest_key("pve", "42") == "pve:42"

    def test_mixed_case_node(self):
        assert make_guest_key("PVE-Node", 200) == "pve-node:200"


class TestMatchesSelectedGuest:
    # ---- empty / None selection → matches everything ----

    def test_empty_list_matches_all(self):
        assert matches_selected_guest([], "node1", 101)

    def test_none_matches_all(self):
        assert matches_selected_guest(None, "node1", 101)

    # ---- raw vmid selection ----

    def test_raw_vmid_matches(self):
        assert matches_selected_guest(["101"], "node1", 101)

    def test_raw_vmid_int_matches(self):
        assert matches_selected_guest([101], "node1", 101)

    def test_raw_vmid_no_match(self):
        assert not matches_selected_guest(["999"], "node1", 101)

    def test_raw_vmid_is_node_agnostic(self):
        """Raw vmid "101" must match regardless of which node hosts the VM."""
        assert matches_selected_guest(["101"], "node2", 101)
        assert matches_selected_guest(["101"], "node3", 101)

    # ---- node:vmid key selection ----

    def test_node_vmid_key_matches_correct_node(self):
        assert matches_selected_guest(["node1:101"], "node1", 101)

    def test_node_vmid_key_does_not_match_different_node(self):
        """Explicit node:vmid selection is node-scoped."""
        assert not matches_selected_guest(["node1:101"], "node2", 101)

    def test_node_vmid_key_does_not_match_different_vmid(self):
        assert not matches_selected_guest(["node1:200"], "node1", 101)

    # ---- guest_key parameter ----

    def test_explicit_guest_key_matches(self):
        assert matches_selected_guest(["node1:101"], "node1", 101, "node1:101")

    def test_explicit_guest_key_overrides_canonical(self):
        """guest_key is tried directly; if it's in the selection it matches."""
        assert matches_selected_guest(["node1:101"], "node2", 101, "node1:101")

    # ---- multiple selections ----

    def test_one_of_many_matches(self):
        assert matches_selected_guest(["200", "101", "300"], "node1", 101)

    def test_none_of_many_matches(self):
        assert not matches_selected_guest(["200", "300"], "node1", 101)
