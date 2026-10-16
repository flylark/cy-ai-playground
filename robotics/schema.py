"""
schema.py - THE DATA CONTRACT (schema version 1.0)

sensor.py defines how code TALKS TO a sensor (methods).
This file defines what a READING LOOKS LIKE as data (fields).

Every reading sent over the message bus or saved to the database
must match this shape. Anything that doesn't is rejected.
"""
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"

# Which unit belongs to which sensor type
UNITS = {
    "temperature": "degC",
    "pressure": "kPa",
    "humidity": "%RH",
}


class SensorReading(BaseModel):
    # Strict contract: no unknown fields, no silent type conversion
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: Literal["1.0"] = SCHEMA_VERSION
    sensor_id: str = Field(min_length=1)           # e.g. "incubator1-temp"
    sensor_type: Literal["temperature", "pressure", "humidity"]
    value: float = Field(allow_inf_nan=False)      # must be a real number
    unit: Literal["degC", "kPa", "%RH"]
    timestamp: datetime                            # when it was measured

    @model_validator(mode="after")
    def unit_matches_type(self):
        # Cross-field rule: a temperature reading must be in degC, etc.
        expected = UNITS[self.sensor_type]
        if self.unit != expected:
            raise ValueError(
                f"{self.sensor_type} readings must use '{expected}', got '{self.unit}'"
            )
        return self


def make_reading(sensor_id: str, sensor_type: str, value: float) -> SensorReading:
    """Helper: build a valid reading with the correct unit and current time."""
    return SensorReading(
        sensor_id=sensor_id,
        sensor_type=sensor_type,
        value=value,
        unit=UNITS[sensor_type],
        timestamp=datetime.now(timezone.utc),
    )
