"""
Tests für H1: build_cluster_notifications_data in cluster_notifications.py
ist zweimal definiert. Die zweite Definition überschreibt die erste still und
gibt kein 'notifications_configured'-Feld zurück und hat keinen 'not_configured'-Zweig.
"""

import pytest
from custom_components.proxmox_sensors.logic.cluster_notifications import (
    build_cluster_notifications_data,
)


class TestBuildClusterNotificationsDataNoNotify:

    def test_returns_not_configured_for_package_updates(self):
        result = build_cluster_notifications_data({}, [])
        assert result["package_updates"] == "not_configured"

    def test_returns_not_configured_for_replication(self):
        result = build_cluster_notifications_data({}, [])
        assert result["replication"] == "not_configured"

    def test_returns_not_configured_for_fencing(self):
        result = build_cluster_notifications_data({}, [])
        assert result["fencing"] == "not_configured"

    def test_notifications_configured_false_when_no_notify(self):
        result = build_cluster_notifications_data({}, [])
        assert result["notifications_configured"] is False

    def test_notifications_configured_false_when_none_input(self):
        result = build_cluster_notifications_data(None, [])
        assert result["notifications_configured"] is False

    def test_notify_raw_is_none_when_no_notify(self):
        result = build_cluster_notifications_data({}, [])
        assert result["notify_raw"] is None


class TestBuildClusterNotificationsDataWithNotify:

    def test_notifications_configured_true_when_notify_set(self):
        opts = {"notify": "package-updates=always"}
        result = build_cluster_notifications_data(opts, [])
        assert result["notifications_configured"] is True

    def test_package_updates_parsed(self):
        opts = {"notify": "package-updates=always"}
        result = build_cluster_notifications_data(opts, [])
        assert result["package_updates"] == "always"

    def test_replication_parsed(self):
        opts = {"notify": "package-updates=always,replication=error"}
        result = build_cluster_notifications_data(opts, [])
        assert result["replication"] == "error"

    def test_notify_raw_preserved(self):
        raw = "package-updates=always"
        result = build_cluster_notifications_data({"notify": raw}, [])
        assert result["notify_raw"] == raw
