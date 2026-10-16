"""
test_messaging.py - tests for the message bus and pipeline

All tests use InMemoryBus, so they need no network and run fine in CI.
"""
import pytest

from bus import InMemoryBus, MessageBus, topic_matches
from drivers import SimulatedPressureSensor, SimulatedTemperatureSensor
from messaging import ReadingCollector, publish_reading


@pytest.mark.parametrize("topic_filter, topic, expected", [
    ("lab/temperature/inc1", "lab/temperature/inc1", True),
    ("lab/temperature/inc1", "lab/pressure/inc1", False),
    ("lab/+/inc1", "lab/pressure/inc1", True),
    ("lab/+", "lab/pressure/inc1", False),
    ("lab/#", "lab/pressure/inc1", True),
    ("lab/#", "other/pressure/inc1", False),
])
def test_topic_matching(topic_filter, topic, expected):
    assert topic_matches(topic_filter, topic) == expected


def test_bus_contract_cannot_be_used_directly():
    with pytest.raises(TypeError):
        MessageBus()


def connected(sensor):
    sensor.connect()
    return sensor


def test_published_reading_is_received_and_valid():
    bus = InMemoryBus()
    collector = ReadingCollector()
    bus.subscribe("lab/#", collector)

    publish_reading(bus, connected(SimulatedTemperatureSensor()), "inc1", "temperature")

    assert len(collector.accepted) == 1
    assert collector.accepted[0].sensor_id == "inc1"
    assert collector.rejected == []


def test_subscriber_only_gets_matching_topics():
    bus = InMemoryBus()
    temperature_only = ReadingCollector()
    bus.subscribe("lab/temperature/#", temperature_only)

    publish_reading(bus, connected(SimulatedTemperatureSensor()), "inc1", "temperature")
    publish_reading(bus, connected(SimulatedPressureSensor()), "inc1", "pressure")

    assert len(temperature_only.accepted) == 1
    assert temperature_only.accepted[0].sensor_type == "temperature"


def test_invalid_message_is_rejected_not_crashed():
    bus = InMemoryBus()
    collector = ReadingCollector()
    bus.subscribe("lab/#", collector)

    bus.publish("lab/temperature/inc1", "this is not JSON")
    bus.publish("lab/temperature/inc1",
                '{"schema_version": "1.0", "sensor_id": "inc1", '
                '"sensor_type": "temperature", "value": 22.0, '
                '"unit": "kPa", "timestamp": "2026-10-04T12:00:00Z"}')

    assert collector.accepted == []
    assert len(collector.rejected) == 2
