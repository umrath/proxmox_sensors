"""
Tests für S2: urllib3.disable_warnings() wird auf Modulebene aufgerufen.

Das unterdrückt InsecureRequestWarning global für den gesamten Python-Prozess,
auch wenn der Nutzer SSL-Verifizierung aktiviert hat — also ohne Grund.

Fix: disable_warnings() nur in _build_client_sync() aufrufen, und nur wenn
verify_ssl=False ist.
"""

import sys
from unittest.mock import MagicMock, patch, call
import pytest


def _make_urllib3_stub():
    stub = MagicMock()
    stub.exceptions = MagicMock()
    stub.exceptions.InsecureRequestWarning = RuntimeWarning
    return stub


class TestUrllib3DisableWarningsScope:

    def test_disable_warnings_not_called_at_import_time(self):
        """Module import must not suppress warnings globally."""
        urllib3_stub = _make_urllib3_stub()
        modules_to_remove = [
            k for k in sys.modules if "proxmox_sensors.api" in k
        ]
        for m in modules_to_remove:
            del sys.modules[m]

        with patch.dict(
            sys.modules,
            {"urllib3": urllib3_stub, "proxmoxer": MagicMock(), "requests": MagicMock()},
        ):
            import importlib
            import custom_components.proxmox_sensors.api as api_mod
            importlib.reload(api_mod)

        urllib3_stub.disable_warnings.assert_not_called()

    def test_disable_warnings_called_when_ssl_disabled(self):
        """When verify_ssl=False, disable_warnings must be called during client init."""
        from custom_components.proxmox_sensors.api import ProxmoxClient
        client = ProxmoxClient(
            host="192.168.1.1",
            user="root@pam",
            password="secret",
            verify_ssl=False,
        )
        urllib3_stub = _make_urllib3_stub()
        proxmox_stub = MagicMock()
        with (
            patch("custom_components.proxmox_sensors.api.urllib3", urllib3_stub),
            patch("custom_components.proxmox_sensors.api.ProxmoxAPI", proxmox_stub),
        ):
            client._build_client_sync()

        urllib3_stub.disable_warnings.assert_called_once_with(
            urllib3_stub.exceptions.InsecureRequestWarning
        )

    def test_disable_warnings_not_called_when_ssl_enabled(self):
        """When verify_ssl=True, disable_warnings must NOT be called."""
        from custom_components.proxmox_sensors.api import ProxmoxClient
        client = ProxmoxClient(
            host="192.168.1.1",
            user="root@pam",
            password="secret",
            verify_ssl=True,
        )
        urllib3_stub = _make_urllib3_stub()
        proxmox_stub = MagicMock()
        with (
            patch("custom_components.proxmox_sensors.api.urllib3", urllib3_stub),
            patch("custom_components.proxmox_sensors.api.ProxmoxAPI", proxmox_stub),
        ):
            client._build_client_sync()

        urllib3_stub.disable_warnings.assert_not_called()
