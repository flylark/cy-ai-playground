"""
test_store.py - tests for the database (data service)

Uses ":memory:", a temporary database that disappears after each test.
"""
import sqlite3
from datetime import datetime, timezone

import pytest

from bus import InMemoryBus
from drivers import SimulatedTemperatureSensor
from messaging import publish_reading
from schema import SensorReading, make_reading
from store import ReadingStore

T1 = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 4, 12, 1, tzinfo=timezone.utc)


def reading(sensor_id="inc1-temp", sensor_type="temperature", value=22.0,
            unit="degC", timestamp=T1):
    return SensorReading(sensor_id=sensor_id, sensor_type=sensor_type,
                         value=value, unit=unit, timestamp=timestamp)


@pytest.fixture
def store():
    s = ReadingStore(":memory:")
    yield s
    s.close()


def test_saved_reading_can_be_queried(store):
    store.save(reading(value=22.5))
    rows = store.query("SELECT sensor_id, value FROM readings")
    assert rows == [("inc1-temp", 22.5)]


def test_sensor_is_registered_once(store):
    store.save(reading(timestamp=T1))
    store.save(reading(timestamp=T2))
    assert store.query("SELECT COUNT(*) FROM sensors") == [(1,)]
    assert store.query("SELECT COUNT(*) FROM readings") == [(2,)]


def test_duplicate_reading_is_ignored(store):
    # QoS 1 can deliver the same message twice; the database stores it once
    assert store.save(reading()) is True
    assert store.save(reading()) is False
    assert store.query("SELECT COUNT(*) FROM readings") == [(1,)]
    assert store.duplicates == 1


def test_same_id_with_different_type_is_rejected(store):
    store.save(reading(sensor_id="inc1", sensor_type="temperature", unit="degC"))
    with pytest.raises(ValueError):
        store.save(reading(sensor_id="inc1", sensor_type="pressure",
                           unit="kPa", value=101.0, timestamp=T2))


def test_foreign_key_blocks_reading_for_unknown_sensor(store):
    # The database itself enforces the link between the two tables
    with pytest.raises(sqlite3.IntegrityError):
        store._conn.execute(
            "INSERT INTO readings (sensor_id, value, timestamp, schema_version) "
            "VALUES ('ghost', 1.0, '2026-10-04T12:00:00+00:00', '1.0')"
        )


def test_join_average_per_sensor_type(store):
    store.save(reading(value=20.0, timestamp=T1))
    store.save(reading(value=24.0, timestamp=T2))
    rows = store.query("""
        SELECT s.sensor_type, AVG(r.value)
        FROM readings AS r
        JOIN sensors AS s ON s.sensor_id = r.sensor_id
        GROUP BY s.sensor_type
    """)
    assert rows == [("temperature", 22.0)]


def test_end_to_end_bus_to_database(store):
    bus = InMemoryBus()
    bus.subscribe("lab/#", store)
    sensor = SimulatedTemperatureSensor()
    sensor.connect()

    publish_reading(bus, sensor, "inc1-temp", "temperature")
    bus.publish("lab/temperature/inc1-temp", "garbage")

    assert store.saved == 1
    assert len(store.rejected) == 1
