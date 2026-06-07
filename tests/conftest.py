"""
Pytest configuration: stubs out homeassistant and related packages so that
the custom-component modules can be imported without a full HA installation.
All stubs are in place before any test module is collected.
"""

import sys
import os
from types import ModuleType
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Make the project root importable so `custom_components.proxmox_sensors.*`
# resolves correctly.
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


# ---------------------------------------------------------------------------
# Concrete stub classes — MagicMock alone is not enough for classes that the
# production code inherits from (MRO matters).
# ---------------------------------------------------------------------------

class _UpdateFailed(Exception):
    """Stub for homeassistant.helpers.update_coordinator.UpdateFailed."""


class _CoordinatorEntity:
    """Stub for CoordinatorEntity — stores the coordinator reference."""

    def __init__(self, coordinator):
        self.coordinator = coordinator


class _SensorEntity:
    """Minimal stub for SensorEntity."""

    _attr_has_entity_name: bool = False
    _attr_name: str | None = None
    _attr_native_unit_of_measurement: str | None = None
    _attr_unique_id: str | None = None
    _attr_icon: str | None = None
    _attr_translation_key: str | None = None
    _attr_state_class: str | None = None
    _attr_device_class: str | None = None

    @property
    def native_value(self):
        try:
            return self._get_value()
        except Exception:
            return None

    def _get_value(self):  # pragma: no cover
        raise NotImplementedError

    @property
    def extra_state_attributes(self):
        return {}


class _DataUpdateCoordinator:
    """Stub for DataUpdateCoordinator — only the parts tests touch."""

    def __init__(self, *args, **kwargs):
        self.data = {}
        self.config_entry = MagicMock()
        self.config_entry.data = {}

    def async_add_listener(self, cb):
        pass


# ---------------------------------------------------------------------------
# Build stub module objects
# ---------------------------------------------------------------------------

def _make_module(name: str) -> ModuleType:
    mod = ModuleType(name)
    sys.modules[name] = mod
    return mod


# homeassistant (root)
_ha = _make_module("homeassistant")

# homeassistant.helpers
_ha_helpers = _make_module("homeassistant.helpers")
_ha.helpers = _ha_helpers

# homeassistant.helpers.update_coordinator
_ha_uc = _make_module("homeassistant.helpers.update_coordinator")
_ha_uc.UpdateFailed = _UpdateFailed
_ha_uc.CoordinatorEntity = _CoordinatorEntity
_ha_uc.DataUpdateCoordinator = _DataUpdateCoordinator
_ha_helpers.update_coordinator = _ha_uc

# homeassistant.helpers.entity_platform  (used by __init__.py — not needed in tests)
_ha_ep = _make_module("homeassistant.helpers.entity_platform")
_ha_ep.AddEntitiesCallback = MagicMock
_ha_helpers.entity_platform = _ha_ep

# homeassistant.helpers.entity_registry
_ha_er = _make_module("homeassistant.helpers.entity_registry")
_ha_er.async_get = MagicMock(return_value=MagicMock())
_ha_er.async_entries_for_config_entry = MagicMock(return_value=[])
_ha_er.async_entries_for_device = MagicMock(return_value=[])
_ha_helpers.entity_registry = _ha_er

# homeassistant.helpers.device_registry
_ha_dr = _make_module("homeassistant.helpers.device_registry")
_ha_dr.async_get = MagicMock(return_value=MagicMock())
_ha_dr.async_entries_for_config_entry = MagicMock(return_value=[])
_ha_helpers.device_registry = _ha_dr

# homeassistant.helpers.restore_state
_ha_rs = _make_module("homeassistant.helpers.restore_state")
_ha_rs.RestoreEntity = object  # plain base class stub
_ha_helpers.restore_state = _ha_rs

# homeassistant.components
_ha_comp = _make_module("homeassistant.components")
_ha.components = _ha_comp

# homeassistant.components.sensor
_ha_sensor = _make_module("homeassistant.components.sensor")
_ha_sensor.SensorEntity = _SensorEntity
_ha_sensor.SensorStateClass = MagicMock()
_ha_comp.sensor = _ha_sensor

# homeassistant.components.binary_sensor
_ha_bs = _make_module("homeassistant.components.binary_sensor")
_ha_bs.BinarySensorEntity = object
_ha_comp.binary_sensor = _ha_bs

# homeassistant.components.persistent_notification
_ha_pn = _make_module("homeassistant.components.persistent_notification")
_ha_pn.create = MagicMock()
_ha_pn.dismiss = MagicMock()
_ha_comp.persistent_notification = _ha_pn

# homeassistant.core
_ha_core = _make_module("homeassistant.core")
_ha_core.HomeAssistant = MagicMock
_ha_core.ServiceCall = MagicMock
_ha_core.callback = lambda f: f   # identity decorator
_ha.core = _ha_core

# homeassistant.const
_ha_const = _make_module("homeassistant.const")
_ha_const.Platform = MagicMock()
_ha_const.STATE_UNAVAILABLE = "unavailable"
_ha_const.STATE_UNKNOWN = "unknown"
_ha_const.PERCENTAGE = "%"
_ha_const.UnitOfInformation = MagicMock()
_ha.const = _ha_const

# homeassistant.config_entries
_ha_ce = _make_module("homeassistant.config_entries")
_ha_ce.ConfigEntry = MagicMock
_ha_ce.config_entries = MagicMock
_ha.config_entries = _ha_ce

# homeassistant.exceptions
_ha_exc = _make_module("homeassistant.exceptions")
_ha_exc.ConfigEntryNotReady = Exception
_ha.exceptions = _ha_exc

# homeassistant.data_entry_flow
_ha_def = _make_module("homeassistant.data_entry_flow")
_ha_def.FlowResult = MagicMock
_ha.data_entry_flow = _ha_def

# homeassistant.helpers.config_validation (used by config_flow)
_ha_cv = _make_module("homeassistant.helpers.config_validation")
_ha_cv.multi_select = MagicMock
_ha_helpers.config_validation = _ha_cv

# voluptuous (used by config_flow — not needed in unit tests but must be importable)
_vol = _make_module("voluptuous")
_vol.Schema = MagicMock
_vol.Required = MagicMock
_vol.Optional = MagicMock
_vol.In = MagicMock

# proxmoxer (used by api.py)
_px = _make_module("proxmoxer")
_px.ProxmoxAPI = MagicMock

# requests (used by api.py)
_req = _make_module("requests")
_req.get = MagicMock()
_req.post = MagicMock()
_req.exceptions = ModuleType("requests.exceptions")
_req.exceptions.RequestException = Exception
sys.modules["requests"] = _req
sys.modules["requests.exceptions"] = _req.exceptions

# urllib3
_urllib3 = _make_module("urllib3")
_urllib3.disable_warnings = MagicMock()
_urllib3.exceptions = ModuleType("urllib3.exceptions")
_urllib3.exceptions.InsecureRequestWarning = Warning
sys.modules["urllib3"] = _urllib3
sys.modules["urllib3.exceptions"] = _urllib3.exceptions

# dateutil (used by sensor/cluster.py)
_dateutil = _make_module("dateutil")
_dateutil_parser = _make_module("dateutil.parser")
_dateutil_parser.isoparse = MagicMock()
_dateutil.parser = _dateutil_parser
