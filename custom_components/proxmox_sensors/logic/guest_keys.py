"""Utilities for stable guest keys across cluster nodes"""

from __future__ import annotations


def make_guest_key(node, vmid):
    """Build a node-aware guest key using the ``node:vmid`` format."""
    return f"{str(node).lower()}:{str(vmid)}"


def matches_selected_guest(selected_values, node, vmid, guest_key=None):
    """Return ``True`` when a selected value matches a guest.

    Supports legacy selections by raw VMID and newer selections by guest key.

    ``selected_values`` carries three distinct states:

    * ``None`` — nothing stored (legacy entry): show every guest.
    * ``[]`` — the user deselected everything on purpose: show none.
    * non-empty list — show only the listed guests.

    Collapsing the first two (``if not selected_values``) made an explicitly
    emptied selection behave like "show all", so deselecting every VM had no
    effect.
    """
    if selected_values is None:
        return True

    if not selected_values:
        return False

    normalized = {str(value) for value in selected_values}
    vmid_str = str(vmid)
    canonical_key = make_guest_key(node, vmid)
    explicit_key = str(guest_key) if guest_key is not None else canonical_key
    raw_node_key = f"{node}:{vmid_str}"

    return any(
        candidate in normalized
        for candidate in (vmid_str, explicit_key, canonical_key, raw_node_key)
    )
