"""
Restliche Auswahl-Stellen aus 5.0.3, die die Coverage-Messung als ungedeckt
auswies: die Vorauswahl im Optionen-Dialog und die PBS-Datastore-Auswahl.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock

import custom_components.proxmox_sensors.coordinator as coord_mod


# ===========================================================================
# options_flow: Vorauswahl der Checkboxen
# ===========================================================================

def _preselect(stored, options):
    """Spiegelt die Helferfunktion aus options_flow.async_step_init.

    Dort lokal definiert und deshalb nicht direkt importierbar; die Semantik ist
    hier festgenagelt, damit eine Rückkehr zu `stored or list(options)`
    auffällt.
    """
    if stored is None:
        stored = list(options.keys())
    return [item for item in stored if item in options]


OPTIONS = {"101": "vm-a", "202": "vm-b"}


class TestOptionsPreselection:

    def test_nothing_stored_preselects_everything(self):
        assert set(_preselect(None, OPTIONS)) == {"101", "202"}

    def test_empty_selection_stays_empty(self):
        """`stored or list(...)` hätte hier alles wieder angehakt."""
        assert _preselect([], OPTIONS) == []

    def test_explicit_selection_is_kept(self):
        assert _preselect(["101"], OPTIONS) == ["101"]

    def test_stale_entries_are_dropped(self):
        """Ein inzwischen gelöschter Gast darf nicht vorausgewählt bleiben."""
        assert _preselect(["101", "999"], OPTIONS) == ["101"]

    def test_options_flow_uses_this_semantics(self):
        """Verankert die Implementierung: kein `or`-Fallback mehr."""
        import inspect
        import custom_components.proxmox_sensors.options_flow as of

        src = inspect.getsource(of)
        assert 'conf.get("selected_vms") or list(' not in src
        assert "def _preselect(" in src


# ===========================================================================
# coordinator: PBS-Datastore-Auswahl
# ===========================================================================

def _pbs_client(datastores):
    """`datastores` are store NAMES — that is what
    ProxmoxClient.get_pbs_datastores() returns."""
    client = MagicMock()
    client._server_type = "PBS"
    client.get_pbs_datastores = AsyncMock(return_value=datastores)
    client.get_pbs_datastore_status = AsyncMock(return_value={"total": 1, "used": 0})
    client.get_pbs_datastore_usage = AsyncMock(return_value={})
    client.get_pbs_snapshots = AsyncMock(return_value=[])
    client.get_pbs_gc = AsyncMock(return_value={})
    client.get_pbs_tasks = AsyncMock(return_value=[])
    client.get_pbs_version = AsyncMock(return_value={})
    client.get_pbs_node_status = AsyncMock(return_value={})
    client.get_pbs_backup_list = AsyncMock(return_value=[])
    return client


def _pbs_entry(**overrides):
    entry = MagicMock()
    entry.data = {
        "node": "pbs1",
        "platform_type": "PBS",
        "server_id": "pbs1",
        **overrides,
    }
    entry.options = {}
    return entry


class TestPbsDatastoreSelection:

    @pytest.mark.asyncio
    async def test_nothing_stored_queries_all_datastores(self):
        client = _pbs_client(["backup1", "backup2"])
        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _pbs_entry(), client
        )
        await coordinator.update_method()
        client.get_pbs_datastores.assert_awaited()

    @pytest.mark.asyncio
    async def test_explicit_selection_skips_the_discovery_call(self):
        client = _pbs_client(["backup1"])
        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _pbs_entry(selected_storage=["backup1"]), client
        )
        await coordinator.update_method()
        client.get_pbs_datastores.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_selection_means_none_not_all(self):
        """Vorher hätte `if not selected` hier alle Datastores entdeckt."""
        client = _pbs_client(["backup1", "backup2"])
        coordinator = await coord_mod.create_proxmox_coordinator(
            MagicMock(), _pbs_entry(selected_storage=[]), client
        )
        result = await coordinator.update_method()

        client.get_pbs_datastores.assert_not_awaited()
        assert result["pbs_datastores"] == {}
