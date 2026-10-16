"""
messaging.py - connects drivers, the data contract, and the message bus

Publisher side:  driver.read() -> SensorReading (validated) -> JSON -> bus
Subscriber side: bus -> JSON -> validated against schema -> accepted or rejected
"""
from pydantic import ValidationError

from bus import MessageBus
from schema import SensorReading, make_reading
from sensor import Sensor

TOPIC_ROOT = "lab"


def topic_for(sensor_type: str, sensor_id: str, root: str = TOPIC_ROOT) -> str:
    return f"{root}/{sensor_type}/{sensor_id}"


def publish_reading(bus: MessageBus, sensor: Sensor, sensor_id: str,
                    sensor_type: str, root: str = TOPIC_ROOT) -> SensorReading:
    """Read a connected sensor and publish the reading as JSON."""
    reading = make_reading(sensor_id, sensor_type, sensor.read())
    bus.publish(topic_for(sensor_type, sensor_id, root), reading.model_dump_json())
    return reading


class ReadingCollector:
    """A subscriber that checks every message against the data contract."""

    def __init__(self):
        self.accepted = []   # valid SensorReading objects
        self.rejected = []   # (topic, payload, reason) for bad messages

    def __call__(self, topic: str, payload: str) -> None:
        try:
            self.accepted.append(SensorReading.model_validate_json(payload))
        except ValidationError as error:
            self.rejected.append((topic, payload, str(error)))
