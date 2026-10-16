"""
store.py - THE DATA SERVICE: saves validated readings to SQLite

Database schema (two tables):

  sensors                        readings
  ---------------------          ------------------------------
  sensor_id   (primary key) <--- sensor_id   (foreign key)
  sensor_type                    reading_id  (primary key)
  unit                           value
  first_seen                     timestamp
                                 schema_version

Why two tables? Facts about a SENSOR (its type, its unit) are stored
once, not repeated in every reading. Readings link to their sensor.
"""
import sqlite3
import threading
from datetime import datetime, timezone

from pydantic import ValidationError

from schema import SensorReading

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sensors (
    sensor_id    TEXT PRIMARY KEY,
    sensor_type  TEXT NOT NULL
                 CHECK (sensor_type IN ('temperature', 'pressure', 'humidity')),
    unit         TEXT NOT NULL,
    first_seen   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS readings (
    reading_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    sensor_id       TEXT NOT NULL REFERENCES sensors(sensor_id),
    value           REAL NOT NULL,
    timestamp       TEXT NOT NULL,
    schema_version  TEXT NOT NULL,
    UNIQUE (sensor_id, timestamp)   -- blocks duplicates from QoS 1 redelivery
);

-- Makes "readings for one sensor over time" queries fast
CREATE INDEX IF NOT EXISTS idx_readings_sensor_time
    ON readings (sensor_id, timestamp);
"""


class ReadingStore:
    """A subscriber that validates messages and saves them to the database."""

    def __init__(self, path: str = ":memory:"):
        # check_same_thread=False: MQTT delivers messages on a background thread
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA_SQL)
        self._lock = threading.Lock()
        self.saved = 0
        self.duplicates = 0
        self.rejected = []  # (topic, payload, reason)

    def save(self, reading: SensorReading) -> bool:
        """Save one reading. Returns False if it was a duplicate."""
        with self._lock, self._conn:  # 'with conn' = commit, or roll back on error
            self._register_sensor(reading)
            cursor = self._conn.execute(
                "INSERT OR IGNORE INTO readings "
                "(sensor_id, value, timestamp, schema_version) VALUES (?, ?, ?, ?)",
                (reading.sensor_id, reading.value,
                 reading.timestamp.isoformat(), reading.schema_version),
            )
        is_new = cursor.rowcount == 1
        if is_new:
            self.saved += 1
        else:
            self.duplicates += 1
        return is_new

    def _register_sensor(self, reading: SensorReading) -> None:
        self._conn.execute(
            "INSERT OR IGNORE INTO sensors (sensor_id, sensor_type, unit, first_seen) "
            "VALUES (?, ?, ?, ?)",
            (reading.sensor_id, reading.sensor_type, reading.unit,
             datetime.now(timezone.utc).isoformat()),
        )
        (known_type,) = self._conn.execute(
            "SELECT sensor_type FROM sensors WHERE sensor_id = ?", (reading.sensor_id,)
        ).fetchone()
        if known_type != reading.sensor_type:
            raise ValueError(
                f"sensor_id '{reading.sensor_id}' is already registered as "
                f"{known_type}, not {reading.sensor_type}"
            )

    def __call__(self, topic: str, payload: str) -> None:
        """Message bus callback: validate, then save or reject."""
        try:
            self.save(SensorReading.model_validate_json(payload))
        except (ValidationError, ValueError) as error:
            self.rejected.append((topic, payload, str(error)))

    def query(self, sql: str, params: tuple = ()) -> list:
        """Run a SELECT and return all rows."""
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def close(self) -> None:
        self._conn.close()
