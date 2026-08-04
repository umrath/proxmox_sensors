"""
Tests für Spannungs-/Lüfter-Erkennung der Hardware-Sensoren (Upstream-Merge).

Der Coordinator flacht lm-sensors pro Messwert ab:
    hardware["<chip>_<reading>"] = {"<reading>_input": <wert>, ...}

Neu:
- ProxmoxHardwareSensor erkennt fan / voltage / temperature am Input-Key.
- Spannung erhält Einheit "V", Lüfter "RPM", Temperatur bleibt "°C".
- Kuratierung (is_meaningful) filtert tote/unplausible Rails heraus.
"""

from unittest.mock import MagicMock
from custom_components.proxmox_sensors.sensor.hardware import ProxmoxHardwareSensor


def make_coordinator(hardware):
    coord = MagicMock()
    coord.config_entry.data = {"server_id": "node1"}
    coord.data = {"hardware": hardware}
    return coord


def make_sensor(key, hardware):
    coord = make_coordinator(hardware)
    return ProxmoxHardwareSensor(coord, key, "node1")


# ===========================================================================
# Typ-Erkennung
# ===========================================================================

class TestSensorTypeDetection:
    def test_temperature_reading_detected(self):
        key = "drivetemp-scsi-0-0_temp1"
        sensor = make_sensor(key, {key: {"temp1_input": 42.5}})
        assert sensor._sensor_type == "temperature"
        assert sensor.native_value == 42.5
        assert sensor._attr_native_unit_of_measurement == "°C"

    def test_voltage_reading_detected(self):
        key = "nct6798-isa-0290_in5"
        sensor = make_sensor(key, {key: {"in5_input": 2.0, "in5_min": 1.9}})
        assert sensor._sensor_type == "voltage"
        assert sensor.native_value == 2.0
        assert sensor._attr_native_unit_of_measurement == "V"
        assert sensor._attr_device_class == "voltage"

    def test_fan_reading_detected(self):
        key = "nct6798-isa-0290_fan2"
        sensor = make_sensor(key, {key: {"fan2_input": 1180}})
        assert sensor._sensor_type == "fan"
        assert sensor.native_value == 1180
        assert sensor._attr_native_unit_of_measurement == "RPM"


# ===========================================================================
# Regression: altes Fehlverhalten
# ===========================================================================

class TestOldBugsFixed:
    def test_voltage_not_mislabeled_as_temperature(self):
        """VORHER: eine 2.0-V-Spannung erschien als 2.0 °C Temperatur-Sensor."""
        key = "nct6798-isa-0290_in5"
        sensor = make_sensor(key, {key: {"in5_input": 2.0}})
        assert sensor._attr_native_unit_of_measurement != "°C"
        assert sensor._attr_native_unit_of_measurement == "V"

    def test_high_rpm_fan_not_dropped(self):
        """VORHER: Lüfter > 145 fielen durch den 1<f<145 Temperatur-Filter raus."""
        key = "nct6798-isa-0290_fan3"
        sensor = make_sensor(key, {key: {"fan3_input": 2500}})
        assert sensor.native_value == 2500
        assert sensor.is_meaningful() is True


# ===========================================================================
# Kuratierung (is_meaningful)
# ===========================================================================

class TestCuration:
    def test_temperature_always_meaningful(self):
        key = "drivetemp-scsi-0-0_temp1"
        sensor = make_sensor(key, {key: {"temp1_input": 41.0}})
        assert sensor.is_meaningful() is True

    def test_dead_fan_zero_rpm_filtered(self):
        key = "nct6798-isa-0290_fan1"
        sensor = make_sensor(key, {key: {"fan1_input": 0}})
        assert sensor._sensor_type == "fan"
        assert sensor.is_meaningful() is False

    def test_zero_voltage_rail_filtered(self):
        key = "nct6798-isa-0290_in0"
        sensor = make_sensor(key, {key: {"in0_input": 0}})
        assert sensor._sensor_type == "voltage"
        assert sensor.is_meaningful() is False

    def test_implausible_voltage_rail_filtered(self):
        key = "nct6798-isa-0290_in7"
        sensor = make_sensor(key, {key: {"in7_input": 99.0}})
        assert sensor._sensor_type == "voltage"
        assert sensor.is_meaningful() is False

    def test_live_fan_kept(self):
        key = "nct6798-isa-0290_fan2"
        sensor = make_sensor(key, {key: {"fan2_input": 900}})
        assert sensor.is_meaningful() is True

    def test_real_voltage_rail_kept(self):
        key = "nct6798-isa-0290_in1"
        sensor = make_sensor(key, {key: {"in1_input": 3.3}})
        assert sensor.is_meaningful() is True


# ===========================================================================
# Regression: CPU-Sensor darf nicht als fan/voltage fehl-typisiert werden
# ===========================================================================

class TestCpuKeyNeverFanOrVoltage:
    """
    Ein Super-I/O-Messwert mit CPU-Label (z. B. 'CPU Fan', 'Vcore') kann laut
    Setup-Klassifizierung ('cpu'/'core'-Substring) zum aggregierten CPU-Sensor
    werden. _detect_sensor_type MUSS ihn dann als 'temperature' behandeln,
    sonst ignoriert _parse die tempN_input-Werte und der CPU-Sensor
    verschwindet oder liefert Unsinn.
    """

    def test_cpu_fan_labelled_key_typed_temperature(self):
        # Flacher Key enthält 'cpu' -> _is_cpu True; Input-Key ist fan1_input.
        cpu_key = "nct6798-isa-0290_cpu fan"
        hardware = {
            cpu_key: {"fan1_input": 1150},
            "coretemp-isa-0000_package id 0": {"temp1_input": 52.0, "temp1_crit": 100.0},
        }
        sensor = make_sensor(cpu_key, hardware)
        assert sensor._is_cpu is True
        assert sensor._sensor_type == "temperature"
        # CPU-Aggregation liest die echte coretemp-Package-Temperatur.
        assert sensor.native_value == 52.0
        assert sensor._attr_native_unit_of_measurement == "°C"

    def test_vcore_labelled_key_typed_temperature(self):
        cpu_key = "nct6798-isa-0290_vcore"
        hardware = {
            cpu_key: {"in0_input": 1.1},
            "k10temp-pci-00c3_tctl": {"temp1_input": 55.0},
        }
        sensor = make_sensor(cpu_key, hardware)
        assert sensor._is_cpu is True
        assert sensor._sensor_type == "temperature"
        # Aggregiert tctl als package -> 55.0, nicht die 1.1 V.
        assert sensor.native_value == 55.0
        # Kein invalider device_class=voltage + unit=°C Kombi.
        assert sensor._attr_device_class == "temperature"

    def test_vcore_voltage_not_leaked_into_cpu_value_without_die_temp(self):
        """Ohne echten Die-Temp-Treiber darf eine 'core'-benannte Spannung
        NICHT als Kern-Temperatur in den CPU-Wert einfließen."""
        cpu_key = "nct6798-isa-0290_vcore"
        hardware = {cpu_key: {"in0_input": 1.104}}
        sensor = make_sensor(cpu_key, hardware)
        assert sensor._is_cpu is True
        # Keine Package-/tctl-Temperatur vorhanden -> kein gültiger Wert,
        # statt der fälschlichen 1.1 °C aus dem Spannungs-Rail.
        assert sensor.native_value is None

    def test_vcore_voltage_not_polluting_cpu_attributes(self):
        """Die CPU-Attribute dürfen kein 1.1-°C-Pseudo-Kern aus Vcore enthalten."""
        cpu_key = "coretemp-isa-0000_package id 0"
        hardware = {
            cpu_key: {"temp1_input": 52.0},
            "nct6798-isa-0290_vcore": {"in0_input": 1.104},
        }
        sensor = make_sensor(cpu_key, hardware)
        attrs = sensor.extra_state_attributes
        assert all(v != 1.1 for v in attrs.values())
        assert "nct6798_isa_0290_vcore" not in attrs
