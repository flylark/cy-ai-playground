"""
test_schema.py - tests for the data contract

Good readings must pass. Bad readings must be rejected.
"""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from drivers import SimulatedTemperatureSensor
from schema import SensorReading, make_reading

NOW = datetime.now(timezone.utc)


def valid_fields():
    """A known-good reading, which each test can break in one way."""
    return {
        "sensor_id": "incubator1-temp",
        "sensor_type": "temperature",
        "value": 22.5,
        "unit": "degC",
        # "unit": "degF",
        "timestamp": NOW,
    }


def test_valid_reading_is_accepted():
    reading = SensorReading(**valid_fields())
    assert reading.value == 22.5
    assert reading.schema_version == "1.0"


def test_missing_field_is_rejected():
    fields = valid_fields()
    del fields["unit"]
    with pytest.raises(ValidationError):
        SensorReading(**fields)


def test_unknown_field_is_rejected():
    fields = valid_fields()
    fields["color"] = "blue"
    with pytest.raises(ValidationError):
        SensorReading(**fields)


def test_text_value_is_rejected():
    fields = valid_fields()
    fields["value"] = "22.5"          # a string, not a number
    with pytest.raises(ValidationError):
        SensorReading(**fields)


def test_wrong_unit_for_type_is_rejected():
    fields = valid_fields()
    fields["unit"] = "kPa"            # temperature in kPa makes no sense
    with pytest.raises(ValidationError):
        SensorReading(**fields)


def test_empty_sensor_id_is_rejected():
    fields = valid_fields()
    fields["sensor_id"] = ""
    with pytest.raises(ValidationError):
        SensorReading(**fields)


def test_json_round_trip():
    # This is what will travel over the message bus
    original = SensorReading(**valid_fields())
    as_json = original.model_dump_json()
    restored = SensorReading.model_validate_json(as_json)
    assert restored == original


def test_driver_reading_fits_the_schema():
    # Connects the two contracts: driver output -> data contract
    sensor = SimulatedTemperatureSensor()
    sensor.connect()
    reading = make_reading("incubator1-temp", "temperature", sensor.read())
    sensor.close()
    assert reading.unit == "degC"
